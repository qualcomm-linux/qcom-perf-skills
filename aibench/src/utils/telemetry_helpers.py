"""
telemetry_helpers.py - Shared helper functions for benchmark telemetry lifecycle.

Provides consistent push/start (setup) and stop/pull (teardown) logic so every
benchmark's setup()/teardown() calls the same well-tested code path instead of
duplicating it across each benchmark implementation.

Note: Orphaned-process/stale-file cleanup on the device itself is handled
inside start_telemetry_device.sh (Option C) so that even a benchmark run that
never reaches Python's teardown() (e.g. host process killed) is protected by
the next run's start_telemetry_device.sh invocation cleaning up first.

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import time
from pathlib import Path
from typing import Any

from src.utils.logger import phase_logger


def push_telemetry_scripts(adb_manager: Any) -> None:
    """
    Pushes start_telemetry_device.sh / stop_telemetry_device.sh to the device
    and marks them executable, without starting collection. Useful for
    benchmarks (e.g. lat_mem_rd) that push the scripts once in setup() but
    start/stop telemetry multiple times (once per iteration) during run().
    """
    script_dir = Path("aibench/src/utils/telemetry")
    if not script_dir.exists():
        script_dir = Path("src/utils/telemetry")  # Fallback when cwd is already aibench/

    adb_manager.push_file(str(script_dir / "start_telemetry_device.sh"), "/root/start_telemetry_device.sh")
    adb_manager.push_file(str(script_dir / "stop_telemetry_device.sh"), "/root/stop_telemetry_device.sh")
    adb_manager.execute_shell_command("chmod +x /root/start_telemetry_device.sh /root/stop_telemetry_device.sh")


def setup_telemetry(adb_manager: Any, timestamp_tag: str = "") -> str:
    """
    Pushes the telemetry scripts to the device, makes them executable, and
    starts background telemetry collection (top/vmstat/dmesg/thermal/cpufreq).

    start_telemetry_device.sh internally cleans up any orphaned telemetry
    processes/files from a previous, potentially forcefully-interrupted run
    before starting fresh collection.

    If `timestamp_tag` is provided, it is used verbatim as the telemetry
    run's timestamp/tag (useful for per-iteration telemetry runs that need
    a unique, caller-controlled tag, e.g. "<timestamp>_iter3"). Otherwise a
    fresh timestamp is generated automatically.

    Returns the telemetry_timestamp string that must be passed to
    teardown_telemetry() later to stop this specific run's telemetry.
    """
    phase_logger.info("Setting up telemetry on device...")

    push_telemetry_scripts(adb_manager)

    telemetry_timestamp = timestamp_tag or time.strftime("%Y-%m-%d_%H-%M-%S")
    phase_logger.info("Starting background telemetry on device...")
    adb_manager.execute_shell_command(
        f"sh /root/start_telemetry_device.sh {telemetry_timestamp}", timeout_override=30.0
    )

    return telemetry_timestamp


def start_telemetry_only(adb_manager: Any, timestamp_tag: str) -> str:
    """
    Starts telemetry collection using an already-pushed script and a
    caller-supplied timestamp tag, without re-pushing/chmod-ing the scripts.
    Intended for benchmarks that call push_telemetry_scripts() once in
    setup() and then start/stop telemetry multiple times (per iteration)
    during run().
    """
    phase_logger.info(f"Starting background telemetry on device (tag={timestamp_tag})...")
    adb_manager.execute_shell_command(
        f"sh /root/start_telemetry_device.sh {timestamp_tag}", timeout_override=30.0
    )
    return timestamp_tag


def teardown_telemetry(adb_manager: Any, run_dir: Path, telemetry_timestamp: str) -> None:
    """
    Stops telemetry collection for the given run and pulls the resulting
    log/csv files into <run_dir>/logs on the host for later analysis.

    Any failure here is logged as a warning only (non-fatal) per project
    convention, so a telemetry hiccup never fails the overall benchmark run.
    """
    phase_logger.info("Stopping telemetry on device...")

    if not telemetry_timestamp:
        phase_logger.warning("No telemetry_timestamp recorded; skipping telemetry teardown.")
        return

    try:
        adb_manager.execute_shell_command(
            f"sh /root/stop_telemetry_device.sh {telemetry_timestamp}", timeout_override=30.0
        )

        logs_dir = Path(run_dir) / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        telemetry_files = [
            f"/root/top_metrics_{telemetry_timestamp}.log",
            f"/root/vmstat_metrics_{telemetry_timestamp}.log",
            f"/root/dmesg_metrics_{telemetry_timestamp}.log",
            f"/root/cpufreq_metrics_{telemetry_timestamp}.log",
            f"/root/thermal_metrics_{telemetry_timestamp}.csv",
            # ftrace is optional telemetry (see start_telemetry_device.sh) --
            # this file may not exist on devices where debugfs/tracing isn't
            # available. The size-check below already skips missing files
            # gracefully, so no special-casing is needed here.
            f"/root/ftrace_metrics_{telemetry_timestamp}.log",
        ]
        for tf in telemetry_files:
            local_name = Path(tf).name
            size_output = adb_manager.execute_shell_command(f"stat -c %s {tf} 2>/dev/null || echo 0").strip()
            if size_output and size_output.isdigit() and int(size_output) > 0:
                adb_manager.pull_file(tf, str(logs_dir / local_name))

        # Clean up the pulled log/csv files on the device now that they're safely on the host.
        # (.pid files were already removed by stop_telemetry_device.sh itself.)
        adb_manager.execute_shell_command(
            f"rm -f /root/*_{telemetry_timestamp}.log /root/*_{telemetry_timestamp}.csv"
        )
    except Exception as e:
        phase_logger.warning(f"Failed during telemetry cleanup/pull: {e}")
#!/usr/bin/env python3
"""
telemetry_parser.py - Parse system telemetry logs for performance anomalies.

Parses: cpufreq, dmesg, thermal (existing), plus vmstat, top, and ftrace
(new, added for the regression-detection-and-rca skill).

All numeric thresholds are configurable via the optional `thresholds` dict
passed to parse_anomalies()/__init__ (see
aibench/.claude/skills/regression-detection-and-rca/scripts/telemetry_thresholds.py
for how these are resolved from config/benchmarks.yaml's
`telemetry_thresholds` section). If no thresholds are supplied, conservative
hardcoded defaults are used so this module remains fully backward compatible
with existing callers (e.g. main.py's render_dashboard()) that construct
TelemetryParser() with no arguments.

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

# Backward-compatible hardcoded defaults (used when no thresholds dict is
# supplied). These match the original hardcoded values that lived in this
# file/regression_detector.py before the telemetry_thresholds config section
# was introduced.
_DEFAULT_THRESHOLDS: Dict[str, Any] = {
    "thermal": {"cpu_high_temp_c": 85, "ddr_high_temp_c": 75, "cpu_throttle_temp_c": 95},
    "cpu_frequency": {"drop_threshold_percent": 20},
    "vmstat": {
        "context_switch_spike_per_sec": 50000,
        "swap_activity_spike_per_sec": 100000,
        "io_wait_spike_percent": 30,
        "free_memory_low_mb": 50,
    },
    "top": {"single_process_cpu_percent_high": 90, "rss_growth_leak_percent": 50},
    "ftrace": {"sched_wakeup_latency_us_high": 5000, "migration_count_high": 500},
    "memory": {"oom_kill_threshold": 1},
}


class TelemetryParser:
    def __init__(self, thresholds: Optional[Dict[str, Any]] = None):
        """
        Args:
            thresholds: Optional device-specific threshold dict (as returned
                by telemetry_thresholds.load_thresholds()). If omitted,
                falls back to _DEFAULT_THRESHOLDS for full backward
                compatibility with pre-existing call sites.
        """
        self.thresholds = thresholds or _DEFAULT_THRESHOLDS
        self.warnings: List[str] = []

    def _get_threshold(self, *path, default=None):
        node: Any = self.thresholds
        for key in path:
            if isinstance(node, dict) and key in node:
                node = node[key]
            else:
                return default
        return node

    def parse_anomalies(self, log_dir):
        """
        Extract anomalies from all telemetry logs found in log_dir.

        Returns: {
            "cpu_frequency_drops": [...],
            "thermal_throttles": [...],
            "thermal_high_temp": [...],
            "oom_kills": [...],
            "context_switch_spike": [...],
            "swap_activity_spike": [...],
            "io_wait_spike": [...],
            "memory_pressure": [...],
            "process_cpu_anomalies": [...],
            "process_memory_leak": [...],
            "zombie_processes": [...],
            "scheduler_latency_spikes": [...],
            "task_migration_high": [],
            "warnings": ["<file>_metrics_*.log not found -- <category> analysis skipped", ...]
        }
        """
        log_dir = Path(log_dir)
        self.warnings = []
        anomalies: Dict[str, List[Any]] = {
            "cpu_frequency_drops": [],
            "thermal_throttles": [],
            "oom_kills": [],
            "context_switch_spike": [],
            "swap_activity_spike": [],
            "io_wait_spike": [],
            "thermal_high_temp": [],
            "memory_pressure": [],
            "process_cpu_anomalies": [],
            "process_memory_leak": [],
            "zombie_processes": [],
            "scheduler_latency_spikes": [],
            "task_migration_high": [],
        }

        self._parse_cpufreq(log_dir, anomalies)
        self._parse_dmesg(log_dir, anomalies)
        self._parse_thermal(log_dir, anomalies)
        self._parse_vmstat(log_dir, anomalies)
        self._parse_top(log_dir, anomalies)
        self._parse_ftrace(log_dir, anomalies)

        anomalies["warnings"] = self.warnings
        return anomalies

    # ------------------------------------------------------------------
    # cpufreq
    # ------------------------------------------------------------------
    def _parse_cpufreq(self, log_dir: Path, anomalies: Dict[str, List[Any]]) -> None:
        cpufreq_logs = list(log_dir.glob("cpufreq_metrics_*.log")) or (
            [log_dir / "cpufreq_metrics.log"] if (log_dir / "cpufreq_metrics.log").exists() else []
        )
        if not cpufreq_logs:
            self.warnings.append("cpufreq_metrics_*.log not found -- CPU frequency drop analysis skipped")
            return

        drop_pct_threshold = self._get_threshold("cpu_frequency", "drop_threshold_percent", default=20)
        cpufreq_log = cpufreq_logs[0]
        # Track a separate baseline per core rather than one global baseline.
        # A single global baseline causes false positives on big.LITTLE
        # SoCs, where the LITTLE cluster's cores run at an inherently lower
        # frequency than the big/prime cluster's - comparing a LITTLE
        # core's frequency against a big-cluster baseline (or vice versa)
        # looks like a frequency drop even when nothing throttled.
        baseline_freq_by_core: Dict[str, int] = {}
        current_time = "Unknown"
        with open(cpufreq_log, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line == "---":
                    continue

                if re.match(r"^\d{4}-\d{2}-\d{2}", line):
                    current_time = line
                    continue

                if line.startswith("cpu"):
                    parts = line.split(":")
                    if len(parts) >= 2:
                        core = parts[0].strip()
                        freq_str = parts[1].strip().split()[0]
                        if freq_str.isdigit():
                            freq = int(freq_str)

                            baseline_freq = baseline_freq_by_core.get(core)
                            if baseline_freq is None:
                                baseline_freq_by_core[core] = freq
                                continue

                            if freq < baseline_freq * (1 - drop_pct_threshold / 100.0):
                                drop_percent = ((baseline_freq - freq) / baseline_freq) * 100
                                anomalies["cpu_frequency_drops"].append({
                                    "time": current_time,
                                    "core": core,
                                    "freq_khz": freq,
                                    "drop_percent": round(drop_percent, 1)
                                })

    # ------------------------------------------------------------------
    # dmesg
    # ------------------------------------------------------------------
    def _parse_dmesg(self, log_dir: Path, anomalies: Dict[str, List[Any]]) -> None:
        dmesg_logs = list(log_dir.glob("dmesg_metrics_*.log")) or (
            [log_dir / "dmesg_metrics.log"] if (log_dir / "dmesg_metrics.log").exists() else []
        )
        if not dmesg_logs:
            self.warnings.append("dmesg_metrics_*.log not found -- thermal-throttle/OOM-kill analysis skipped")
            return

        dmesg_log = dmesg_logs[0]
        with open(dmesg_log, "r") as f:
            for line in f:
                line = line.strip()
                if "throttle" in line.lower():
                    anomalies["thermal_throttles"].append({"event": line})
                if "oom-kill" in line.lower() or "out of memory" in line.lower():
                    anomalies["oom_kills"].append({"event": line})

    # ------------------------------------------------------------------
    # thermal (CSV)
    # ------------------------------------------------------------------
    def _parse_thermal(self, log_dir: Path, anomalies: Dict[str, List[Any]]) -> None:
        thermal_logs = list(log_dir.glob("thermal_metrics_*.csv"))
        if not thermal_logs:
            self.warnings.append("thermal_metrics_*.csv not found -- thermal-spike analysis skipped")
            return

        cpu_high = self._get_threshold("thermal", "cpu_high_temp_c", default=85.0)
        ddr_high = self._get_threshold("thermal", "ddr_high_temp_c", default=75.0)

        thermal_log = thermal_logs[0]
        cpu_spikes = 0
        ddr_spikes = 0

        with open(thermal_log, "r") as f:
            f.readline()  # header
            for line in f:
                line = line.strip()
                if not line:
                    continue

                parts = line.split(",")
                if len(parts) >= 4:
                    zone_type = parts[2]
                    temp_str = parts[3]

                    if temp_str.isdigit():
                        temp_c = int(temp_str) / 1000.0

                        if "cpu" in zone_type and temp_c > cpu_high:
                            cpu_spikes += 1
                            if cpu_spikes == 1:
                                anomalies["thermal_high_temp"].append({
                                    "event": "CPU Temperature Spike",
                                    "zone": zone_type,
                                    "temp_c": temp_c
                                })
                        elif "ddr" in zone_type and temp_c > ddr_high:
                            ddr_spikes += 1
                            if ddr_spikes == 1:
                                anomalies["thermal_high_temp"].append({
                                    "event": "DDR Temperature Spike",
                                    "zone": zone_type,
                                    "temp_c": temp_c
                                })

    # ------------------------------------------------------------------
    # vmstat -- context switches, swap activity, I/O wait, free memory
    # ------------------------------------------------------------------
    def _parse_vmstat(self, log_dir: Path, anomalies: Dict[str, List[Any]]) -> None:
        """
        Parses `vmstat 1` output. Standard procps vmstat column layout:
            r  b  swpd  free  buff  cache  si  so  bi  bo  in  cs  us  sy  id  wa  st
        (positions 0-indexed: free=3, in=10, cs=11, wa=15)

        The first two header lines are skipped. Any line that doesn't parse
        as the expected number of whitespace-separated integer/numeric
        columns is silently skipped (handles the vmstat 1 header being
        repeated in some busybox/toybox variants, or partial/corrupted
        lines from I/O truncation during pull).
        """
        vmstat_logs = list(log_dir.glob("vmstat_metrics_*.log")) or (
            [log_dir / "vmstat_metrics.log"] if (log_dir / "vmstat_metrics.log").exists() else []
        )
        if not vmstat_logs:
            self.warnings.append("vmstat_metrics_*.log not found -- context-switch/swap-activity/IO-wait/memory-pressure analysis skipped")
            return

        cs_threshold = self._get_threshold("vmstat", "context_switch_spike_per_sec", default=50000)
        swap_threshold = self._get_threshold("vmstat", "swap_activity_spike_per_sec", default=100000)
        wa_threshold = self._get_threshold("vmstat", "io_wait_spike_percent", default=30)
        free_low_threshold_kb = self._get_threshold("vmstat", "free_memory_low_mb", default=50) * 1024

        vmstat_log = vmstat_logs[0]
        sample_idx = 0
        with open(vmstat_log, "r") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                cols = stripped.split()
                # Skip header lines ("procs -----...", "r  b  swpd free ...")
                if not cols or not (cols[0].lstrip("-").isdigit() or cols[0] == "0"):
                    continue
                if len(cols) < 16:
                    continue

                try:
                    free_kb = int(cols[3])
                    swap_in = int(cols[6])
                    swap_out = int(cols[7])
                    cs = int(cols[11])
                    wa = int(cols[15])
                except (ValueError, IndexError):
                    continue

                sample_idx += 1

                if cs > cs_threshold:
                    anomalies["context_switch_spike"].append({
                        "sample": sample_idx, "context_switches_per_sec": cs
                    })

                swap_activity = swap_in + swap_out
                if swap_activity > swap_threshold:
                    anomalies["swap_activity_spike"].append({
                        "sample": sample_idx, "swap_events_per_sec": swap_activity
                    })

                if wa > wa_threshold:
                    anomalies["io_wait_spike"].append({
                        "sample": sample_idx, "io_wait_percent": wa
                    })

                if free_kb < free_low_threshold_kb:
                    anomalies["memory_pressure"].append({
                        "sample": sample_idx, "free_kb": free_kb
                    })

    # ------------------------------------------------------------------
    # top -- per-process CPU%, RSS growth (leak proxy), zombie processes
    # ------------------------------------------------------------------
    def _parse_top(self, log_dir: Path, anomalies: Dict[str, List[Any]]) -> None:
        """
        Parses `top -b -d 1` batch-mode output. Batch mode repeats a full
        screen (summary + process table) once per interval. We track, per
        PID, the first and last observed RSS to compute leak-proxy growth,
        and flag any single-sample CPU% above threshold as a CPU anomaly.
        Zombie processes are detected via the 'Z' state column.
        """
        top_logs = list(log_dir.glob("top_metrics_*.log")) or (
            [log_dir / "top_metrics.log"] if (log_dir / "top_metrics.log").exists() else []
        )
        if not top_logs:
            self.warnings.append("top_metrics_*.log not found -- per-process CPU/memory-leak/zombie analysis skipped")
            return

        cpu_high_threshold = self._get_threshold("top", "single_process_cpu_percent_high", default=90)
        rss_growth_threshold = self._get_threshold("top", "rss_growth_leak_percent", default=50)

        top_log = top_logs[0]

        # PID -> {"cmd": str, "first_rss_kb": int, "last_rss_kb": int}
        proc_rss_track: Dict[str, Dict[str, Any]] = {}
        cpu_anomaly_seen = set()
        zombie_seen = set()

        # Typical busybox/procps top -b process line:
        #   PID USER  PR  NI  VIRT  RES  SHR S  %CPU %MEM  TIME+ COMMAND
        # RES may have a K/M/G suffix (busybox) or be plain KB (procps).
        proc_line_re = re.compile(
            r"^\s*(?P<pid>\d+)\s+\S+\s+\S+\s+\S+\s+\S+\s+(?P<res>\S+)\s+\S+\s+(?P<state>[A-Za-z])\s+"
            r"(?P<cpu>[\d.]+)\s+(?P<mem>[\d.]+)\s+\S+\s+(?P<cmd>.+)$"
        )

        def parse_res_to_kb(res_str: str) -> Optional[int]:
            res_str = res_str.strip()
            try:
                if res_str[-1] in ("k", "K"):
                    return int(float(res_str[:-1]))
                if res_str[-1] in ("m", "M"):
                    return int(float(res_str[:-1]) * 1024)
                if res_str[-1] in ("g", "G"):
                    return int(float(res_str[:-1]) * 1024 * 1024)
                return int(float(res_str))
            except (ValueError, IndexError):
                return None

        with open(top_log, "r", errors="ignore") as f:
            for line in f:
                stripped = line.rstrip("\n")
                match = proc_line_re.match(stripped)
                if not match:
                    continue

                pid = match.group("pid")
                state = match.group("state")
                try:
                    cpu_pct = float(match.group("cpu"))
                except ValueError:
                    continue
                res_kb = parse_res_to_kb(match.group("res"))
                cmd = match.group("cmd").strip()

                if state.upper() == "Z" and pid not in zombie_seen:
                    zombie_seen.add(pid)
                    anomalies["zombie_processes"].append({"pid": pid, "command": cmd})

                if cpu_pct > cpu_high_threshold and pid not in cpu_anomaly_seen:
                    cpu_anomaly_seen.add(pid)
                    anomalies["process_cpu_anomalies"].append({
                        "pid": pid, "command": cmd, "cpu_percent": cpu_pct
                    })

                if res_kb is not None:
                    entry = proc_rss_track.setdefault(pid, {"cmd": cmd, "first_rss_kb": res_kb, "last_rss_kb": res_kb})
                    entry["last_rss_kb"] = res_kb

        for pid, entry in proc_rss_track.items():
            first_kb = entry["first_rss_kb"]
            last_kb = entry["last_rss_kb"]
            if first_kb > 0:
                growth_pct = ((last_kb - first_kb) / first_kb) * 100.0
                if growth_pct > rss_growth_threshold:
                    anomalies["process_memory_leak"].append({
                        "pid": pid,
                        "command": entry["cmd"],
                        "first_rss_kb": first_kb,
                        "last_rss_kb": last_kb,
                        "growth_percent": round(growth_pct, 1)
                    })

    # ------------------------------------------------------------------
    # ftrace -- scheduler wake-up latency, preemption/migration events
    # ------------------------------------------------------------------
    def _parse_ftrace(self, log_dir: Path, anomalies: Dict[str, List[Any]]) -> None:
        """
        Parses the raw ftrace ring-buffer dump (nop tracer; sched_wakeup,
        sched_switch, sched_migrate_task events only -- see
        start_telemetry_device.sh). ftrace is OPTIONAL telemetry: if the
        file is missing (unsupported/locked-down device), this is recorded
        as a warning, not a failure.

        Standard ftrace text-format event line looks like:
          <task>-<pid> [<cpu>] <flags> <timestamp>: sched_wakeup: comm=<c> pid=<p> ...
          <task>-<pid> [<cpu>] <flags> <timestamp>: sched_switch: prev_comm=<c> ... next_pid=<p> ...
          <task>-<pid> [<cpu>] <flags> <timestamp>: sched_migrate_task: comm=<c> pid=<p> orig_cpu=<o> dest_cpu=<d>

        We compute wake-up latency as the delta between a sched_wakeup for
        pid P and the next sched_switch that schedules pid P in (next_pid=P).
        """
        ftrace_logs = list(log_dir.glob("ftrace_metrics_*.log")) or (
            [log_dir / "ftrace_metrics.log"] if (log_dir / "ftrace_metrics.log").exists() else []
        )
        if not ftrace_logs:
            self.warnings.append(
                "ftrace_metrics_*.log not found -- scheduler-latency/preemption/migration analysis skipped "
                "(ftrace may be unavailable on this device/build)"
            )
            return

        latency_threshold_us = self._get_threshold("ftrace", "sched_wakeup_latency_us_high", default=5000)
        migration_high_threshold = self._get_threshold("ftrace", "migration_count_high", default=500)

        ftrace_log = ftrace_logs[0]

        event_re = re.compile(
            r"^\s*\S+-(?P<pid>\d+)\s+\[\d+\].*?\s(?P<timestamp>\d+\.\d+):\s+(?P<event>\S+):\s*(?P<rest>.*)$"
        )
        wakeup_pid_re = re.compile(r"\bpid=(\d+)\b")
        switch_next_pid_re = re.compile(r"\bnext_pid=(\d+)\b")

        pending_wakeups: Dict[str, float] = {}  # pid -> wakeup timestamp
        migration_count = 0
        latency_samples: List[float] = []

        with open(ftrace_log, "r", errors="ignore") as f:
            for line in f:
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                match = event_re.match(stripped)
                if not match:
                    continue

                event = match.group("event")
                ts = float(match.group("timestamp"))
                rest = match.group("rest")

                if event == "sched_wakeup":
                    pid_match = wakeup_pid_re.search(rest)
                    if pid_match:
                        pending_wakeups[pid_match.group(1)] = ts

                elif event == "sched_switch":
                    pid_match = switch_next_pid_re.search(rest)
                    if pid_match:
                        next_pid = pid_match.group(1)
                        if next_pid in pending_wakeups:
                            latency_s = ts - pending_wakeups.pop(next_pid)
                            latency_us = latency_s * 1_000_000.0
                            if latency_us >= 0:
                                latency_samples.append(latency_us)
                                if latency_us > latency_threshold_us:
                                    anomalies["scheduler_latency_spikes"].append({
                                        "pid": next_pid,
                                        "wakeup_to_switch_latency_us": round(latency_us, 1)
                                    })

                elif event == "sched_migrate_task":
                    migration_count += 1

        if migration_count > migration_high_threshold:
            anomalies["task_migration_high"].append({
                "migration_count": migration_count,
                "threshold": migration_high_threshold
            })


if __name__ == "__main__":
    # Test script locally if logs exist
    import sys
    if len(sys.argv) > 1:
        parser = TelemetryParser()
        result = parser.parse_anomalies(sys.argv[1])
        print(json.dumps(result, indent=2))
    else:
        print("Usage: python telemetry_parser.py <log_dir>")
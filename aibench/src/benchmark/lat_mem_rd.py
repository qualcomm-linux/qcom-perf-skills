"""
lat_mem_rd.py - lat_mem_rd memory-latency benchmark engine.

Executes lmbench's lat_mem_rd tool over a sweep of increasing working-set
sizes for a fixed stride, detects the latency "plateau" at large working
sets (memory-bound region), and aggregates a per-iteration plateau
latency. Repeats for N iterations and reports overall plateau latency plus
iteration-to-iteration repeatability spread.

Command reference (per workload size):
    lat_mem_rd -t -N 7 <size> <stride>

Sample raw output:
    stride=64
    0.00049 1.697
    ...
    256.00000 141.742

Plateau detection algorithm (see aibench/documentation for full spec):
    1. Take the last 7 (workload, latency) points from the LARGEST
       workload-size command's output (the 256M run naturally has the
       widest coverage and contains the largest points already).
    2. Search from the tail backwards for the longest run of trailing
       points that satisfies:
         - at least `min_points` (default 4) points,
         - total spread <= `max_spread_pct` (default 3%),
         - max adjacent-point change <= `max_adjacent_change_pct` (default 2%),
         - no sustained upward trend.
    3. Average latency of that run = plateau latency for the iteration.

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import re
import time
import statistics
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.utils.logger import phase_logger as benchmark_logger
from src.reporting.outlier_registry import OutlierDetectorRegistry
from src.utils.telemetry_helpers import push_telemetry_scripts, start_telemetry_only, teardown_telemetry

_LOG_PREFIX = "[lat_mem_rd]"


@dataclass
class LatMemRdIterationResult:
    """Data class for a single lat_mem_rd iteration's plateau analysis."""
    iteration: int
    plateau_latency_ns: float
    plateau_points_count: int
    plateau_spread_pct: float
    plateau_valid: bool
    reason: str


class LatMemRd:
    """
    lat_mem_rd benchmark implementation.

    Follows the same lifecycle pattern (setup/run/teardown via
    execute_lifecycle) used by other benchmarks in this harness, including
    per-iteration device telemetry start/stop/pull and raw-output capture
    to the run directory.
    """

    def __init__(self, name: str, config: Dict[str, Any], run_dir: Path):
        self.name = name
        self.config = config
        self.run_dir = Path(run_dir)

        self.command_base = self.config.get("command", "/usr/bin/lat_mem_rd")
        self.iterations = self.config.get("iterations", 3)
        self.common_params: Dict[str, Any] = self.config.get("common_params", {"-t": "", "-N": 7})
        self.stride = self.config.get("stride", 64)
        self.workload_sizes: List[str] = self.config.get(
            "workload_sizes", ["64M", "96M", "128M", "192M", "256M"]
        )
        self.inter_command_delay = self.config.get("inter_command_delay", 5)
        self.inter_iteration_delay = self.config.get("inter_iteration_delay", 5)
        self.retry_attempts = max(1, int(self.config.get("retry_attempts", 3)))
        self.plateau_thresholds = self.config.get(
            "plateau_thresholds",
            {"min_points": 4, "max_spread_pct": 3.0, "max_adjacent_change_pct": 2.0},
        )
        self.tests_to_run = self.config.get("tests", ["lat_mem_rd_default"])

        self.telemetry_timestamps: List[str] = []  # one per iteration

    # ------------------------------------------------------------------
    # Command building
    # ------------------------------------------------------------------

    def _build_command(self, workload_size: str) -> str:
        """
        Build the CLI string for a single workload-size invocation:
            lat_mem_rd -t -N 7 <size> <stride>
        """
        cmd_parts = [self.command_base]
        for key, value in self.common_params.items():
            # NOTE: The fallback YAML parser (used when PyYAML is unavailable)
            # converts an empty-string value (e.g. "-t: \"\"") into an empty
            # dict {} instead of "". Guard against both representations so
            # flag-only CLI args (no value) are built correctly either way.
            if value == "" or value is None or (isinstance(value, dict) and not value):
                cmd_parts.append(str(key))
            else:
                cmd_parts.extend([str(key), str(value)])
        cmd_parts.append(str(workload_size))
        cmd_parts.append(str(self.stride))
        return " ".join(cmd_parts)

    # ------------------------------------------------------------------
    # Output parsing
    # ------------------------------------------------------------------

    def _parse_output(self, output: str) -> List[Tuple[float, float]]:
        """
        Parse raw lat_mem_rd output into a list of (workload_mb, latency_ns)
        tuples, preserving order. Skips the 'stride=NN' header line.
        """
        points: List[Tuple[float, float]] = []
        skipped_lines: List[str] = []
        for line in output.splitlines():
            line = line.strip()
            if not line or line.lower().startswith("stride"):
                continue
            parts = line.split()
            if len(parts) != 2:
                skipped_lines.append(line)
                continue
            try:
                workload = float(parts[0])
                latency = float(parts[1])
            except ValueError:
                skipped_lines.append(line)
                continue
            points.append((workload, latency))

        # Diagnostic aid: if the output was non-empty but we extracted zero
        # points, log the unparsed lines so the actual format mismatch (or
        # error message from the device) is visible in the console/log
        # output, rather than silently failing with no explanation.
        if not points and output.strip():
            sample = skipped_lines[:5] if skipped_lines else output.strip().splitlines()[:5]
            benchmark_logger.warning(
                f"{_LOG_PREFIX} _parse_output found 0 valid (workload, latency) points in "
                f"non-empty output. Sample unparsed line(s): {sample}"
            )

        return points

    # ------------------------------------------------------------------
    # Plateau detection
    # ------------------------------------------------------------------

    def detect_plateau(self, points: List[Tuple[float, float]]) -> Dict[str, Any]:
        """
        Implements the plateau-detection algorithm on the tail of `points`
        (assumed sorted ascending by workload size).

        A plateau is valid when, for some trailing window of >= min_points:
            - total spread = (max - min) / average * 100 <= max_spread_pct
            - max adjacent-point pct change <= max_adjacent_change_pct
            - no sustained upward trend across the window
        The search starts from the largest possible trailing window (last 7
        points, if available) and shrinks until a valid window is found or
        the minimum size is reached.
        """
        min_points = max(2, int(self.plateau_thresholds.get("min_points", 4)))
        max_spread_pct = float(self.plateau_thresholds.get("max_spread_pct", 3.0))
        max_adjacent_pct = float(self.plateau_thresholds.get("max_adjacent_change_pct", 2.0))

        default_result = {
            "plateau_latency_ns": 0.0,
            "points_count": 0,
            "spread_pct": None,
            "valid": False,
            "reason": "Insufficient data points for plateau analysis.",
        }

        if not points:
            return default_result

        # Only consider the last 7 points as candidate plateau data per spec.
        tail = points[-7:] if len(points) >= 7 else points[:]

        n = len(tail)
        if n < min_points:
            default_result["reason"] = (
                f"Only {n} tail points available; at least {min_points} are required."
            )
            return default_result

        # Try progressively smaller trailing windows, starting from the
        # largest (all of `tail`), down to `min_points`.
        for window_size in range(n, min_points - 1, -1):
            window = tail[-window_size:]
            latencies = [lat for _, lat in window]

            avg_latency = sum(latencies) / len(latencies)
            if avg_latency <= 0:
                continue

            spread_pct = ((max(latencies) - min(latencies)) / avg_latency) * 100.0

            adjacent_changes = []
            for i in range(1, len(latencies)):
                prev_lat = latencies[i - 1]
                curr_lat = latencies[i]
                denom = (curr_lat + prev_lat) / 2.0
                if denom <= 0:
                    adjacent_changes.append(0.0)
                    continue
                adjacent_changes.append(abs(curr_lat - prev_lat) / denom * 100.0)

            max_adjacent = max(adjacent_changes) if adjacent_changes else 0.0

            # "No sustained upward trend" is already effectively enforced by
            # the spread_pct and max_adjacent_pct constraints above: a real
            # sustained/significant upward trend would violate one of them.
            # NOTE: A plateau region can still have small monotonically
            # increasing latencies point-to-point (as in the reference
            # example: 139.351 -> 140.490 -> 141.227 -> 141.703 -> 141.742)
            # and must still be considered valid, provided the overall
            # spread and per-step changes stay within threshold.

            if spread_pct <= max_spread_pct and max_adjacent <= max_adjacent_pct:
                return {
                    "plateau_latency_ns": round(avg_latency, 3),
                    "points_count": len(window),
                    "spread_pct": round(spread_pct, 3),
                    "max_adjacent_change_pct": round(max_adjacent, 3),
                    "valid": True,
                    "reason": (
                        f"Valid plateau found using last {len(window)} points "
                        f"(spread={spread_pct:.2f}%, max_adjacent={max_adjacent:.2f}%)."
                    ),
                }

        # No valid window found; fall back to reporting the full-tail average
        # as a best-effort estimate, but mark plateau as invalid.
        fallback_latencies = [lat for _, lat in tail]
        fallback_avg = sum(fallback_latencies) / len(fallback_latencies)
        fallback_spread = (
            (max(fallback_latencies) - min(fallback_latencies)) / fallback_avg * 100.0
            if fallback_avg > 0 else None
        )

        return {
            "plateau_latency_ns": round(fallback_avg, 3),
            "points_count": len(tail),
            "spread_pct": round(fallback_spread, 3) if fallback_spread is not None else None,
            "valid": False,
            "reason": (
                "No trailing window satisfied plateau validity thresholds "
                f"(min_points={min_points}, max_spread_pct={max_spread_pct}, "
                f"max_adjacent_change_pct={max_adjacent_pct}). Reporting best-effort "
                "average of the full tail window as a fallback estimate."
            ),
        }

    # ------------------------------------------------------------------
    # Telemetry helpers (per-iteration start/stop/pull)
    # ------------------------------------------------------------------

    def _push_telemetry_scripts(self, adb_manager) -> None:
        push_telemetry_scripts(adb_manager)

    def _start_iteration_telemetry(self, adb_manager, iteration: int) -> str:
        if not self.config.get("collect_telemetry", False):
            return ""
        timestamp = time.strftime("%Y-%m-%d_%H-%M-%S") + f"_iter{iteration}"
        benchmark_logger.info(f"{_LOG_PREFIX} Starting telemetry for iteration {iteration} (tag={timestamp})...")
        return start_telemetry_only(adb_manager, timestamp)

    def _stop_and_pull_iteration_telemetry(self, adb_manager, timestamp: str) -> None:
        teardown_telemetry(adb_manager, self.run_dir, timestamp)

    # ------------------------------------------------------------------
    # Lifecycle: setup / run / teardown
    # ------------------------------------------------------------------

    def setup(self, serial_executor, adb_manager) -> None:
        benchmark_logger.info(f"{_LOG_PREFIX} Setting up lat_mem_rd benchmark on device...")
        out = serial_executor.execute_command(f"ls {self.command_base}")
        if "No such file or directory" in out:
            benchmark_logger.error(f"{_LOG_PREFIX} Binary {self.command_base} not found on target.")
        self._push_telemetry_scripts(adb_manager)

    def _run_single_workload(self, serial_executor, workload_size: str) -> Tuple[List[Tuple[float, float]], str]:
        """
        Executes a single workload-size command with retry-on-failure logic.
        Returns a tuple of (parsed_points, last_raw_output).

        IMPORTANT: The raw output from the LAST attempt is always returned,
        even if parsing failed on every attempt (parsed_points will simply
        be an empty list in that case). Previously this method discarded
        the actual device output and returned "" on total failure, which
        meant the real output was never written to the per-run log file -
        making it impossible to diagnose *why* parsing failed (e.g. unit
        not installed, unexpected output format, stderr-only output, etc).
        This mirrors the pattern used by sysbench.py, which unconditionally
        persists raw output to disk regardless of parse success so failures
        can always be triaged after the fact.

        NOTE on timeout_override=0: This is intentional and matches the
        pattern used by every other working benchmark in this harness
        (hackbench, sysbench, ramspeed, tiobench, osbench, glmark2,
        coremark, coremark_pro all use timeout_override=0).

        ssh_manager.py treats timeout_override=0 as "no timeout" (passes
        timeout=None to Paramiko's exec_command), which means Paramiko
        will block indefinitely waiting for socket activity. Passing any
        finite numeric value (e.g. 300) sets a Paramiko *socket* timeout -
        NOT a command-execution timeout. If no data arrives on the SSH
        socket within that window (which can legitimately happen for a
        ~30-60s long-running command like lat_mem_rd depending on buffering
        behavior), the channel can end up in a state where stdout.read()
        returns 0 bytes even though the command executed successfully on
        the device. This was confirmed on-target: lat_mem_rd ran to
        completion in ~30s but returned 0 bytes when timeout_override was
        set to a finite value (300s), while all other benchmarks - which
        use timeout_override=0 - work correctly. Reverting to 0 here fixes
        the empty-output issue and aligns with the rest of the codebase.

        NOTE on prefer_stderr=True: On-target testing confirmed that this
        specific lmbench build of lat_mem_rd writes its data output (the
        "stride=NN" / workload-latency lines) to stderr rather than stdout.
        SshManager.execute_command() supports an explicit, opt-in
        `prefer_stderr` flag for exactly this situation: when set, stderr
        is treated as the primary output stream (falling back to stdout
        only if stderr is empty). This is scoped to lat_mem_rd only - the
        flag defaults to False for every other benchmark/caller and does
        not alter their behavior in any way. SerialCommandExecutor accepts
        the same parameter as a no-op (a serial connection cannot separate
        stdout/stderr), so this call remains valid under either transport.
        """
        cmd = self._build_command(workload_size)

        last_output = ""

        for attempt in range(1, self.retry_attempts + 1):
            benchmark_logger.info(f"{_LOG_PREFIX} Executing: {cmd}")
            try:
                output = serial_executor.execute_command(
                    cmd, timeout_override=0, prefer_stderr=True
                )
            except Exception as e:
                benchmark_logger.warning(f"{_LOG_PREFIX} Command execution failed: {e}")
                continue

            last_output = output or ""
            output_len = len(last_output)
            benchmark_logger.info(
                f"{_LOG_PREFIX} Received {output_len} bytes of output for workload={workload_size}."
            )
            if output_len == 0:
                benchmark_logger.warning(
                    f"{_LOG_PREFIX} Command returned empty output for workload={workload_size} "
                    f"(attempt {attempt}/{self.retry_attempts}). This usually indicates the command "
                    f"produced no output on either stdout or stderr (e.g. binary missing/failed)."
                )

            points = self._parse_output(last_output)
            if points:
                return points, last_output

            benchmark_logger.warning(
                f"{_LOG_PREFIX} Failed to parse valid output for workload={workload_size} "
                f"(attempt {attempt}/{self.retry_attempts}). Retrying..."
            )

        benchmark_logger.error(
            f"{_LOG_PREFIX} All {self.retry_attempts} attempts failed for workload={workload_size}. "
            f"Persisting last raw output ({len(last_output)} bytes) for diagnosis."
        )
        # Return the real last-seen output (possibly non-empty even though
        # parsing failed) instead of discarding it as "".
        return [], last_output

    def run(self, serial_executor, adb_manager) -> Dict[str, Any]:
        benchmark_logger.info(f"{_LOG_PREFIX} Executing lat_mem_rd...")

        results: Dict[str, Any] = {
            "metadata": {"benchmark_name": self.name},
            "tests": {},
        }

        logs_dir = self.run_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        for test_id in self.tests_to_run:
            iteration_entries: List[Dict[str, Any]] = []
            per_iteration_plateaus: List[float] = []

            for iteration in range(1, self.iterations + 1):
                benchmark_logger.info(f"{_LOG_PREFIX} --- Iteration {iteration}/{self.iterations} ---")

                # Per-iteration telemetry lifecycle
                telemetry_tag = self._start_iteration_telemetry(adb_manager, iteration)

                largest_points: List[Tuple[float, float]] = []

                for size_idx, workload_size in enumerate(self.workload_sizes):
                    points, raw_output = self._run_single_workload(serial_executor, workload_size)

                    # Persist raw output to run directory
                    if raw_output:
                        out_file = logs_dir / f"lat_mem_rd_iter{iteration}_{workload_size}.log"
                        with open(out_file, "w", encoding="utf-8") as f:
                            f.write(raw_output)

                    if points:
                        # Use the widest-coverage run (typically the last/largest
                        # workload size) for plateau extraction, since it contains
                        # the tail data points needed for detection.
                        largest_points = points

                    if size_idx < len(self.workload_sizes) - 1:
                        time.sleep(self.inter_command_delay)

                plateau_info = self.detect_plateau(largest_points)

                iteration_result = LatMemRdIterationResult(
                    iteration=iteration,
                    plateau_latency_ns=plateau_info["plateau_latency_ns"],
                    plateau_points_count=plateau_info["points_count"],
                    plateau_spread_pct=plateau_info.get("spread_pct") or 0.0,
                    plateau_valid=plateau_info["valid"],
                    reason=plateau_info["reason"],
                )

                benchmark_logger.info(
                    f"{_LOG_PREFIX} Iteration {iteration} plateau latency: "
                    f"{iteration_result.plateau_latency_ns:.3f} ns "
                    f"(valid={iteration_result.plateau_valid}, "
                    f"points={iteration_result.plateau_points_count})"
                )

                it_dict = asdict(iteration_result)
                it_dict["is_outlier"] = False
                iteration_entries.append(it_dict)

                if plateau_info["plateau_latency_ns"] > 0:
                    per_iteration_plateaus.append(plateau_info["plateau_latency_ns"])

                # Stop/pull telemetry for this iteration
                self._stop_and_pull_iteration_telemetry(adb_manager, telemetry_tag)

                if iteration < self.iterations:
                    benchmark_logger.info(f"{_LOG_PREFIX} Cooling down for {self.inter_iteration_delay}s...")
                    time.sleep(self.inter_iteration_delay)

            # --- Outlier detection across per-iteration plateau latencies ---
            clean_iterations = iteration_entries
            outlier_discarded_count = 0

            if len(iteration_entries) >= 2:
                try:
                    detector = OutlierDetectorRegistry.get("lat_mem_rd")
                    out = detector.run_detection(
                        iteration_entries,
                        n_iterations=len(iteration_entries),
                        benchmark_variant=test_id,
                        run_id="lat_mem_rd",
                    )
                    clean_iterations = out.get("clean_iterations", iteration_entries)
                    discarded_indices = out.get("discarded_indices", [])
                    outlier_discarded_count = len(discarded_indices)
                    for idx in discarded_indices:
                        if idx < len(iteration_entries):
                            iteration_entries[idx]["is_outlier"] = True
                except Exception as e:
                    benchmark_logger.warning(f"{_LOG_PREFIX} Outlier detection failed: {e}")

            clean_plateaus = [
                it["plateau_latency_ns"] for it in clean_iterations
                if it.get("plateau_latency_ns", 0) > 0
            ]

            overall_plateau = statistics.mean(clean_plateaus) if clean_plateaus else 0.0
            iter_to_iter_spread_pct = 0.0
            if clean_plateaus and overall_plateau > 0 and len(clean_plateaus) > 1:
                iter_to_iter_spread_pct = (
                    (max(clean_plateaus) - min(clean_plateaus)) / overall_plateau
                ) * 100.0

            results["tests"][test_id] = {
                "category": self.config.get("category", "Memory"),
                "iterations": iteration_entries,
                "clean_iterations_count": len(clean_iterations),
                "outlier_discarded_count": outlier_discarded_count,
                "per_iteration_plateau_ns": clean_plateaus,
                "overall_plateau_latency_ns": round(overall_plateau, 3),
                "iteration_to_iteration_spread_pct": round(iter_to_iter_spread_pct, 3),
                "unit": "ns",
            }

            benchmark_logger.info(
                f"{_LOG_PREFIX} Test '{test_id}': overall plateau latency = "
                f"{overall_plateau:.3f} ns, iteration-to-iteration spread = "
                f"{iter_to_iter_spread_pct:.2f}%"
            )

        return results

    def teardown(self, serial_executor, adb_manager) -> None:
        # Telemetry is stopped/pulled per-iteration inside run(); nothing
        # additional required here beyond logging completion.
        benchmark_logger.info(f"{_LOG_PREFIX} lat_mem_rd teardown complete (telemetry handled per-iteration).")

    # ------------------------------------------------------------------
    # Harness entrypoint
    # ------------------------------------------------------------------

    def execute_lifecycle(self, serial_executor, adb_manager: Any = None) -> Dict[str, Any]:
        """Main execution method called by harness."""
        self.setup(serial_executor, adb_manager)
        try:
            results = self.run(serial_executor, adb_manager)
        finally:
            self.teardown(serial_executor, adb_manager)
        return results


# REQUIRED: Export the benchmark class for auto-discovery
BENCHMARK_CLASS = LatMemRd
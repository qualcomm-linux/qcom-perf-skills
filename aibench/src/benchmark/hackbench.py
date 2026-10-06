"""
hackbench.py - Hackbench benchmark runner
Executes hackbench with configurable parameters to test scheduler IPC.

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import time
import re
from dataclasses import dataclass, asdict
from typing import Any, Dict, List
from pathlib import Path

from src.utils.logger import phase_logger as benchmark_logger
from src.utils.serial_executor import SerialCommandExecutor
from src.reporting.outlier_registry import OutlierDetectorRegistry
from src.utils.telemetry_helpers import setup_telemetry, teardown_telemetry

_LOG_PREFIX = "[hackbench]"

@dataclass
class HackbenchIterationResult:
    iteration: int
    test_name: str
    total_messages: int
    time_taken: float
    throughput: float  # messages per second

class Hackbench:
    """
    Executes the Hackbench benchmark suite over a serial connection.
    Parses output to extract IPC timing and calculates throughput.
    """
    
    def __init__(self, name: str, config: Dict[str, Any], run_dir: Path):
        self.name = name
        self.config = config
        self.run_dir = run_dir
        self.command_base = self.config.get("command", "/usr/bin/hackbench")
        self.iterations = self.config.get("iterations", 3)
        self.test_params = self.config.get("test_params", {})
        
        # Determine which tests to run
        # Based on requirement: if no parameters provided, run only sched_ipc_default
        configured_tests = self.config.get("tests", [])
        self.tests_to_run = configured_tests if configured_tests else ["sched_ipc_default"]
        self.telemetry_timestamp = ""

    def setup(self, serial_executor, adb_manager) -> None:
        benchmark_logger.info(f"{_LOG_PREFIX} Setting up Hackbench benchmark on device...")
        if self.config.get('collect_telemetry', False):
            self.telemetry_timestamp = setup_telemetry(adb_manager)

    def _build_command(self, test_name: str, params: Dict[str, Any]) -> str:
        """Constructs the hackbench command line from parameters."""
        cmd_parts = [self.command_base]
        
        for key, value in params.items():
            if key == "category":
                continue
                
            # Handle empty values (like empty strings or dicts from YAML parsing)
            # When -p: "" is parsed in YAML, it might be evaluated strangely depending on the parser.
            # We only want to append the flag for these empty-like values.
            if value == "" or value is None or (isinstance(value, dict) and not value):
                cmd_parts.append(key)
            else:
                cmd_parts.extend([key, str(value)])
                
        return " ".join(cmd_parts)

    def _calculate_total_messages(self, params: Dict[str, Any]) -> int:
        """
        Calculates total messages based on parameters:
        total_message = -g (groups) * -f (fds per group) * -l (loops)
        """
        try:
            g = int(params.get("-g", 0))
            f = int(params.get("-f", 0))
            l = int(params.get("-l", 0))
            return g * f * l
        except (ValueError, TypeError):
            benchmark_logger.error(f"{_LOG_PREFIX} Invalid parameters for message calculation: {params}")
            return 0

    def _parse_output(self, output: str, iteration: int, test_name: str, params: Dict[str, Any]) -> HackbenchIterationResult:
        """
        Parses the hackbench output.
        Expected format includes: Time: 6.787
        """
        time_taken = 0.0
        
        for line in output.split('\n'):
            line = line.strip()
            # Match "Time: 6.787"
            match = re.search(r'Time:\s*([\d.]+)', line)
            if match:
                time_taken = float(match.group(1))
                break
                
        if time_taken <= 0:
            benchmark_logger.error(f"{_LOG_PREFIX} Failed to parse valid time from output:\n{output}")
            time_taken = 0.0001  # Prevent division by zero
            
        total_messages = self._calculate_total_messages(params)
        throughput = total_messages / time_taken if time_taken > 0 else 0.0
        
        return HackbenchIterationResult(
            iteration=iteration,
            test_name=test_name,
            total_messages=total_messages,
            time_taken=time_taken,
            throughput=throughput
        )
        
    def generate_outlier_explanation(self, metrics_list, deviation_pct, method):
        """Generates a human-readable explanation for outlier detection."""
        primary_reason = f"Iteration discarded because throughput deviated by {deviation_pct:.1f}% from the expected normal range."
        
        method_explanation = {
            "median_pct": "detected by comparing against the median (middle value) of all iterations",
            "iqr": "detected using statistical range analysis",
            "mad_zscore": "detected using advanced statistical analysis"
        }
        
        return f"{primary_reason} This was {method_explanation.get(method, 'detected by statistical analysis')}."

    def execute_lifecycle(self, serial_executor: SerialCommandExecutor, adb_manager: Any = None) -> Dict[str, Any]:
        """
        Standard interface required by the harness.
        Returns the benchmark results dictionary.
        """
        self.serial = serial_executor
        self.setup(serial_executor, adb_manager)
        
        metadata = {
            "benchmark": self.name,
            "timestamp_utc": time.strftime("%Y-%m-%d %H:%M:%S"),
            "os_build_id": adb_manager.get_build_id() if adb_manager else "unknown",
            "os_pretty_name": getattr(adb_manager, "get_os_version", lambda: "Linux")() if adb_manager and hasattr(adb_manager, "get_os_version") else "Linux",
            "total_iterations_executed": self.iterations * len(self.tests_to_run),
            "iterations_run": 0,
            "warmup_iterations_discarded": 0,
            "outlier_iterations_discarded": 0
        }
        
        results = {
            "metadata": metadata,
            "tests": {}
        }
        
        try:
            self._run_all_tests(results)
        finally:
            self.teardown(serial_executor, adb_manager)
            
        return results

    def teardown(self, serial_executor, adb_manager) -> None:
        teardown_telemetry(adb_manager, self.run_dir, self.telemetry_timestamp)

    def _run_all_tests(self, results: Dict[str, Any]) -> None:
        tests = self.tests_to_run
        
        for idx, test_id in enumerate(tests):
            if test_id not in self.test_params:
                benchmark_logger.warning(f"{_LOG_PREFIX} Test {test_id} not found in configuration. Skipping.")
                continue
                
            params = self.test_params[test_id]
            cmd = self._build_command(test_id, params)
            
            benchmark_logger.info(f"{_LOG_PREFIX} Running {test_id}: {cmd}")
            
            raw_iterations = []
            total_runs = self.iterations
            
            for i in range(1, total_runs + 1):
                iter_label = f"{i}/{self.iterations}"
                benchmark_logger.info(f"{_LOG_PREFIX} Iteration {iter_label}")
                
                # Execute command
                output = self.serial.execute_command(cmd, timeout_override=0)
                
                # Parse result
                res = self._parse_output(output, i, test_id, params)
                benchmark_logger.info(f"{_LOG_PREFIX} Result: Time={res.time_taken:.3f}s, Throughput={res.throughput:,.2f} msgs/sec")
                
                # We need to map 'throughput' to 'cpu_events_per_sec' temporarily 
                # so the outlier_detector can process it like it does for sysbench
                it_dict = asdict(res)
                it_dict["cpu_events_per_sec"] = res.throughput
                it_dict["is_outlier"] = False
                    
                raw_iterations.append(it_dict)
                
                # Fixed 5-second cooldown gap between iterations to allow system to cool down
                if i < total_runs:
                    benchmark_logger.info(f"{_LOG_PREFIX} Cooling down for 5 seconds...")
                    time.sleep(5)
            
            if not raw_iterations:
                continue
                
            # Use all iterations for analysis (warm-up feature removed)
            analysis_iterations = raw_iterations
            
            # Apply outlier detection to analysis iterations only
            clean_iterations = analysis_iterations
            outlier_discarded_metrics = {}
            
            outlier_details = []
            if len(analysis_iterations) >= 3:
                try:
                    detector = OutlierDetectorRegistry.get("hackbench")
                    out = detector.run_detection(
                        analysis_iterations,
                        n_iterations=len(analysis_iterations),
                        min_iterations=2,
                        benchmark_variant="hackbench_ipc"
                    )
                    outlier_discarded_indices = out.get("discarded_indices", [])
                    outlier_discarded_count = len(outlier_discarded_indices)
                    clean_iterations = out.get("clean_iterations", raw_iterations)
                    outlier_discarded_metrics = out.get("discarded_metrics", {})
                    method = out.get("detection_method", "median_pct")
                    
                    if outlier_discarded_count > 0:
                        for raw_idx in outlier_discarded_indices:
                            if raw_idx < len(analysis_iterations):
                                # Mark as outlier in the original list
                                analysis_iterations[raw_idx]["is_outlier"] = True
                                val = analysis_iterations[raw_idx].get("cpu_events_per_sec", 0.0)
                                
                                # Estimate median from clean iterations
                                clean_vals = [it.get("cpu_events_per_sec", 0.0) for it in clean_iterations]
                                clean_vals.sort()
                                n = len(clean_vals)
                                median = clean_vals[n//2] if n % 2 != 0 else (clean_vals[n//2 - 1] + clean_vals[n//2]) / 2.0 if n > 0 else 0.0
                                
                                deviation_pct = abs(val - median) / median * 100.0 if median > 0 else 0.0
                                
                                metrics_list = {"cpu_events_per_sec": val}
                                explanation = self.generate_outlier_explanation(metrics_list, deviation_pct, method)
                                
                                outlier_details.append({
                                    "iteration_index": raw_idx + 1,
                                    "explanation": explanation,
                                    "detection_method": method,
                                    "flagged_metrics": ["cpu_events_per_sec"],
                                    "values": metrics_list
                                })
                                
                                benchmark_logger.warning(
                                    f"Outlier detected for {test_id}: {val:.2f} (dev: {deviation_pct:.1f}%). "
                                    f"Method: {method}",
                                    extra={
                                        "outlier_info": {
                                            "test": test_id,
                                            "discarded_metrics": metrics_list,
                                            "detection_method": method,
                                            "explanation": explanation
                                        }
                                    }
                                )
                except Exception as e:
                    benchmark_logger.warning(f"{_LOG_PREFIX} Outlier detection failed for {test_id}: {e}")
                    clean_iterations = raw_iterations
            
            # Format final results
            # The top-level 'throughput' array is used by the regression detector
            final_throughput = [r.get("cpu_events_per_sec") for r in clean_iterations]
            
            outliers_discarded = len(analysis_iterations) - len(clean_iterations)
            results["metadata"]["iterations_run"] += len(clean_iterations)
            results["metadata"]["outlier_iterations_discarded"] += outliers_discarded
            
            results["tests"][test_id] = {
                "category": params.get("category", "scheduler_ipc"),
                "iterations": raw_iterations,  # Pass all iterations so template can display them
                "clean_iterations_count": len(clean_iterations),
                "outlier_discarded_count": outliers_discarded,
                "outlier_details": outlier_details,
                "throughput": final_throughput
            }
            
            # Cooldown gap between different tests to prevent thermal skewing
            if idx < len(tests) - 1:
                benchmark_logger.info(f"{_LOG_PREFIX} Cooling down for 5 seconds between different test flavors...")
                time.sleep(5)

BENCHMARK_CLASS = Hackbench

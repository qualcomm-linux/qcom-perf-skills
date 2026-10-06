"""
geekbench.py - Geekbench 6 CPU benchmark engine
Executes Geekbench and parses Single-Core and Multi-Core results.

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import re
import time
from dataclasses import dataclass, asdict
from typing import Any, Dict, List
from pathlib import Path

from src.utils.logger import phase_logger as benchmark_logger
from src.utils.serial_executor import SerialCommandExecutor
from src.reporting.outlier_registry import OutlierDetectorRegistry
from src.utils.telemetry_helpers import setup_telemetry, teardown_telemetry
from src.utils.device_info_collector import collect_device_info_remote

_LOG_PREFIX = "[geekbench]"

@dataclass
class GeekbenchIterationResult:
    """Data class for a single Geekbench iteration"""
    iteration: int
    test_name: str
    single_core_score: float
    single_core_integer_score: float
    single_core_float_score: float
    multi_core_score: float
    multi_core_integer_score: float
    multi_core_float_score: float


class GeekbenchBenchmark:
    """Geekbench 6 CPU benchmark implementation"""
    
    def __init__(self, name: str, config: Dict[str, Any], run_dir: Path):
        self.name = name
        self.config = config
        self.run_dir = run_dir
        self.command_base = self.config.get("command", "/root/geekbench_aarch64")
        self.iterations = self.config.get("iterations", 3)
        self.test_params = self.config.get("test_params", {})
        self.tests_to_run = self.config.get("tests", ["geekbench_cpu"])
        self.telemetry_timestamp = ""
    
    def _build_command(self, test_name: str, params: Dict[str, Any]) -> str:
        """Build the command line for a test"""
        cmd_parts = [self.command_base]
        for key, value in params.items():
            if key == "category":
                continue
            if value == "" or value is None or (isinstance(value, dict) and not value):
                cmd_parts.append(key)
            else:
                cmd_parts.extend([key, str(value)])
        return " ".join(cmd_parts)
    
    def _parse_output(self, output: str, iteration: int, test_name: str) -> GeekbenchIterationResult:
        """
        Parse Geekbench output.
        Extract all 6 metrics from the raw output string.
        
        Expected output format:
        Single-Core
          ...
          Integer Score                 1171
          Floating Point Score          1044
        
        Multi-Core
          ...
          Integer Score                 5187
          Floating Point Score          5967
        
        Benchmark Summary
          Single-Core Score             1125
            Integer Score                 1171
            Floating Point Score          1044
          Multi-Core Score              5448
            Integer Score                 5187
            Floating Point Score          5967
        """
        single_core_score = 0.0
        single_core_integer_score = 0.0
        single_core_float_score = 0.0
        multi_core_score = 0.0
        multi_core_integer_score = 0.0
        multi_core_float_score = 0.0
        
        lines = output.split('\n')
        in_single_core_section = False
        in_multi_core_section = False
        in_summary_section = False
        summary_single_done = False
        
        for i, line in enumerate(lines):
            line = line.strip()
            
            # Detect sections
            if 'Benchmark Summary' in line:
                in_summary_section = True
                in_single_core_section = False
                in_multi_core_section = False
                continue
            elif line.startswith('Single-Core') and not in_summary_section:
                in_single_core_section = True
                in_multi_core_section = False
                continue
            elif line.startswith('Multi-Core') and not in_summary_section:
                in_single_core_section = False
                in_multi_core_section = True
                continue
            
            # Parse Summary section (most reliable)
            if in_summary_section:
                if 'Single-Core Score' in line:
                    match = re.search(r'Single-Core Score\s+(\d+)', line)
                    if match:
                        single_core_score = float(match.group(1))
                        summary_single_done = False
                elif 'Multi-Core Score' in line:
                    match = re.search(r'Multi-Core Score\s+(\d+)', line)
                    if match:
                        multi_core_score = float(match.group(1))
                        summary_single_done = True
                elif 'Integer Score' in line:
                    match = re.search(r'Integer Score\s+(\d+)', line)
                    if match:
                        if not summary_single_done:
                            single_core_integer_score = float(match.group(1))
                        else:
                            multi_core_integer_score = float(match.group(1))
                elif 'Floating Point Score' in line:
                    match = re.search(r'Floating Point Score\s+(\d+)', line)
                    if match:
                        if not summary_single_done:
                            single_core_float_score = float(match.group(1))
                        else:
                            multi_core_float_score = float(match.group(1))
        
        # Validate that we got all scores
        if single_core_score <= 0 or multi_core_score <= 0:
            benchmark_logger.error(f"{_LOG_PREFIX} Failed to parse valid scores from output")
            benchmark_logger.debug(f"{_LOG_PREFIX} Output sample:\n{output[:500]}")
            
        return GeekbenchIterationResult(
            iteration=iteration,
            test_name=test_name,
            single_core_score=single_core_score,
            single_core_integer_score=single_core_integer_score,
            single_core_float_score=single_core_float_score,
            multi_core_score=multi_core_score,
            multi_core_integer_score=multi_core_integer_score,
            multi_core_float_score=multi_core_float_score
        )
        
    def setup(self, serial_executor, adb_manager) -> None:
        benchmark_logger.info("Setting up Geekbench benchmark on device...")
        if self.config.get('collect_telemetry', False):
            self.telemetry_timestamp = setup_telemetry(adb_manager)
    
    def execute_lifecycle(self, serial_executor: SerialCommandExecutor, adb_manager: Any = None) -> Dict[str, Any]:
        """
        Main execution method called by harness.
        Returns results dictionary.
        """
        if hasattr(self, 'setup') and callable(getattr(self, 'setup')):
            self.setup(serial_executor, adb_manager)
            
        self.serial = serial_executor
        
        # Collect device info from target device
        benchmark_logger.info(f"{_LOG_PREFIX} Collecting device information from target...")
        device_info = {}
        try:
            device_info = collect_device_info_remote(serial_executor)
            benchmark_logger.info(f"{_LOG_PREFIX} Device: {device_info.get('model', 'unknown')}")
        except Exception as e:
            benchmark_logger.warning(f"{_LOG_PREFIX} Failed to collect device info: {e}")
            device_info = {
                'model': 'collection failed',
                'os_pretty_name': 'unknown',
                'os_build_id': 'unknown',
                'kernel': 'not available'
            }
        
        metadata = {
            "benchmark_name": self.name,
            "timestamp_utc": time.strftime("%Y-%m-%d %H:%M:%S"),
            "os_build_id": device_info.get('os_build_id', adb_manager.get_build_id() if adb_manager else "unknown"),
            "os_pretty_name": device_info.get('os_pretty_name', getattr(adb_manager, "get_os_version", lambda: "Linux")() if adb_manager and hasattr(adb_manager, "get_os_version") else "Linux"),
            "total_iterations_executed": self.iterations * len(self.tests_to_run),
            "iterations_run": 0,
            "warmup_iterations_discarded": 0,
            "outlier_iterations_discarded": 0,
            "device_info": device_info
        }
        
        results = {"metadata": metadata, "tests": {}}
        
        for idx, test_id in enumerate(self.tests_to_run):
            if test_id not in self.test_params:
                benchmark_logger.warning(f"{_LOG_PREFIX} Test {test_id} not found. Skipping.")
                continue
            
            params = self.test_params[test_id]
            cmd = self._build_command(test_id, params)
            benchmark_logger.info(f"{_LOG_PREFIX} Running {test_id}: {cmd}")
            
            raw_iterations = []
            total_runs = self.iterations
            
            for i in range(1, total_runs + 1):
                iter_label = f"{i}/{self.iterations}"
                benchmark_logger.info(f"{_LOG_PREFIX} Iteration {iter_label}")
                
                # Execute command (Geekbench takes ~2-3 minutes)
                benchmark_logger.info(f"{_LOG_PREFIX} Executing Geekbench (this may take 2-3 minutes)...")
                output = self.serial.execute_command(cmd, timeout_override=300)  # 5 minute timeout
                
                # Parse result
                res = self._parse_output(output, i, test_id)
                benchmark_logger.info(
                    f"{_LOG_PREFIX} Result: Single-Core={res.single_core_score:.0f}, "
                    f"Multi-Core={res.multi_core_score:.0f}"
                )
                
                # Convert to dict and add metadata
                it_dict = asdict(res)
                it_dict["is_outlier"] = False
                raw_iterations.append(it_dict)
                
                # Cooldown between iterations
                if i < total_runs:
                    benchmark_logger.info(f"{_LOG_PREFIX} Cooling down for 10 seconds...")
                    time.sleep(10)
            
            if not raw_iterations:
                continue
                
            # Use all iterations for analysis (no warm-up for Geekbench)
            analysis_iterations = raw_iterations
            
            # Run outlier detection
            clean_iterations = analysis_iterations
            outlier_discarded_count = 0
            
            if len(analysis_iterations) >= 3:
                try:
                    detector = OutlierDetectorRegistry.get("geekbench")
                    out = detector.run_detection(
                        analysis_iterations,
                        n_iterations=len(analysis_iterations),
                        min_iterations=2,
                        benchmark_variant=test_id,
                        run_id=self.telemetry_timestamp
                    )
                    clean_iterations = out.get("clean_iterations", analysis_iterations)
                    outlier_discarded_indices = out.get("discarded_indices", [])
                    outlier_discarded_count = len(outlier_discarded_indices)
                    
                    # Mark outliers
                    for raw_idx in outlier_discarded_indices:
                        if raw_idx < len(analysis_iterations):
                            analysis_iterations[raw_idx]["is_outlier"] = True
                            
                except Exception as e:
                    benchmark_logger.warning(f"{_LOG_PREFIX} Outlier detection failed: {e}")
            
            outliers_discarded = len(analysis_iterations) - len(clean_iterations)
            
            # Store results
            results["tests"][test_id] = {
                "category": params.get("category", "cpu_benchmark"),
                "iterations": raw_iterations,
                "clean_iterations_count": len(clean_iterations),
                "outlier_discarded_count": outliers_discarded,
                "single_core_scores": [r.get("single_core_score") for r in clean_iterations],
                "multi_core_scores": [r.get("multi_core_score") for r in clean_iterations]
            }
            
            results["metadata"]["iterations_run"] += len(clean_iterations)
            results["metadata"]["outlier_iterations_discarded"] += outliers_discarded
            
            # Cooldown gap between different tests (if multiple)
            if idx < len(self.tests_to_run) - 1:
                benchmark_logger.info(f"{_LOG_PREFIX} Cooling down for 10 seconds between tests...")
                time.sleep(10)
                
        if hasattr(self, 'teardown') and callable(getattr(self, 'teardown')):
            self.teardown(serial_executor, adb_manager)
            
        return results

    def teardown(self, serial_executor, adb_manager) -> None:
        teardown_telemetry(adb_manager, self.run_dir, self.telemetry_timestamp)

# REQUIRED: Export the benchmark class for auto-discovery
BENCHMARK_CLASS = GeekbenchBenchmark
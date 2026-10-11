"""
coremark.py - Coremark benchmark engine
Executes Coremark and parses results.

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

_LOG_PREFIX = "[coremark]"

@dataclass
class CoremarkIterationResult:
    """Data class for a single Coremark iteration"""
    iteration: int
    test_name: str
    score: float
    iterations_per_sec: float
    time_taken: float

class CoremarkBenchmark:
    """Coremark benchmark implementation"""
    
    def __init__(self, name: str, config: Dict[str, Any], run_dir: Path):
        self.name = name
        self.config = config
        self.run_dir = run_dir
        self.command_base = self.config.get("command", "/usr/bin/coremark")
        self.iterations = self.config.get("iterations", 3)
        self.test_params = self.config.get("test_params", {})
        self.tests_to_run = self.config.get("tests", ["default"])
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
    
    def _parse_output(self, output: str, iteration: int, test_name: str) -> CoremarkIterationResult:
        """
        Parse Coremark output.
        Extract metrics from the raw output string.
        """
        score = 0.0
        iterations_per_sec = 0.0
        time_taken = 0.0
        
        for line in output.split('\n'):
            line = line.strip()
            # Iterations/Sec   : 23150.312601
            if 'Iterations/Sec' in line:
                match = re.search(r'Iterations/Sec\s*:\s*([\d.]+)', line)
                if match:
                    iterations_per_sec = float(match.group(1))
            # CoreMark 1.0 : 23150.312601 / GCC11.2.0 -O3 -fno-common ...
            elif 'CoreMark' in line and ':' in line and '/' in line:
                match = re.search(r'CoreMark[a-zA-Z0-9.\s]*:\s*([\d.]+)', line)
                if match:
                    score = float(match.group(1))
            # Total time (secs): 12.958788
            elif 'Total time' in line:
                match = re.search(r'Total time\s*\(secs\)\s*:\s*([\d.]+)', line)
                if match:
                    time_taken = float(match.group(1))
        
        # If score wasn't found but iterations_per_sec was, use that as the score
        if score == 0.0 and iterations_per_sec > 0:
            score = iterations_per_sec
            
        if score <= 0:
            benchmark_logger.error(f"{_LOG_PREFIX} Failed to parse valid score from output:\n{output}")
            
        return CoremarkIterationResult(
            iteration=iteration,
            test_name=test_name,
            score=score,
            iterations_per_sec=iterations_per_sec,
            time_taken=time_taken
        )
        
    def setup(self, serial_executor, adb_manager) -> None:
        benchmark_logger.info("Setting up Coremark benchmark on device...")
        if self.config.get('collect_telemetry', False):
            self.telemetry_timestamp = setup_telemetry(adb_manager)
    
    def execute_lifecycle(self, serial_executor: SerialCommandExecutor, adb_manager: Any = None) -> Dict[str, Any]:
        """
        Main execution method called by harness.
        Returns results dictionary.
        """
        benchmark_logger.configure_run_dir(self.run_dir)
        benchmark_logger.set_phase("setup")
        if hasattr(self, 'setup') and callable(getattr(self, 'setup')):
            self.setup(serial_executor, adb_manager)

        self.serial = serial_executor
        benchmark_logger.set_phase("benchmark")
        
        metadata = {
            "benchmark": self.name,
            "timestamp_utc": time.strftime("%Y-%m-%d %H:%M:%S"),
            "os_build_id": adb_manager.get_build_id() if adb_manager else "unknown",
            "os_pretty_name": adb_manager.get_pretty_name() if adb_manager and hasattr(adb_manager, "get_pretty_name") else "Linux",
            "total_iterations_executed": self.iterations * len(self.tests_to_run),
            "iterations_run": 0,
            "warmup_iterations_discarded": 0,
            "outlier_iterations_discarded": 0
        }
        
        results = {"metadata": metadata, "tests": {}}

        try:
            self._run_all_tests(results)
        finally:
            benchmark_logger.set_phase("teardown")
            if hasattr(self, 'teardown') and callable(getattr(self, 'teardown')):
                self.teardown(serial_executor, adb_manager)
            benchmark_logger.end_phase()

        return results

    def _run_all_tests(self, results: Dict[str, Any]) -> None:
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
                
                # Execute command
                output = self.serial.execute_command(cmd, timeout_override=0)
                
                # Parse result
                res = self._parse_output(output, i, test_id)
                benchmark_logger.info(f"{_LOG_PREFIX} Result: Score={res.score:.2f}, Time={res.time_taken:.2f}s")
                
                # Convert to dict and add metadata
                it_dict = asdict(res)
                it_dict["is_outlier"] = False
                raw_iterations.append(it_dict)
                
                # Cooldown between iterations
                if i < total_runs:
                    benchmark_logger.info(f"{_LOG_PREFIX} Cooling down for 5 seconds...")
                    time.sleep(5)
            
            if not raw_iterations:
                continue
                
            # Use all iterations for analysis (warm-up feature removed)
            analysis_iterations = raw_iterations
            
            # Run outlier detection
            clean_iterations = analysis_iterations
            outlier_discarded_count = 0
            
            if len(analysis_iterations) >= 3:
                try:
                    detector = OutlierDetectorRegistry.get("coremark")
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
                "category": params.get("category", "performance"),
                "iterations": raw_iterations,
                "clean_iterations_count": len(clean_iterations),
                "outlier_discarded_count": outliers_discarded,
                "throughput": [r.get("score") for r in clean_iterations]
            }
            
            results["metadata"]["iterations_run"] += len(clean_iterations)
            results["metadata"]["outlier_iterations_discarded"] += outliers_discarded
            
            # Cooldown gap between different tests
            if idx < len(self.tests_to_run) - 1:
                benchmark_logger.info(f"{_LOG_PREFIX} Cooling down for 5 seconds between different test flavors...")
                time.sleep(5)

    def teardown(self, serial_executor, adb_manager) -> None:
        teardown_telemetry(adb_manager, self.run_dir, self.telemetry_timestamp)

# REQUIRED: Export the benchmark class for auto-discovery
BENCHMARK_CLASS = CoremarkBenchmark

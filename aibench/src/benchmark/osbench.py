"""
osbench.py - OSBench benchmark lifecycle implementation
Inherits from BenchmarkBase.

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import re
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Any, Dict, List
from datetime import datetime
from src.benchmark.base import BenchmarkBase
from src.utils.logger import phase_logger
from src.utils.telemetry_helpers import setup_telemetry, teardown_telemetry

@dataclass
class OSBenchResult:
    workload_id: str
    time_us: float = 0.0
    raw_output: str = ""

class OSBenchParser:
    @staticmethod
    def parse_block(content: str, workload_id: str) -> OSBenchResult:
        result = OSBenchResult(workload_id=workload_id, raw_output=content)
        
        # Match pattern like "74.682236 us / program"
        # Example output:
        # Benchmark: Launch 100 programs...
        # 74.682236 us / program
        match = re.search(r'([0-9.]+)\s*us\s*/', content)
        if match:
            result.time_us = float(match.group(1))
            
        return result

class OSBenchBenchmark(BenchmarkBase):
    def __init__(self, name: str, config: Dict[str, Any], run_dir: Path):
        super().__init__(name, config, run_dir)
        self.iterations = max(self.config.get("iterations", 3), 1)
        self.tests_to_run = self.config.get("tests", ["osbench_default"])
        self.microbenchmarks = self.config.get("microbenchmarks", {
            "launch_programs": None,
            "create_files": "/root/",
            "create_processes": None,
            "create_threads": None
        })
        self.base_dir = "/usr/bin"
        self.telemetry_timestamp = ""
        
    def setup(self, serial_executor, adb_manager) -> None:
        phase_logger.info("Setting up OSBench benchmark on device...")
        # Check if binaries exist
        for mb_name in self.microbenchmarks.keys():
            bin_path = f"{self.base_dir}/{mb_name}"
            check = serial_executor.execute_command(f"ls {bin_path} 2>/dev/null")
            if mb_name not in check:
                phase_logger.warning(f"Binary {bin_path} not found on device!")

        if self.config.get('collect_telemetry', False):
            self.telemetry_timestamp = setup_telemetry(adb_manager)

    def run(self, serial_executor, adb_manager) -> Dict[str, Any]:
        parsed_results: Dict[str, List[OSBenchResult]] = {}
        
        # Initialize result lists
        # Since we just have one default test we use microbenchmark name as key
        for mb_name in self.microbenchmarks.keys():
            key = f"osbench_{mb_name}"
            parsed_results[key] = []

        logs_dir = self.run_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        for iteration in range(1, self.iterations + 1):
            phase_logger.info(f"--- OSBench Iteration {iteration}/{self.iterations} ---")
            
            for mb_name, mb_args in self.microbenchmarks.items():
                key = f"osbench_{mb_name}"
                
                # Construct command with args if provided
                cmd = f"{self.base_dir}/{mb_name}"
                if isinstance(mb_args, str) and mb_args.strip():
                    cmd = f"{cmd} {mb_args.strip()}"
                    
                phase_logger.info(f"Running {key}: {cmd}")
                
                output = serial_executor.execute_command(cmd, timeout_override=0)
                
                # Write log
                log_file = logs_dir / f"{key}_output.txt"
                with open(log_file, "a", encoding="utf-8") as f:
                    f.write(f"\n=== Iteration {iteration} ===\n")
                    f.write(output)
                    
                # Parse
                parsed = OSBenchParser.parse_block(output, mb_name)
                if parsed.time_us == 0.0:
                    phase_logger.warning(f"Failed to parse output for {key}")
                else:
                    phase_logger.info(f"Parsed {key} time (us): {parsed.time_us}")
                
                parsed_results[key].append(parsed)

        # Format metrics structure
        now_local = datetime.now()
        os_info = adb_manager.get_os_release_info()

        formatted_tests = {}
        for key, res_list in parsed_results.items():
            if not res_list:
                continue
                
            formatted_tests[key] = {
                # Store it as 'throughput' internally so aggregator handles it,
                # but map metric_direction = lower in config
                "throughput": [r.time_us for r in res_list],
                "raw_iterations": [asdict(r) for r in res_list]
            }

        metrics = {
            "metadata": {
                "timestamp_utc": now_local.strftime("%Y-%m-%d %H:%M:%S"),
                "os_pretty_name": os_info.get("pretty_name", "Unknown"),
                "os_build_id": os_info.get("build_id", "Unknown"),
                "iterations_run": self.iterations,
                "benchmark_name": "osbench"
            },
            "tests": formatted_tests
        }
        
        return metrics

    def teardown(self, serial_executor, adb_manager) -> None:
        teardown_telemetry(adb_manager, self.run_dir, self.telemetry_timestamp)

BENCHMARK_CLASS = OSBenchBenchmark

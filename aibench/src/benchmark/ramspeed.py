"""
ramspeed.py - RAMSpeed benchmark lifecycle implementation
Inherits from BenchmarkBase.

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import re
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Dict, List
from datetime import datetime
from src.benchmark.base import BenchmarkBase
from src.utils.logger import phase_logger
from src.utils.telemetry_helpers import setup_telemetry, teardown_telemetry

@dataclass
class RAMSpeedResult:
    workload_id: str
    throughput_mbps: float = 0.0
    raw_output: str = ""

class RAMSpeedParser:
    @staticmethod
    def parse_block(content: str, benchmark_id: str) -> RAMSpeedResult:
        result = RAMSpeedResult(workload_id=benchmark_id, raw_output=content)
        
        # -b 1, 2, 4, 5 (Individual read/write tests) match "32768 Kb block: XXX Mb/s"
        # -b 3, 6 (Average tests) match "AVERAGE: XXX Mb/s"
        if benchmark_id in ["1", "2", "4", "5"]:
            match = re.search(r'32768 Kb block:\s*([0-9.]+)\s*Mb/s', content)
            if match:
                result.throughput_mbps = float(match.group(1))
        elif benchmark_id in ["3", "6"]:
            match = re.search(r'AVERAGE:\s*([0-9.]+)\s*Mb/s', content)
            if match:
                result.throughput_mbps = float(match.group(1))
                
        return result

class RAMSpeedBenchmark(BenchmarkBase):
    def __init__(self, name: str, config: Dict[str, Any], run_dir: Path):
        super().__init__(name, config, run_dir)
        self.iterations = max(self.config.get("iterations", 3), 1)
        self.tests_to_run = self.config.get("tests", ["ramspeed_single", "ramspeed_multi"])
        
        # Common params like -m 32 -g 8 -r
        self.common_params = self.config.get("common_params", {})
        
        # Mapping of benchmark ID to string name e.g. "1": "intmark_writing"
        self.benchmark_ids = self.config.get("benchmark_ids", {
            "1": "intmark_writing",
            "2": "intmark_reading",
            "3": "integer_average",
            "4": "floatmark_writing",
            "5": "floatmark_reading",
            "6": "float_average"
        })
        
        self.telemetry_timestamp = ""
        
    def setup(self, serial_executor, adb_manager) -> None:
        phase_logger.info("Setting up RAMSpeed benchmark on device...")
        binaries = ["/usr/bin/ramspeed", "/usr/bin/ramsmp"]
        for b in binaries:
            check = serial_executor.execute_command(f"ls {b} 2>/dev/null")
            if "No such file" in check or b not in check:
                phase_logger.warning(f"Binary {b} might not be found on device!")

        if self.config.get('collect_telemetry', False):
            self.telemetry_timestamp = setup_telemetry(adb_manager)

    def run(self, serial_executor, adb_manager) -> Dict[str, Any]:
        parsed_results: Dict[str, List[RAMSpeedResult]] = {}
        
        # Initialize result lists for all configured tests and benchmark IDs
        for test_type in self.tests_to_run:
            for b_id, b_name in self.benchmark_ids.items():
                key = f"{test_type}_b{b_id}_{b_name}"
                parsed_results[key] = []

        logs_dir = self.run_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        # Build base params string
        base_params = []
        for k, v in self.common_params.items():
            if isinstance(v, (str, int, float)) and str(v).strip():
                base_params.append(f"{k} {v}")
            else:
                base_params.append(f"{k}")
        base_params_str = " ".join(base_params)

        for iteration in range(1, self.iterations + 1):
            phase_logger.info(f"--- RAMSpeed Iteration {iteration}/{self.iterations} ---")
            
            for test_type in self.tests_to_run:
                # Determine binary and specific arguments
                if test_type == "ramspeed_single":
                    binary = "/usr/bin/ramspeed"
                    core_param = ""
                elif test_type == "ramspeed_multi":
                    binary = "/usr/bin/ramsmp"
                    core_param = "-p $(nproc)"
                else:
                    phase_logger.warning(f"Unknown test type: {test_type}")
                    continue
                
                for b_id, b_name in self.benchmark_ids.items():
                    key = f"{test_type}_b{b_id}_{b_name}"
                    
                    cmd_parts = [binary, base_params_str, f"-b {b_id}"]
                    if core_param:
                        cmd_parts.append(core_param)
                        
                    cmd = " ".join(cmd_parts)
                    
                    phase_logger.info(f"Running {key}: {cmd}")
                    output = serial_executor.execute_command(cmd, timeout_override=0)
                    
                    # Write log
                    log_file = logs_dir / f"{key}_output.txt"
                    with open(log_file, "a", encoding="utf-8") as f:
                        f.write(f"\n=== Iteration {iteration} ===\n")
                        f.write(output)
                        
                    # Parse
                    parsed = RAMSpeedParser.parse_block(output, str(b_id))
                    if parsed.throughput_mbps == 0.0:
                        phase_logger.warning(f"Failed to parse output for {key}")
                    else:
                        phase_logger.info(f"Parsed {key} throughput (MB/s): {parsed.throughput_mbps}")
                    
                    parsed_results[key].append(parsed)

        # Format metrics structure
        now_local = datetime.now()
        os_info = adb_manager.get_os_release_info()

        formatted_tests = {}
        for key, res_list in parsed_results.items():
            if not res_list:
                continue
                
            formatted_tests[key] = {
                "throughput": [r.throughput_mbps for r in res_list],
            }

        metrics = {
            "metadata": {
                "timestamp_utc": now_local.strftime("%Y-%m-%d %H:%M:%S"),
                "os_pretty_name": os_info.get("pretty_name", "Unknown"),
                "os_build_id": os_info.get("build_id", "Unknown"),
                "iterations_run": self.iterations,
                "benchmark_name": "ramspeed"
            },
            "tests": formatted_tests
        }
        
        return metrics

    def teardown(self, serial_executor, adb_manager) -> None:
        teardown_telemetry(adb_manager, self.run_dir, self.telemetry_timestamp)

BENCHMARK_CLASS = RAMSpeedBenchmark

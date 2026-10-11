"""
coremark_pro.py - Coremark-Pro benchmark lifecycle implementation
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
class CoremarkProResult:
    workload_id: str
    contexts: int = 0
    iterations: int = 0
    time_secs: float = 0.0
    secs_per_workload: float = 0.0
    workloads_per_sec: float = 0.0
    raw_output: str = ""

class CoremarkProParser:
    @staticmethod
    def parse_block(content: str) -> CoremarkProResult:
        workload_id = ""
        # Match workload id from the Workloads/sec line
        match_id = re.search(r'-- ([a-zA-Z0-9_-]+):workloads/sec=', content)
        if match_id:
            workload_id = match_id.group(1)
            
        result = CoremarkProResult(workload_id=workload_id, raw_output=content)
        
        if not workload_id:
            return result
            
        m_ctx = re.search(fr'-- {workload_id}:contexts=\s*(\d+)', content)
        if m_ctx: result.contexts = int(m_ctx.group(1))
            
        m_iter = re.search(fr'-- {workload_id}:iterations=\s*(\d+)', content)
        if m_iter: result.iterations = int(m_iter.group(1))
            
        m_time = re.search(fr'-- {workload_id}:time\(secs\)=\s*([0-9.]+)', content)
        if m_time: result.time_secs = float(m_time.group(1))
            
        m_spw = re.search(fr'-- {workload_id}:secs/workload=\s*([0-9.]+)', content)
        if m_spw: result.secs_per_workload = float(m_spw.group(1))
            
        m_wps = re.search(fr'-- {workload_id}:workloads/sec=\s*([0-9.]+)', content)
        if m_wps: result.workloads_per_sec = float(m_wps.group(1))
            
        return result


class CoremarkProBenchmark(BenchmarkBase):
    def __init__(self, name: str, config: Dict[str, Any], run_dir: Path):
        super().__init__(name, config, run_dir)
        self.iterations = max(self.config.get("iterations", 3), 1)
        self.tests_to_run = self.config.get("tests", ["coremark_pro_single", "coremark_pro_multi"])
        self.microbenchmarks = self.config.get("microbenchmarks", {})
        self.base_dir = "/usr/bin"
        self.telemetry_timestamp = ""
        
    def setup(self, serial_executor, adb_manager) -> None:
        phase_logger.info("Setting up Coremark-Pro benchmark on device...")
        # Check if binaries exist
        for mb_name in self.microbenchmarks.keys():
            bin_path = f"{self.base_dir}/{mb_name}"
            check = serial_executor.execute_command(f"ls {bin_path} 2>/dev/null")
            if mb_name not in check:
                phase_logger.warning(f"Binary {bin_path} not found on device!")

        if self.config.get('collect_telemetry', False):
            self.telemetry_timestamp = setup_telemetry(adb_manager)

    def run(self, serial_executor, adb_manager) -> Dict[str, Any]:
        parsed_results: Dict[str, List[CoremarkProResult]] = {}
        
        # Initialize result lists
        for test_id in self.tests_to_run:
            for mb_name in self.microbenchmarks.keys():
                key = f"{test_id}_{mb_name}"
                parsed_results[key] = []

        logs_dir = self.run_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        for iteration in range(1, self.iterations + 1):
            phase_logger.info(f"--- Coremark-Pro Iteration {iteration}/{self.iterations} ---")
            
            for test_id in self.tests_to_run:
                is_multi = "multi" in test_id
                core_flag = "-c$(nproc)" if is_multi else "-c1"
                
                for mb_name, mb_iters in self.microbenchmarks.items():
                    key = f"{test_id}_{mb_name}"
                    
                    cmd = f"{self.base_dir}/{mb_name} -v0 {core_flag} -i{mb_iters}"
                    phase_logger.info(f"Running {key}: {cmd}")
                    
                    output = serial_executor.execute_command(cmd, timeout_override=0)
                    
                    # Write log
                    log_file = logs_dir / f"{key}_output.txt"
                    with open(log_file, "a", encoding="utf-8") as f:
                        f.write(f"\n=== Iteration {iteration} ===\n")
                        f.write(output)
                        
                    # Parse
                    parsed = CoremarkProParser.parse_block(output)
                    if not parsed.workload_id:
                        phase_logger.warning(f"Failed to parse output for {key}")
                    else:
                        phase_logger.info(f"Parsed {key} workloads/sec: {parsed.workloads_per_sec}")
                    
                    parsed_results[key].append(parsed)

        # Format metrics structure
        now_local = datetime.now()
        os_info = adb_manager.get_os_release_info()

        formatted_tests = {}
        for key, res_list in parsed_results.items():
            if not res_list:
                continue
                
            formatted_tests[key] = {
                "throughput": [r.workloads_per_sec for r in res_list],
                "time_secs": [r.time_secs for r in res_list],
                "secs_per_workload": [r.secs_per_workload for r in res_list],
                "contexts": [r.contexts for r in res_list],
                "iterations_run": [r.iterations for r in res_list],
                "raw_iterations": [asdict(r) for r in res_list]
            }

        metrics = {
            "metadata": {
                "timestamp_utc": now_local.strftime("%Y-%m-%d %H:%M:%S"),
                "os_pretty_name": os_info.get("pretty_name", "Unknown"),
                "os_build_id": os_info.get("build_id", "Unknown"),
                "iterations_run": self.iterations,
                "benchmark_name": "coremark_pro"
            },
            "tests": formatted_tests
        }
        
        return metrics

    def teardown(self, serial_executor, adb_manager) -> None:
        teardown_telemetry(adb_manager, self.run_dir, self.telemetry_timestamp)

BENCHMARK_CLASS = CoremarkProBenchmark

"""
tiobench.py - TIOBench benchmark lifecycle implementation
Inherits from BenchmarkBase.

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import re
import json
import time
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Any, Dict, List
from datetime import datetime
from src.benchmark.base import BenchmarkBase
from src.utils.logger import phase_logger
from src.utils.telemetry_helpers import setup_telemetry, teardown_telemetry

@dataclass
class LatencyMetrics:
    avg_ms: float = 0.0
    max_ms: float = 0.0
    p_gt_2s: float = 0.0
    p_gt_10s: float = 0.0

@dataclass
class PerformanceMetrics:
    write_rate_mbs: float = 0.0
    read_rate_mbs: float = 0.0
    write_usr_cpu: float = 0.0
    write_sys_cpu: float = 0.0
    read_usr_cpu: float = 0.0
    read_sys_cpu: float = 0.0

@dataclass
class TiotestBlockResult:
    performance: PerformanceMetrics
    latency: Dict[str, LatencyMetrics]

class TiotestParser:
    RUN_CMD_PATTERN = re.compile(r'#\s*Running:\s*(?P<cmd>.+)')
    BLOCK_SIZE_PATTERN = re.compile(r'-b\s+(\d+)')
    
    PERF_PATTERN = re.compile(
        r'(?:Random\s+)?Write\s+\d+\s*MBs\s*\|\s*[\d.]+\s*s\s*\|\s*([\d.]+)\s*MB/s\s*\|\s*([\d.]+)\s*%\s*\|\s*([\d.]+)\s*%\s*\|'
        r'.*?'
        r'(?:Random\s+)?Read\s+\d+\s*MBs\s*\|\s*[\d.]+\s*s\s*\|\s*([\d.]+)\s*MB/s\s*\|\s*([\d.]+)\s*%\s*\|\s*([\d.]+)\s*%\s*\|',
        re.DOTALL
    )
    
    LATENCY_PATTERN = re.compile(
        r'(?:Random\s+)?Write\s*\|\s*([\d.]+)\s*ms\s*\|\s*([\d.]+)\s*ms\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|'
        r'.*?'
        r'(?:Random\s+)?Read\s*\|\s*([\d.]+)\s*ms\s*\|\s*([\d.]+)\s*ms\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|',
        re.DOTALL
    )

    def parse(self, full_output: str) -> Dict[str, TiotestBlockResult]:
        results: Dict[str, TiotestBlockResult] = {}
        run_markers = list(self.RUN_CMD_PATTERN.finditer(full_output))
        
        for i, marker in enumerate(run_markers):
            cmd_line = marker.group('cmd')
            block_start = marker.end()
            block_end = (
                run_markers[i + 1].start()
                if i + 1 < len(run_markers)
                else len(full_output)
            )
            block_text = full_output[block_start:block_end]

            block_size_match = self.BLOCK_SIZE_PATTERN.search(cmd_line)
            if not block_size_match:
                continue
            block_size = block_size_match.group(1)

            results[block_size] = TiotestBlockResult(
                performance=self._parse_performance(block_text),
                latency=self._parse_latency(block_text),
            )

        return results

    def _parse_performance(self, block_text: str) -> PerformanceMetrics:
        match = self.PERF_PATTERN.search(block_text)
        if not match:
            return PerformanceMetrics()
        return PerformanceMetrics(
            write_rate_mbs=float(match.group(1)),
            write_usr_cpu=float(match.group(2)),
            write_sys_cpu=float(match.group(3)),
            read_rate_mbs=float(match.group(4)),
            read_usr_cpu=float(match.group(5)),
            read_sys_cpu=float(match.group(6)),
        )

    def _parse_latency(self, block_text: str) -> Dict[str, LatencyMetrics]:
        match = self.LATENCY_PATTERN.search(block_text)
        if not match:
            return {'write': LatencyMetrics(), 'read': LatencyMetrics()}
        return {
            'write': LatencyMetrics(
                avg_ms=float(match.group(1)),
                max_ms=float(match.group(2)),
                p_gt_2s=float(match.group(3)),
                p_gt_10s=float(match.group(4)),
            ),
            'read': LatencyMetrics(
                avg_ms=float(match.group(5)),
                max_ms=float(match.group(6)),
                p_gt_2s=float(match.group(7)),
                p_gt_10s=float(match.group(8)),
            ),
        }

class TiobenchBenchmark(BenchmarkBase):
    def __init__(self, name: str, config: Dict[str, Any], run_dir: Path):
        super().__init__(name, config, run_dir)
        self.telemetry_timestamp = ""
        self.iterations = max(self.config.get("iterations", 3), 3)
        self.test_types = self.config.get("test_types", ["sequential", "random"])

    def setup(self, serial_executor, adb_manager) -> None:
        phase_logger.info("Setting up TIOBench on device...")
        if self.config.get('collect_telemetry', False):
            self.telemetry_timestamp = setup_telemetry(adb_manager)

    def _clear_cache(self, adb_manager):
        phase_logger.info("Purging cache memory before I/O test (drop_caches)...")
        adb_manager.execute_shell_command("sync && echo 3 > /proc/sys/vm/drop_caches")

    def _build_command(self, test_id: str, params: Dict[str, Any]) -> str:
        """Builds the tiotest command string dynamically from test_params."""
        cmd_parts = ["tiotest"]
        
        for k, v in params.items():
            if v == "" or v is None:
                cmd_parts.append(str(k))
            elif k == "-k" and isinstance(v, str) and "," in v:
                # Handle comma-separated values for -k (e.g. -k: "1,3" -> -k1 -k3)
                for item in v.split(","):
                    cmd_parts.append(f"{k}{item.strip()}")
            elif k == "-k" and isinstance(v, (int, str)):
                # Handle single -k values formatted without space (e.g. -k: 1 -> -k1)
                cmd_parts.append(f"{k}{v}")
            elif isinstance(v, list):
                # Handle duplicate keys parsed as lists (e.g. -k: [3, 1])
                for item in v:
                    if item is True:
                        cmd_parts.append(str(k))
                    else:
                        if k == "-k":
                            cmd_parts.append(f"{k}{item}")
                        else:
                            cmd_parts.append(f"{k} {item}")
            else:
                # tiotest accepts space-separated arguments (e.g. "-t 8")
                # Handle special case where a user might pass boolean true
                if v is True:
                    cmd_parts.append(str(k))
                else:
                    cmd_parts.append(f"{k} {v}")
                    
        return " ".join(cmd_parts)

    def run(self, serial_executor, adb_manager) -> Dict[str, Any]:
        phase_logger.info(f"Running TIOBench for {self.iterations} iterations...")
        
        # Get active tests list from test_params
        test_params = self.config.get("test_params", {})
        tests_to_run = self.config.get("tests", list(test_params.keys()))
        
        active_tests = []
        for test_id in tests_to_run:
            if test_id in test_params:
                active_tests.append((test_id, self._build_command(test_id, test_params[test_id])))
                
        if not active_tests:
            phase_logger.warning("No active tiotest commands found in config!")
            
        # Buffer to keep concatenated run logs
        full_raw_outputs = []
        
        # Structured results per test type
        test_results = {test_id: {"iterations": []} for test_id, _ in active_tests}
        
        # Run iterations
        for iteration in range(1, self.iterations + 1):
            phase_logger.info(f"--- TIOBench Iteration {iteration}/{self.iterations} ---")
            for test_id, cmd in active_tests:
                self._clear_cache(adb_manager)
                
                phase_logger.info(f"Executing: {cmd}")
                marker = f"# Running: {cmd}\n"
                full_raw_outputs.append(marker)
                
                output = serial_executor.execute_command(cmd, timeout_override=0)
                
                if not output or not output.strip():
                    phase_logger.warning(f"Warning: Command '{cmd}' returned empty output!")
                    
                full_raw_outputs.append(output + "\n")
                
                # Parse just this iteration's output
                parser = TiotestParser()
                parsed_iteration = parser.parse(marker + output)
                
                test_results[test_id]["iterations"].append({
                    "iteration": iteration,
                    "cmd": cmd,
                    "block_sizes": {k: asdict(v) for k, v in parsed_iteration.items()}
                })

        # Write output file to host run folder for triage
        concatenated_output = "".join(full_raw_outputs)
        logs_dir = self.run_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        with open(logs_dir / "tiotest_raw.log", "w", encoding="utf-8") as f:
            f.write(concatenated_output)

        # Build standardized result structure
        now_local = datetime.now()
        timestamp_display = now_local.strftime("%Y-%m-%d %H:%M:%S")
        os_info = adb_manager.get_os_release_info()

        metrics = {
            "metadata": {
                "timestamp_utc": timestamp_display,
                "os_pretty_name": os_info.get("pretty_name", "Unknown"),
                "os_build_id": os_info.get("build_id", "Unknown"),
                "iterations_run": self.iterations,
                "benchmark_name": "tiobench"
            }
        }
        
        # Calculate averages for each test type
        for test_id, data in test_results.items():
            metrics[test_id] = {
                "iterations": data["iterations"],
                "average_bandwidth": {},
                "average_latency": {"write": {}, "read": {}}
            }
            
            # Gather all performance metrics to calculate averages
            # We assume all iterations have the same block size. For simplicity, we just average all blocks.
            write_rates, read_rates = [], []
            write_usr_cpus, write_sys_cpus = [], []
            read_usr_cpus, read_sys_cpus = [], []
            
            lat_w_avg, lat_w_max, lat_r_avg, lat_r_max = [], [], [], []
            
            for iter_data in data["iterations"]:
                for block_size, block_data in iter_data["block_sizes"].items():
                    perf = block_data["performance"]
                    write_rates.append(perf["write_rate_mbs"])
                    read_rates.append(perf["read_rate_mbs"])
                    write_usr_cpus.append(perf["write_usr_cpu"])
                    write_sys_cpus.append(perf["write_sys_cpu"])
                    read_usr_cpus.append(perf["read_usr_cpu"])
                    read_sys_cpus.append(perf["read_sys_cpu"])
                    
                    lat = block_data["latency"]
                    lat_w_avg.append(lat["write"]["avg_ms"])
                    lat_w_max.append(lat["write"]["max_ms"])
                    lat_r_avg.append(lat["read"]["avg_ms"])
                    lat_r_max.append(lat["read"]["max_ms"])
                    
            if write_rates:
                metrics[test_id]["average_bandwidth"] = {
                    "write_rate_mbs": sum(write_rates) / len(write_rates),
                    "read_rate_mbs": sum(read_rates) / len(read_rates),
                    "write_usr_cpu": sum(write_usr_cpus) / len(write_usr_cpus),
                    "write_sys_cpu": sum(write_sys_cpus) / len(write_sys_cpus),
                    "read_usr_cpu": sum(read_usr_cpus) / len(read_usr_cpus),
                    "read_sys_cpu": sum(read_sys_cpus) / len(read_sys_cpus),
                }
            if lat_w_avg:
                metrics[test_id]["average_latency"]["write"] = {
                    "avg_ms": sum(lat_w_avg) / len(lat_w_avg),
                    "max_ms": max(lat_w_max) # Using max of maxes is more representative than avg of maxes
                }
                metrics[test_id]["average_latency"]["read"] = {
                    "avg_ms": sum(lat_r_avg) / len(lat_r_avg),
                    "max_ms": max(lat_r_max)
                }

        return metrics

    def teardown(self, serial_executor, adb_manager) -> None:
        teardown_telemetry(adb_manager, self.run_dir, self.telemetry_timestamp)

BENCHMARK_CLASS = TiobenchBenchmark

"""
sysbench.py - Sysbench benchmark lifecycle implementation
Inherits from BenchmarkBase.

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import re
import json
import time
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Tuple
from datetime import datetime
from src.benchmark.base import BenchmarkBase
from src.utils.logger import phase_logger
import statistics
from src.reporting.outlier_registry import OutlierDetectorRegistry
from src.utils.telemetry_helpers import setup_telemetry, teardown_telemetry

def generate_outlier_explanation(flagged_metrics: List[str], deviation_pct: float, method: str) -> str:
    """Generate a non-technical explanation of why an iteration was flagged as an outlier."""
    
    explanations = {
        "cpu_events_per_sec": "This iteration completed significantly fewer operations than the others, suggesting the system may have been temporarily busy or experiencing interference.",
        "latency_avg_ms": "The average response time for this iteration was noticeably higher than typical, indicating potential system slowdown.",
        "latency_p95_ms": "Most operations in this iteration took longer than expected, suggesting temporary system contention or resource constraints.",
        "latency_min_ms": "Even the fastest operations in this iteration were slower than usual.",
        "latency_max_ms": "This iteration experienced unusually long delays for some operations."
    }
    
    primary_reason = explanations.get(flagged_metrics[0] if flagged_metrics else "", "Performance metrics deviated from expected values.")
    
    if deviation_pct > 0:
        primary_reason += f" (Deviation: {deviation_pct:.1f}% from typical performance)"
    
    method_explanation = {
        "median_pct": "detected by comparing against the median (middle value) of all iterations",
        "iqr": "detected using statistical range analysis",
        "mad_zscore": "detected using advanced statistical analysis"
    }
    
    return f"{primary_reason} This was {method_explanation.get(method, 'detected by statistical analysis')}."

@dataclass
class SysbenchIterationResult:
    test_name: str
    category: str = ""
    
    # Common metrics
    throughput: float = 0.0
    total_events: int = 0
    total_time_sec: float = 0.0
    raw_output: str = ""
    
    # Latency metrics (all in ms)
    latency_min_ms: float = 0.0
    latency_avg_ms: float = 0.0
    latency_max_ms: float = 0.0
    latency_95_ms: float = 0.0
    latency_sum_ms: float = 0.0
    
    # Fairness metrics
    events_avg: float = 0.0
    events_stddev: float = 0.0
    execution_time_avg_sec: float = 0.0
    execution_time_stddev_sec: float = 0.0
    
    # Category-specific metrics
    operations_per_sec: float = 0.0  # Memory/FileIO
    data_transferred_mib: float = 0.0  # Memory/FileIO
    read_mib_sec: float = 0.0  # FileIO
    write_mib_sec: float = 0.0  # FileIO

class SysbenchParser:
    @staticmethod
    def parse_block(content: str, test_name: str) -> SysbenchIterationResult:
        # Determine category (strip prefix to maintain original parsing rules)
        parsed_name = test_name
        if parsed_name.startswith("sysbench_"):
            parsed_name = parsed_name[len("sysbench_"):]
            
        category = parsed_name.split('_')[0]
        
        # Route to appropriate parser
        from src.benchmark.sysbench_parsers import (
            ThreadsParser, MutexParser, MemoryParser, CPUParser, FileIOParser
        )
        
        if category == "threads":
            return ThreadsParser.parse(content, test_name)
        elif category == "mutex":
            return MutexParser.parse(content, test_name)
        elif category == "memory":
            return MemoryParser.parse(content, test_name)
        elif category == "cpu":
            return CPUParser.parse(content, test_name)
        elif category == "fileio":
            return FileIOParser.parse(content, test_name)
        else:
            # Fallback for unknown categories
            return SysbenchParser._parse_generic(content, test_name, category)

    @staticmethod
    def _parse_generic(content: str, test_name: str, category: str) -> SysbenchIterationResult:
        result = SysbenchIterationResult(test_name=test_name, category=category, raw_output=content)
        
        # Regexes for parsing
        match_lat = re.search(r'95th percentile:\s+([\d.]+)', content)
        if match_lat:
            result.latency_95_ms = float(match_lat.group(1))
            
        match_events = re.search(r'total number of events:\s+(\d+)', content)
        if match_events:
            result.total_events = int(match_events.group(1))

        if category in ["cpu", "threads", "mutex"]:
            match_speed = re.search(r'events per second:\s+([\d.]+)', content)
            if match_speed:
                result.throughput = float(match_speed.group(1))
        elif category == "memory":
            match_speed = re.search(r'transferred \(([\d.]+)\s+MiB/sec\)', content)
            if match_speed:
                result.throughput = float(match_speed.group(1))
        elif category == "fileio":
            is_read = "read" in test_name
            pattern = r'read, MiB/s:\s+([\d.]+)' if is_read else r'written, MiB/s:\s+([\d.]+)'
            match_speed = re.search(pattern, content)
            if match_speed:
                result.throughput = float(match_speed.group(1))
                
        return result

class SysbenchBenchmark(BenchmarkBase):
    def __init__(self, name: str, config: Dict[str, Any], run_dir: Path):
        super().__init__(name, config, run_dir)
        self.telemetry_timestamp = ""
        self.iterations = max(self.config.get("iterations", 3), 3)
        self.tests_to_run = self.config.get("tests", ["sysbench_cpu_prime_single_test", "sysbench_cpu_prime_multi_test"])
        self.fileio_dir = self.config.get("fileio_dir", "/root/sysbench_io")

    def _get_sysbench_cmd_prefix(self) -> str:
        return self.config.get("command", "sysbench")

    def _build_command(self, test_id: str) -> str:
        """
        Dynamically constructs the execution command for a given test.
        It merges default parameters from benchmarks.yaml with CLI overrides,
        and constructs the shell syntax safely.
        """
        # 1. Fetch default parameters from yaml
        test_params = self.config.get("test_params", {}).get(test_id, {})
        
        # Determine category (fallback to parsing if not specified)
        category = test_params.get("category", "")
        if not category:
            parsed = test_id[len("sysbench_"):] if test_id.startswith("sysbench_") else test_id
            category = parsed.split('_')[0]

        # 2. Extract and merge overrides
        overrides = self.config.get("overrides", {})
        
        merged_params = {}
        for k, v in test_params.items():
            if k != "category":
                merged_params[k] = v
                
        for k, v in overrides.items():
            merged_params[k] = v

        # 3. Construct argument string
        arg_strings = []
        for k, v in merged_params.items():
            if v == "true" or v is True:
                arg_strings.append(k)
            elif v == "false" or v is False:
                # Boolean-off flags are omitted entirely rather than
                # serialized as "k=False"/"k=false", which sysbench would
                # otherwise receive as a literal (and invalid) argument.
                continue
            else:
                arg_strings.append(f"{k}={v}")

        args_str = " ".join(arg_strings)
        
        # Determine sysbench action
        if test_id.endswith("_prepare"):
            action = "prepare"
        elif test_id.endswith("_cleanup"):
            action = "cleanup"
        else:
            action = "run"
            
        sysbench_cmd = self._get_sysbench_cmd_prefix()
        raw_cmd = f"{sysbench_cmd} {category} {args_str} {action}".strip()

        # Prepend directory context if it is a fileio benchmark
        if category == "fileio":
            if test_id == "sysbench_fileio_prepare":
                return f"mkdir -p {self.fileio_dir} && cd {self.fileio_dir} && {raw_cmd}"
            else:
                return f"cd {self.fileio_dir} && {raw_cmd}"
                
        return raw_cmd

    def setup(self, serial_executor, adb_manager) -> None:
        phase_logger.info("Setting up Sysbench benchmark on device...")
        
        # Prepare loosely (cleanup tmp files)
        adb_manager.execute_shell_command("rm -f /tmp/*_output.txt")
        
        if self.config.get('collect_telemetry', False):
            self.telemetry_timestamp = setup_telemetry(adb_manager)

    def _clear_cache(self, adb_manager):
        phase_logger.info("Purging cache memory (drop_caches)...")
        adb_manager.execute_shell_command("sync && echo 3 > /proc/sys/vm/drop_caches")

    # --- Dedicated Stateful File I/O Methods ---

    def sysbench_fileio_prepare(self, serial_executor):
        cmd = self._build_command("sysbench_fileio_prepare")
        phase_logger.info(f"Running dedicated preparation state: sysbench_fileio_prepare (command: {cmd})")
        serial_executor.execute_command(cmd, timeout_override=0)

    def sysbench_fileio_cleanup(self, serial_executor):
        cmd = self._build_command("sysbench_fileio_cleanup")
        phase_logger.info(f"Running dedicated cleanup state: sysbench_fileio_cleanup (command: {cmd})")
        serial_executor.execute_command(cmd, timeout_override=0)
        # Directory cleanup is highly recommended
        serial_executor.execute_command(f"rm -rf {self.fileio_dir}", timeout_override=0)

    def sysbench_fileio_seq_write_test(self, serial_executor) -> str:
        cmd = self._build_command("sysbench_fileio_seq_write_test")
        return serial_executor.execute_command(cmd, timeout_override=0)

    def sysbench_fileio_seq_read_test(self, serial_executor) -> str:
        cmd = self._build_command("sysbench_fileio_seq_read_test")
        return serial_executor.execute_command(cmd, timeout_override=0)

    def sysbench_fileio_random_write_test(self, serial_executor) -> str:
        cmd = self._build_command("sysbench_fileio_random_write_test")
        return serial_executor.execute_command(cmd, timeout_override=0)

    def sysbench_fileio_random_read_test(self, serial_executor) -> str:
        cmd = self._build_command("sysbench_fileio_random_read_test")
        return serial_executor.execute_command(cmd, timeout_override=0)

    def sysbench_fileio_random_mixed_test(self, serial_executor) -> str:
        cmd = self._build_command("sysbench_fileio_random_mixed_test")
        return serial_executor.execute_command(cmd, timeout_override=0)

    # --- Run Loop ---

    def run(self, serial_executor, adb_manager) -> Dict[str, Any]:
        test_params_config = self.config.get("test_params", {})
        
        stateless_tests = [t for t in self.tests_to_run if test_params_config.get(t, {}).get("category") != "fileio"]
        stateful_tests = [t for t in self.tests_to_run if test_params_config.get(t, {}).get("category") == "fileio"]

        # Capture raw outputs
        test_raw_logs: Dict[str, List[str]] = {t: [] for t in self.tests_to_run}
        parsed_results: Dict[str, List[SysbenchIterationResult]] = {t: [] for t in self.tests_to_run}
        
        # 1. Execute Stateless benchmarks
        for iteration in range(1, self.iterations + 1):
            if stateless_tests:
                phase_logger.info(f"--- Stateless Iteration {iteration}/{self.iterations} ---")
            for test_id in stateless_tests:
                if 'memory' in test_id:
                    self._clear_cache(adb_manager)
                    
                cmd = self._build_command(test_id)
                phase_logger.info(f"Running stateless benchmark: {test_id}")
                
                output = serial_executor.execute_command(cmd, timeout_override=0)
                test_raw_logs[test_id].append(output)
                
                parsed = SysbenchParser.parse_block(output, test_id)
                parsed_results[test_id].append(parsed)
                phase_logger.info(f"Parsed {test_id} throughput: {parsed.throughput:.2f}")

        # 2. Execute Stateful File I/O benchmarks if requested
        if stateful_tests:
            for iteration in range(1, self.iterations + 1):
                phase_logger.info(f"--- Stateful Iteration {iteration}/{self.iterations} ---")

                self.sysbench_fileio_prepare(serial_executor)
                try:
                    for test_id in stateful_tests:
                        self._clear_cache(adb_manager)
                        
                        phase_logger.info(f"Running stateful benchmark: {test_id}")
                        if hasattr(self, test_id):
                            method = getattr(self, test_id)
                            output = method(serial_executor)
                        else:
                            # Fallback if somehow not defined as method
                            cmd = self._build_command(test_id)
                            output = serial_executor.execute_command(cmd, timeout_override=0)
                            
                        test_raw_logs[test_id].append(output)
                        
                        parsed = SysbenchParser.parse_block(output, test_id)
                        parsed_results[test_id].append(parsed)
                        phase_logger.info(f"Parsed {test_id} throughput: {parsed.throughput:.2f}")
                finally:
                    self.sysbench_fileio_cleanup(serial_executor)

        # Write outputs to self.run_dir/logs for triage
        logs_dir = self.run_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        
        for test_id, raw_outs in test_raw_logs.items():
            parsed_id = test_id
            if parsed_id.startswith("sysbench_"):
                parsed_id = parsed_id[len("sysbench_"):]
            category = parsed_id.split('_')[0]
            
            log_file = logs_dir / f"{category}_output.txt"
            with open(log_file, "a", encoding="utf-8") as f:
                for idx, out in enumerate(raw_outs):
                    f.write(f"\n=== sysbench {test_id} - Iteration {idx+1} ===\n")
                    f.write(out)

        # Format metrics structure
        now_local = datetime.now()
        timestamp_display = now_local.strftime("%Y-%m-%d %H:%M:%S")
        os_info = adb_manager.get_os_release_info()

        # Structure results per sub-test
        formatted_tests = {}
        for test_id, res_list in parsed_results.items():
            raw_iterations = []
            for r in res_list:
                it_dict = asdict(r)
                # outlier_detector expects specific keys
                it_dict["cpu_events_per_sec"] = r.throughput
                it_dict["latency_p95_ms"] = r.latency_95_ms
                raw_iterations.append(it_dict)
                
            outlier_discarded_count = 0
            outlier_discarded_metrics = {}
            outlier_details = []
            warmup_discarded_count = 0
            method = "median_pct"
            
            # Use all iterations for analysis (warm-up feature removed)
            analysis_iterations = raw_iterations
            
            if len(analysis_iterations) >= 3:
                try:
                    detector = OutlierDetectorRegistry.get("sysbench")
                    out = detector.run_detection(
                        analysis_iterations,
                        n_iterations=len(analysis_iterations),
                        min_iterations=2,
                        benchmark_variant=test_id,
                        run_id=self.telemetry_timestamp
                    )
                    clean_iterations = out.get("clean_iterations", analysis_iterations)
                    outlier_discarded_count = len(out.get("discarded_indices", []))
                    outlier_discarded_metrics = out.get("discarded_metrics", {})
                    method = out.get("detection_method", "median_pct")
                    
                    # Extract detailed outlier info
                    if outlier_discarded_count > 0:
                        # outlier detector ran on analysis_iterations
                        working = analysis_iterations
                        
                        # Calculate median for deviation info
                        median_throughput = statistics.median([it.get("cpu_events_per_sec", 0.0) for it in clean_iterations]) if clean_iterations else 0.0
                        
                        for idx_str, metrics_list in outlier_discarded_metrics.items():
                            idx = int(idx_str)
                            if idx < len(working):
                                flagged_iteration = working[idx]
                                actual_throughput = flagged_iteration.get("cpu_events_per_sec", 0.0)
                                deviation_pct = (abs(actual_throughput - median_throughput) / median_throughput * 100) if median_throughput > 0 else 0.0
                                
                                outlier_details.append({
                                    "iteration_index": idx + 1, # +1 for 0-index
                                    "flagged_metrics": metrics_list,
                                    "values": {
                                        "cpu_events_per_sec": float(actual_throughput),
                                        "latency_min_ms": float(flagged_iteration.get("latency_min_ms", 0.0)),
                                        "latency_avg_ms": float(flagged_iteration.get("latency_avg_ms", 0.0)),
                                        "latency_p95_ms": float(flagged_iteration.get("latency_p95_ms", 0.0)),
                                        "latency_max_ms": float(flagged_iteration.get("latency_max_ms", 0.0))
                                    },
                                    "detection_method": method,
                                    "explanation": generate_outlier_explanation(metrics_list, deviation_pct, method)
                                })
                                
                                # Mark the outlier in original list for template
                                analysis_iterations[idx]["is_outlier"] = True
                except Exception as e:
                    phase_logger.warning(f"Outlier detection failed or unstable for {test_id}: {e}")
                    clean_iterations = analysis_iterations
            else:
                clean_iterations = analysis_iterations
                
            # Keep existing keys for backward compatibility and add all new category-specific metrics
            category = raw_iterations[0].get("category", "") if raw_iterations else ""
            
            test_metrics = {
                "category": category,
                "warmup_discarded": warmup_discarded_count,
                "outlier_discarded": outlier_discarded_count,
                "outlier_discarded_metrics": outlier_discarded_metrics,
                "outlier_details": outlier_details,
                "throughput": [it.get("cpu_events_per_sec", 0.0) for it in clean_iterations],
                "total_time_sec": [it.get("total_time_sec", 0.0) for it in clean_iterations],
                "latency_95": [it.get("latency_p95_ms", 0.0) for it in clean_iterations],
                "latency_avg": [it.get("latency_avg_ms", 0.0) for it in clean_iterations],
                "latency_min": [it.get("latency_min_ms", 0.0) for it in clean_iterations],
                "latency_max": [it.get("latency_max_ms", 0.0) for it in clean_iterations],
                "event_fairness_stddev": [it.get("events_stddev", 0.0) for it in clean_iterations],
                "event_fairness_avg": [it.get("events_avg", 0.0) for it in clean_iterations],
                "execution_time_fairness_stddev": [it.get("execution_time_stddev_sec", 0.0) for it in clean_iterations],
                "execution_time_fairness_avg": [it.get("execution_time_avg_sec", 0.0) for it in clean_iterations],
                "iterations": raw_iterations # Pass all iterations (including warmup/outlier) for report display
            }
            
            # Add specific metrics based on category
            if category == "memory":
                test_metrics["operations_per_sec"] = [it.get("operations_per_sec", 0.0) for it in clean_iterations]
                test_metrics["data_transferred_mib"] = [it.get("data_transferred_mib", 0.0) for it in clean_iterations]
            elif category == "fileio":
                test_metrics["read_mib_sec"] = [it.get("read_mib_sec", 0.0) for it in clean_iterations]
                test_metrics["write_mib_sec"] = [it.get("write_mib_sec", 0.0) for it in clean_iterations]
                
            formatted_tests[test_id] = test_metrics

        # Calculate maximum discards across all tests for global metadata
        # (Assuming all tests ran with same initial iteration count)
        retained_counts = [len(t_data.get("iterations", [])) for t_data in formatted_tests.values()]
        retained_iterations = max(retained_counts) if retained_counts else self.iterations
        
        total_warmup_discarded = 0
        
        # We calculate the max outlier discards across tests to represent worst-case
        max_outlier_discarded = max((t_data.get("outlier_discarded", 0) for t_data in formatted_tests.values()), default=0)

        metrics = {
            "metadata": {
                "timestamp_utc": timestamp_display,
                "os_pretty_name": os_info.get("pretty_name", "Unknown"),
                "os_build_id": os_info.get("build_id", "Unknown"),
                "iterations_run": retained_iterations,
                "total_iterations_executed": self.iterations,
                "warmup_iterations_discarded": total_warmup_discarded,
                "outlier_iterations_discarded": max_outlier_discarded,
                "benchmark_name": "sysbench"
            },
            "tests": formatted_tests
        }
        return metrics

    def teardown(self, serial_executor, adb_manager) -> None:
        teardown_telemetry(adb_manager, self.run_dir, self.telemetry_timestamp)

BENCHMARK_CLASS = SysbenchBenchmark

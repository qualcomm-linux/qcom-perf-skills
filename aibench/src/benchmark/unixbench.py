import json
import re
from pathlib import Path
from typing import Dict, Any, List

from src.benchmark.base import BenchmarkBase
from src.utils.logger import phase_logger
from src.utils.serial_executor import SerialCommandExecutor
from src.utils.telemetry_helpers import setup_telemetry, teardown_telemetry

class UnixBench(BenchmarkBase):
    """
    Executes UnixBench (BYTE UNIX Benchmarks) on target devices.
    Focuses on OS/Kernel/Scheduler performance.
    """

    def __init__(self, name, config, run_dir):
        super().__init__(name, config, run_dir)
        self.telemetry_timestamp = ""

    def setup(self, serial_executor, adb_manager) -> None:
        phase_logger.info("Setting up UnixBench...")
        # Check if UnixBench directory exists
        out = serial_executor.execute_command("ls -d /usr/share/unixbench")
        if "No such file or directory" in out:
            phase_logger.error("UnixBench directory /usr/share/unixbench not found on target.")

        if self.config.get('collect_telemetry', False):
            self.telemetry_timestamp = setup_telemetry(adb_manager)

    def _parse_unixbench_output(self, output: str) -> Dict[str, float]:
        """
        Parses standard UnixBench output to extract index scores.
        Looks for the 'System Benchmarks Index Values' table.
        """
        metrics = {}
        
        # Parse individual metrics
        # Example line: Dhrystone 2 using register variables         116700.0  337711645.2  28938.4
        in_index_section = False
        
        lines = output.strip().splitlines()
        for line in lines:
            line = line.strip()
            
            if "System Benchmarks Index Score" in line:
                # E.g., System Benchmarks Index Score                                        8414.3
                try:
                    score_str = line.split()[-1]
                    metrics["System Benchmarks Index Score"] = float(score_str)
                except ValueError:
                    pass
                continue
                
            if "System Benchmarks Index Values" in line:
                in_index_section = True
                continue
                
            if in_index_section:
                if not line or line.startswith("====="):
                    continue
                
                # Match metric name and the three columns (BASELINE, RESULT, INDEX)
                # Since names can have spaces, we can split by multiple spaces, or just look for the last 3 tokens
                parts = line.split()
                if len(parts) >= 4:
                    try:
                        # The last token is the INDEX score we care about
                        index_score = float(parts[-1])
                        # The metric name is everything before the last 3 tokens
                        metric_name = " ".join(parts[:-3])
                        
                        # Normalize metric name for JSON keys
                        clean_name = re.sub(r'[^a-zA-Z0-9_]', '_', metric_name).lower()
                        clean_name = re.sub(r'_+', '_', clean_name).strip('_')
                        
                        metrics[clean_name] = index_score
                    except ValueError:
                        pass
                        
        return metrics

    def run(self, serial_executor, adb_manager) -> Dict[str, Any]:
        phase_logger.info("Executing UnixBench...")
        
        tests = {}

        # We need self.results to be returned. We'll build it now.
        results = {"metadata": {"benchmark_name": self.name}, "tests": {}}
        iterations = self.config.get("iterations", 1)
        successful_iterations = 0
        
        for iteration in range(1, iterations + 1):
            phase_logger.info(f"--- UnixBench Iteration {iteration}/{iterations} ---")
            
            # Run Single Core
            phase_logger.info("Running Single Core (-c 1)...")
            cmd_single = "cd /usr/share/unixbench && ./Run -c 1"
            out_single = serial_executor.execute_command(cmd_single, timeout_override=2400) # Give it 40 mins
            
            single_metrics = self._parse_unixbench_output(out_single)
            
            # Log raw output
            log_dir = self.run_dir / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            with open(log_dir / f"unixbench_single_iter_{iteration}.log", "w", encoding="utf-8") as f:
                f.write(out_single)
                
            if "System Benchmarks Index Score" not in single_metrics:
                phase_logger.error("Failed to parse single-core System Benchmarks Index Score.")
                continue
                
            single_score = single_metrics.pop("System Benchmarks Index Score")
                
            # Run Multi Core
            phase_logger.info("Running Multi Core (-c $(nproc))...")
            cmd_multi = "cd /usr/share/unixbench && ./Run -c $(nproc)"
            out_multi = serial_executor.execute_command(cmd_multi, timeout_override=2400)
            
            multi_metrics = self._parse_unixbench_output(out_multi)
            
            with open(log_dir / f"unixbench_multi_iter_{iteration}.log", "w", encoding="utf-8") as f:
                f.write(out_multi)
                
            if "System Benchmarks Index Score" not in multi_metrics:
                phase_logger.error("Failed to parse multi-core System Benchmarks Index Score.")
                continue
                
            multi_score = multi_metrics.pop("System Benchmarks Index Score")
            
            # Fetch nproc to calculate scaling efficiency
            out_nproc = serial_executor.execute_command("nproc")
            try:
                nproc = int(out_nproc.strip())
            except ValueError:
                nproc = 1
                phase_logger.warning("Could not determine nproc, defaulting to 1 for scaling calculation.")
                
            if nproc > 0 and single_score > 0:
                scaling_efficiency = (multi_score / single_score) / nproc * 100.0
            else:
                scaling_efficiency = 0.0

            successful_iterations += 1

            phase_logger.info(f"Iteration {iteration} Results:")
            phase_logger.info(f"  Single-Core Score: {single_score}")
            phase_logger.info(f"  Multi-Core Score: {multi_score}")
            phase_logger.info(f"  Scaling Efficiency: {scaling_efficiency:.2f}% (nproc={nproc})")
            
            # Store single core results
            if "unixbench_single_core" not in tests:
                tests["unixbench_single_core"] = {"metrics": {}}
                
            # Add single core metrics (running average if multiple iterations, though usually 1)
            for m_name, m_val in single_metrics.items():
                if m_name not in tests["unixbench_single_core"]["metrics"]:
                    tests["unixbench_single_core"]["metrics"][m_name] = m_val
                else:
                    tests["unixbench_single_core"]["metrics"][m_name] += m_val
                    
            # We treat the overall index score as a metric too, for regression detection
            if "index_score" not in tests["unixbench_single_core"]["metrics"]:
                tests["unixbench_single_core"]["metrics"]["index_score"] = single_score
            else:
                tests["unixbench_single_core"]["metrics"]["index_score"] += single_score
                
            # Store multi core results
            if "unixbench_multi_core" not in tests:
                tests["unixbench_multi_core"] = {"metrics": {}}
                
            for m_name, m_val in multi_metrics.items():
                if m_name not in tests["unixbench_multi_core"]["metrics"]:
                    tests["unixbench_multi_core"]["metrics"][m_name] = m_val
                else:
                    tests["unixbench_multi_core"]["metrics"][m_name] += m_val
                    
            if "index_score" not in tests["unixbench_multi_core"]["metrics"]:
                tests["unixbench_multi_core"]["metrics"]["index_score"] = multi_score
            else:
                tests["unixbench_multi_core"]["metrics"]["index_score"] += multi_score
                
            # Store scaling results
            if "unixbench_scaling" not in tests:
                tests["unixbench_scaling"] = {"throughput": []}
            tests["unixbench_scaling"]["throughput"].append(scaling_efficiency)
            
        # Average out the metrics using the count of iterations that actually
        # produced parseable scores for BOTH single and multi core runs --
        # dividing by the configured `iterations` would silently deflate the
        # average whenever any iteration's output failed to parse.
        if successful_iterations > 1 and "unixbench_single_core" in tests:
            for m_name in tests["unixbench_single_core"]["metrics"]:
                tests["unixbench_single_core"]["metrics"][m_name] /= successful_iterations
            for m_name in tests["unixbench_multi_core"]["metrics"]:
                tests["unixbench_multi_core"]["metrics"][m_name] /= successful_iterations
                
        results["tests"] = tests
        return results

    def teardown(self, serial_executor, adb_manager) -> None:
        phase_logger.info("Tearing down UnixBench...")
        teardown_telemetry(adb_manager, self.run_dir, self.telemetry_timestamp)

BENCHMARK_CLASS = UnixBench

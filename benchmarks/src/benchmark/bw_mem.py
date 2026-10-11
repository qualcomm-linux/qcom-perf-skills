import math
import re
from pathlib import Path
from statistics import median
from typing import Dict, Any, List, Optional, Tuple

from src.benchmark.base import BenchmarkBase
from src.utils.logger import phase_logger
from src.utils.telemetry_helpers import setup_telemetry, teardown_telemetry

class BwMem(BenchmarkBase):
    """
    Executes bw_mem memory bandwidth benchmark.
    Iterates over varying worker counts to detect bandwidth plateau.
    """

    def __init__(self, name, config, run_dir):
        super().__init__(name, config, run_dir)
        self.telemetry_timestamp = ""

    def setup(self, serial_executor, adb_manager) -> None:
        phase_logger.info("Setting up bw_mem benchmark...")
        # Check if bw_mem binary exists
        out = serial_executor.execute_command("ls /usr/bin/bw_mem")
        if "No such file or directory" in out:
            phase_logger.error("bw_mem binary /usr/bin/bw_mem not found on target.")

        if self.config.get('collect_telemetry', False):
            self.telemetry_timestamp = setup_telemetry(adb_manager)

    def detect_plateau(
        self,
        bandwidth_dict: Dict[int, float],
        thresholds: Dict[str, float]
    ) -> Dict[str, Any]:
        """
        Detect a sustained memory-bandwidth plateau.

        Parameters
        ----------
        bandwidth_dict:
            Mapping of worker count to measured bandwidth in GB/s.

        thresholds:
            Supported keys:
            consecutive_gain_pct, overall_gain_pct, collapse_threshold_pct,
            regression_tolerance_pct, plateau_spread_pct, min_plateau_points
        """
        default_result: Dict[str, Any] = {
            "plateau": 0.0,
            "peak_observed": 0.0,
            "raw_peak_observed": 0.0,
            "saturation_worker": None,
            "plateau_range": None,
            "plateau_detected": False,
            "anomaly": None,
            "collapse_worker": None,
            "valid_worker_range": None,
            "gains_pct": {},
            "plateau_spread_pct": None,
            "reason": "No valid bandwidth data was provided.",
        }

        if not bandwidth_dict:
            return default_result

        valid_items: List[Tuple[int, float]] = []

        for worker, bandwidth in bandwidth_dict.items():
            try:
                worker_value = int(worker)
                bandwidth_value = float(bandwidth)
            except (TypeError, ValueError):
                continue

            if worker_value <= 0:
                continue

            if bandwidth_value <= 0 or not math.isfinite(bandwidth_value):
                continue

            valid_items.append((worker_value, bandwidth_value))

        valid_items.sort(key=lambda item: item[0])

        if not valid_items:
            return default_result

        workers = [item[0] for item in valid_items]
        bandwidths = [item[1] for item in valid_items]

        consecutive_gain_pct = float(thresholds.get("consecutive_gain_pct", 5.0))
        overall_gain_pct = float(thresholds.get("overall_gain_pct", 2.0))
        collapse_threshold_pct = abs(float(thresholds.get("collapse_threshold_pct", 20.0)))
        regression_tolerance_pct = abs(float(thresholds.get("regression_tolerance_pct", 3.0)))
        plateau_spread_limit_pct = abs(float(thresholds.get("plateau_spread_pct", 5.0)))
        min_plateau_points = max(3, int(thresholds.get("min_plateau_points", 3)))

        result = default_result.copy()
        result["raw_peak_observed"] = max(bandwidths)
        result["peak_observed"] = max(bandwidths)
        result["plateau"] = max(bandwidths)
        result["valid_worker_range"] = f"{workers[0]}-{workers[-1]}"
        result["reason"] = "Insufficient evidence to establish a plateau."

        if len(workers) < 2:
            result["reason"] = "At least two workers are required to calculate scaling gains."
            return result

        all_gains = [
            ((bandwidths[index + 1] - bandwidths[index]) / bandwidths[index]) * 100.0
            for index in range(len(bandwidths) - 1)
        ]

        collapse_bandwidth_index: Optional[int] = None

        for gain_index, gain_pct in enumerate(all_gains):
            if gain_pct <= -collapse_threshold_pct:
                collapse_bandwidth_index = gain_index + 1
                result["anomaly"] = "bandwidth_collapse"
                result["collapse_worker"] = workers[collapse_bandwidth_index]
                break

        if collapse_bandwidth_index is not None:
            analysis_workers = workers[:collapse_bandwidth_index]
            analysis_bandwidths = bandwidths[:collapse_bandwidth_index]
        else:
            analysis_workers = workers
            analysis_bandwidths = bandwidths

        if not analysis_workers:
            result["reason"] = "The first usable scaling transition was a bandwidth collapse."
            return result

        result["valid_worker_range"] = f"{analysis_workers[0]}-{analysis_workers[-1]}"
        result["peak_observed"] = max(analysis_bandwidths)
        result["plateau"] = max(analysis_bandwidths)

        if len(analysis_workers) < min_plateau_points:
            result["reason"] = (
                f"Only {len(analysis_workers)} valid pre-collapse samples were "
                f"available; at least {min_plateau_points} are required."
            )
            return result

        analysis_gains = [
            ((analysis_bandwidths[index + 1] - analysis_bandwidths[index]) / analysis_bandwidths[index]) * 100.0
            for index in range(len(analysis_bandwidths) - 1)
        ]

        result["gains_pct"] = {
            f"{analysis_workers[index]}->{analysis_workers[index + 1]}": analysis_gains[index]
            for index in range(len(analysis_gains))
        }

        plateau_start_index: Optional[int] = None

        for start_index in range(0, len(analysis_bandwidths) - min_plateau_points + 1):
            plateau_bandwidths = analysis_bandwidths[start_index:]
            plateau_workers = analysis_workers[start_index:]
            plateau_gains = analysis_gains[start_index:]

            if len(plateau_bandwidths) < min_plateau_points:
                continue

            if len(plateau_gains) < min_plateau_points - 1:
                continue

            gain_envelope_is_stable = all(
                -regression_tolerance_pct <= gain_pct <= consecutive_gain_pct
                for gain_pct in plateau_gains
            )

            if not gain_envelope_is_stable:
                continue

            strict_low_gain_count = sum(
                1 for gain_pct in plateau_gains if abs(gain_pct) <= overall_gain_pct
            )

            has_strict_support = strict_low_gain_count >= 2

            if not has_strict_support:
                continue

            plateau_median = median(plateau_bandwidths)

            plateau_spread_pct = (
                (max(plateau_bandwidths) - min(plateau_bandwidths)) / plateau_median
            ) * 100.0

            if plateau_spread_pct > plateau_spread_limit_pct:
                continue

            plateau_near_peak_pct = (
                (result["peak_observed"] - plateau_median) / result["peak_observed"]
            ) * 100.0

            if plateau_near_peak_pct > plateau_spread_limit_pct:
                continue

            plateau_start_index = start_index
            break

        if plateau_start_index is None:
            if result["anomaly"] == "bandwidth_collapse":
                result["reason"] = (
                    "A bandwidth collapse was detected, but the valid "
                    "pre-collapse region did not contain enough stable samples "
                    "to establish a plateau."
                )
            else:
                result["reason"] = (
                    "Bandwidth did not contain a stable region satisfying the "
                    "configured plateau thresholds."
                )
            return result

        final_plateau_workers = analysis_workers[plateau_start_index:]
        final_plateau_bandwidths = analysis_bandwidths[plateau_start_index:]
        final_plateau_median = median(final_plateau_bandwidths)

        final_plateau_spread_pct = (
            (max(final_plateau_bandwidths) - min(final_plateau_bandwidths)) / final_plateau_median
        ) * 100.0

        result.update({
            "plateau": final_plateau_median,
            "saturation_worker": final_plateau_workers[0],
            "plateau_range": f"{final_plateau_workers[0]}-{final_plateau_workers[-1]}",
            "plateau_detected": True,
            "plateau_spread_pct": final_plateau_spread_pct,
            "reason": (
                f"Bandwidth remained stable from "
                f"{final_plateau_workers[0]} through "
                f"{final_plateau_workers[-1]} workers."
            ),
        })

        return result

    def run(self, serial_executor, adb_manager) -> Dict[str, Any]:
        phase_logger.info("Executing bw_mem...")
        
        results = {"metadata": {"benchmark_name": self.name}, "tests": {}}
        
        # Parse configuration
        iterations = self.config.get("iterations", 1)
        mem_size = self.config.get("memory_size", "3G")
        worker_start = self.config.get("worker_start", 1)
        
        # Determine worker_end (parse $(nproc) if specified)
        worker_end_conf = str(self.config.get("worker_end", "$(nproc)"))
        if worker_end_conf == "$(nproc)":
            out_nproc = serial_executor.execute_command("nproc")
            try:
                worker_end = int(out_nproc.strip())
            except ValueError:
                worker_end = 8
                phase_logger.warning("Could not determine nproc, defaulting to 8.")
        else:
            try:
                worker_end = int(worker_end_conf)
            except ValueError:
                worker_end = 8
                
        plateau_thresholds = self.config.get("plateau_thresholds", {
            "consecutive_gain_pct": 5.0,
            "overall_gain_pct": 2.0,
            "collapse_threshold_pct": 20.0,
            "regression_tolerance_pct": 3.0,
            "plateau_spread_pct": 5.0,
            "min_plateau_points": 3
        })
        
        # Determine which operations to run
        configured_operations = self.config.get("operations", ["rd", "wr", "cp", "rdwr", "frd", "fwr"])
        tests_requested = self.config.get("tests", [])
        
        operations_to_run = []
        if tests_requested:
            # Check if specific tests were requested via --tests argument
            for t in tests_requested:
                op_name = t.replace("bw_mem_", "")
                if op_name in configured_operations:
                    operations_to_run.append(op_name)
                    
            if not operations_to_run:
                phase_logger.warning("No valid bw_mem operations requested in --tests. Running all.")
                operations_to_run = configured_operations
        else:
            operations_to_run = configured_operations
            
        phase_logger.info(f"Running bw_mem operations: {operations_to_run}")
        phase_logger.info(f"Worker range: {worker_start} to {worker_end}, Size: {mem_size}")

        for iteration in range(1, iterations + 1):
            phase_logger.info(f"--- bw_mem Iteration {iteration}/{iterations} ---")
            iteration_results = {}
            
            for op in operations_to_run:
                phase_logger.info(f"Executing operation: {op}")
                bandwidth_data = {}
                
                for workers in range(worker_start, worker_end + 1):
                    # Use 2>&1 because lmbench tools often write to stderr
                    cmd = f"/usr/bin/bw_mem -P {workers} {mem_size} {op} 2>&1"
                    phase_logger.info(f"  Workers: {workers}")
                    
                    try:
                        # Use a large timeout (3600s) to let it finish without hitting the default 15s/60s timeouts
                        out = serial_executor.execute_command(cmd, timeout_override=3600)
                    except Exception as e:
                        phase_logger.error(f"    Execution failed or timed out for workers={workers}: {e}")
                        break
                        
                    # Log raw output
                    log_dir = self.run_dir / "logs"
                    log_dir.mkdir(parents=True, exist_ok=True)
                    with open(log_dir / f"bw_mem_{op}_worker_{workers}.log", "w", encoding="utf-8") as f:
                        f.write(out)
                    
                    # Parse output
                    # Looking for: <size> <bandwidth>
                    # Example: 3000.00 6519.46
                    bw_mbps = 0.0
                    for line in out.splitlines():
                        line = line.strip()
                        if not line or line.startswith("real") or line.startswith("user") or line.startswith("sys"):
                            continue
                        
                        parts = line.split()
                        if len(parts) >= 2:
                            try:
                                # Both size and bandwidth should be floats
                                size_val = float(parts[0])
                                bw_mbps = float(parts[1])
                                break # Found the bandwidth line
                            except ValueError:
                                pass
                                
                    if bw_mbps > 0:
                        bw_gbps = bw_mbps / 1024.0
                        bandwidth_data[workers] = round(bw_gbps, 2)
                        phase_logger.info(f"    Bandwidth: {bw_gbps:.2f} GB/s")
                    else:
                        snippet = (out[:100] + '...') if len(out) > 100 else out
                        phase_logger.warning(f"    Failed to parse bandwidth for workers={workers}. Output: {snippet}")
                
                # Detect plateau for this operation
                plateau_info = self.detect_plateau(bandwidth_data, plateau_thresholds)
                
                iteration_results[op] = {
                    "plateau": plateau_info["plateau"],
                    "unit": "GB/sec",
                    "saturation_worker": plateau_info["saturation_worker"],
                    "plateau_range": plateau_info["plateau_range"],
                    "plateau_detected": plateau_info["plateau_detected"],
                    "plateau_analysis": plateau_info
                }
                
                if plateau_info.get("anomaly"):
                    iteration_results[op]["anomaly"] = plateau_info["anomaly"]

                if plateau_info["plateau_detected"]:
                    phase_logger.info(
                        f"  Operation '{op}': sustained plateau "
                        f"{plateau_info['plateau']:.2f} GB/s, "
                        f"saturation at P={plateau_info['saturation_worker']}, "
                        f"range={plateau_info['plateau_range']}."
                    )
                else:
                    phase_logger.info(
                        f"  Operation '{op}': no supported plateau detected; "
                        f"peak valid bandwidth="
                        f"{plateau_info['peak_observed']:.2f} GB/s."
                    )

                if plateau_info.get("anomaly") == "bandwidth_collapse":
                    phase_logger.warning(
                        f"  Operation '{op}': bandwidth collapse at "
                        f"P={plateau_info['collapse_worker']}; "
                        f"analysis used P={plateau_info['valid_worker_range']}."
                    )

                phase_logger.info(f"  Operation '{op}': {plateau_info['reason']}")
                    
            results["tests"][f"iteration_{iteration}"] = iteration_results
            
        return results

    def teardown(self, serial_executor, adb_manager) -> None:
        phase_logger.info("Tearing down bw_mem...")
        teardown_telemetry(adb_manager, self.run_dir, self.telemetry_timestamp)

BENCHMARK_CLASS = BwMem

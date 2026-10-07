"""
aggregator.py - Aggregate results across multiple runs of a build
Produces build_analysis.json and updates global build history.

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import json
import statistics
from pathlib import Path
from typing import Any, Dict, List
from src.utils.logger import phase_logger

def aggregate_build_runs(output_dir: Path, benchmark_name: str, build_id: str) -> Dict[str, Any]:
    """
    Scans all runs of a build, aggregates metrics, calculates mean/stddev/min/max/median,
    and writes build_analysis.json inside the build folder.
    """
    build_dir = Path(output_dir) / benchmark_name / f"build_{build_id}"
    if not build_dir.exists():
        phase_logger.warning(f"Build directory does not exist: {build_dir}")
        return {}

    run_results: List[Dict[str, Any]] = []
    for run_path in build_dir.glob("run_*"):
        if run_path.is_dir():
            res_file = run_path / "results.json"
            if res_file.exists():
                try:
                    with open(res_file, "r", encoding="utf-8") as f:
                        run_results.append(json.load(f))
                except Exception as e:
                    phase_logger.error(f"Error loading {res_file}: {e}")

    if not run_results:
        phase_logger.warning(f"No valid results.json files found for build {build_id}")
        return {}

    # Gather numeric metrics across runs
    aggregated_metrics: Dict[str, List[float]] = {}
    
    # Each benchmark has a slightly different results schema
    for result in run_results:
        # Support both "benchmark_name" (new) and "benchmark" (legacy) keys
        metadata = result.get("metadata", {})
        b_name = metadata.get("benchmark_name", "") or metadata.get("benchmark", "")
        
        # Check if unixbench
        if b_name == "unixbench":
            tests_dict = result.get("tests", {})
            if "unixbench_single_core" in tests_dict:
                idx = tests_dict["unixbench_single_core"].get("metrics", {}).get("index_score")
                if idx is not None:
                    aggregated_metrics.setdefault("unixbench_single_core", []).append(idx)
            if "unixbench_multi_core" in tests_dict:
                idx = tests_dict["unixbench_multi_core"].get("metrics", {}).get("index_score")
                if idx is not None:
                    aggregated_metrics.setdefault("unixbench_multi_core", []).append(idx)
            if "unixbench_scaling" in tests_dict:
                tp_list = tests_dict["unixbench_scaling"].get("throughput", [])
                aggregated_metrics.setdefault("unixbench_scaling", []).extend(tp_list)
                
        # Check if bw_mem
        elif b_name == "bw_mem":
            tests_dict = result.get("tests", {})
            for iteration_key, iteration_data in tests_dict.items():
                if isinstance(iteration_data, dict):
                    for operation, op_data in iteration_data.items():
                        if isinstance(op_data, dict) and "plateau" in op_data:
                            plateau_val = op_data.get("plateau")
                            if plateau_val is not None:
                                metric_key = f"bw_mem_{operation}_plateau"
                                aggregated_metrics.setdefault(metric_key, []).append(plateau_val)
                            
                            peak_val = op_data.get("plateau_analysis", {}).get("peak_observed")
                            if peak_val is not None:
                                metric_key_peak = f"bw_mem_{operation}_peak_observed"
                                aggregated_metrics.setdefault(metric_key_peak, []).append(peak_val)

        # Check if lat_mem_rd
        elif b_name == "lat_mem_rd":
            tests_dict = result.get("tests", {})
            for test_name, test_data in tests_dict.items():
                if not isinstance(test_data, dict):
                    continue
                overall_plateau = test_data.get("overall_plateau_latency_ns")
                if overall_plateau is not None:
                    aggregated_metrics.setdefault(f"{test_name}_overall_plateau_ns", []).append(overall_plateau)

                spread_pct = test_data.get("iteration_to_iteration_spread_pct")
                if spread_pct is not None:
                    aggregated_metrics.setdefault(f"{test_name}_iter_spread_pct", []).append(spread_pct)

                # Store individual per-iteration plateau values (p1, p2, p3, ...)
                # positionally so the dashboard tooltip can display them.
                per_iter_plateaus = test_data.get("per_iteration_plateau_ns", [])
                for idx, plateau_val in enumerate(per_iter_plateaus, start=1):
                    aggregated_metrics.setdefault(f"{test_name}_iter{idx}_plateau_ns", []).append(plateau_val)

        # Geekbench (single-core and multi-core scores) - CHECK BEFORE GENERIC HANDLER
        elif b_name == "geekbench":
            tests_dict = result.get("tests", {})
            for test_name, test_data in tests_dict.items():
                if not isinstance(test_data, dict):
                    continue
                # Extract single-core and multi-core scores.
                # Keys must be {test_name}_single_core / {test_name}_multi_core
                # (i.e. geekbench_cpu_single_core / geekbench_cpu_multi_core) to
                # match the dashboard template's table_config entries.
                sc_scores = [s for s in test_data.get("single_core_scores", []) if s is not None]
                mc_scores = [s for s in test_data.get("multi_core_scores", []) if s is not None]

                if sc_scores:
                    aggregated_metrics.setdefault(f"{test_name}_single_core", []).extend(sc_scores)
                if mc_scores:
                    aggregated_metrics.setdefault(f"{test_name}_multi_core", []).extend(mc_scores)

        # Check if sysbench or generic test fallback
        elif b_name == "sysbench" or "tests" in result:
            tests_dict = result.get("tests", {})
            for test_name, test_data in tests_dict.items():
                # Legacy aggregation mapping
                tp_list = test_data.get("throughput", [])
                
                # Fallback to raw iterations if outlier detection discarded all iterations
                if not tp_list and "iterations" in test_data:
                    tp_list = [it.get("cpu_events_per_sec") for it in test_data["iterations"] if it.get("cpu_events_per_sec") is not None]
                    
                aggregated_metrics.setdefault(test_name, []).extend(tp_list)
                
                # New metric aggregation (if fields exist)
                metrics_to_aggregate = [
                    "latency_95", "latency_avg", "latency_min", "latency_max",
                    "event_fairness_stddev", "event_fairness_avg",
                    "execution_time_fairness_stddev", "execution_time_fairness_avg",
                    "operations_per_sec", "data_transferred_mib",
                    "read_mib_sec", "write_mib_sec"
                ]
                
                for metric in metrics_to_aggregate:
                    if metric in test_data:
                        aggregated_metrics.setdefault(f"{test_name}_{metric}", []).extend(test_data[metric])
                        
        # Check if tiobench
        elif b_name == "tiobench":
            # New structure: top-level test types like "sequential", "random"
            for key, val in result.items():
                if key == "metadata": continue
                
                if isinstance(val, dict) and "average_bandwidth" in val:
                    w_rate = val["average_bandwidth"].get("write_rate_mbs", 0.0)
                    aggregated_metrics.setdefault(f"{key}_write_rate", []).append(w_rate)
                    r_rate = val["average_bandwidth"].get("read_rate_mbs", 0.0)
                    aggregated_metrics.setdefault(f"{key}_read_rate", []).append(r_rate)
                # Fallback for old structure just in case
                elif key == "results" and isinstance(val, dict):
                    for block_size, block_data in val.items():
                        perf = block_data.get("performance", {})
                        w_rate = perf.get("write_rate_mbs", 0.0)
                        aggregated_metrics.setdefault(f"write_rate_{block_size}", []).append(w_rate)
                        r_rate = perf.get("read_rate_mbs", 0.0)
                        aggregated_metrics.setdefault(f"read_rate_{block_size}", []).append(r_rate)

        # Coremark has no dedicated schema -- its results.json has a top-level
        # "tests" dict (e.g. {"coremark_default": {"throughput": [...]}}), so it
        # is correctly handled by the "tests" in result generic fallback above,
        # which aggregates per-test-id keys (e.g. "coremark_default") matching
        # what the dashboard/Excel templates expect.

    # Calculate summary statistics
    analysis_stats: Dict[str, Dict[str, float]] = {}
    for metric_name, values in aggregated_metrics.items():
        if not values:
            continue
        stddev = statistics.stdev(values) if len(values) > 1 else 0.0
        analysis_stats[metric_name] = {
            "mean": statistics.mean(values),
            "median": statistics.median(values),
            "min": min(values),
            "max": max(values),
            "stddev": stddev,
            "cv": (stddev / statistics.mean(values)) if statistics.mean(values) > 0 else 0.0
        }

    # Format the build analysis artifact
    analysis_payload = {
        "metadata": {
            "benchmark_name": benchmark_name,
            "build_id": build_id,
            "total_runs_aggregated": len(run_results),
            "aggregated_at": datetime_str()
        },
        "statistics": analysis_stats
    }

    analysis_file = build_dir / "build_analysis.json"
    with open(analysis_file, "w", encoding="utf-8") as f:
        json.dump(analysis_payload, f, indent=2)
        
    phase_logger.info(f"Build analysis stats written to {analysis_file}")
    
    # Update global build history in output/reports/build_history.json
    update_global_build_history(output_dir, analysis_payload)
    
    return analysis_payload

def update_global_build_history(output_dir: Path, analysis_payload: Dict[str, Any]):
    """Appends/updates the current build statistics in the reports build history."""
    reports_dir = Path(output_dir) / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    history_file = reports_dir / "build_history.json"

    history_data = []
    if history_file.exists():
        try:
            with open(history_file, "r", encoding="utf-8") as f:
                history_data = json.load(f)
        except Exception as e:
            # Do NOT silently reset to [] and overwrite below - that would
            # permanently destroy all prior build history on a transient
            # read/parse error. Log loudly and bail out, leaving the
            # existing (unreadable but intact) file untouched.
            phase_logger.error(
                f"Failed to load existing build history from {history_file}: {e}. "
                "Skipping history update to avoid overwriting existing data."
            )
            return

    # Replace entry if same build exists, otherwise append
    new_entry = analysis_payload
    updated = False
    for idx, entry in enumerate(history_data):
        meta = entry.get("metadata", {})
        new_meta = new_entry.get("metadata", {})
        if meta.get("build_id") == new_meta.get("build_id") and meta.get("benchmark_name") == new_meta.get("benchmark_name"):
            history_data[idx] = new_entry
            updated = True
            break
            
    if not updated:
        history_data.append(new_entry)

    with open(history_file, "w", encoding="utf-8") as f:
        json.dump(history_data, f, indent=2)
    phase_logger.info(f"Global build history updated in {history_file}")

def datetime_str() -> str:
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
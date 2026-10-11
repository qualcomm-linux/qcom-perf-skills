"""
metrics_extractor.py - Extracts flat {metric_name: [value_per_iteration, ...]}
dicts from a single benchmark run's results.json.

This mirrors the per-benchmark parsing branches in src/reporting/aggregator.py
(which aggregates ACROSS multiple runs of a build) but operates on a SINGLE
run's results.json, preserving per-iteration granularity so the
regression-detection-and-rca pipeline can perform iteration-level (Tier 1)
comparisons within one run, in addition to run-level/build-level comparisons
that reuse build_analysis.json's already-aggregated statistics.

Kept intentionally independent from aggregator.py (rather than refactoring
it to share code) to avoid introducing any risk of regressing the existing,
tested build_analysis.json/dashboard pipeline while this skill is being
introduced.

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

from typing import Any, Dict, List


def extract_iteration_metrics(results: Dict[str, Any]) -> Dict[str, List[float]]:
    """
    Given a single run's results.json content, returns
    {metric_name: [value_iter1, value_iter2, ...]} for every metric this
    benchmark type is known to expose with per-iteration granularity.

    Benchmarks without meaningful per-iteration values (e.g. single-shot
    tests) will simply return single-element (or empty) lists for their
    metrics -- callers should treat lists of length < 2 as "no iteration-
    level comparison possible" rather than an error.
    """
    metrics: Dict[str, List[float]] = {}
    metadata = results.get("metadata", {})
    # Support both "benchmark_name" (new) and "benchmark" (legacy) keys,
    # matching aggregator.py's resolution.
    b_name = metadata.get("benchmark_name", "") or metadata.get("benchmark", "")

    if b_name == "unixbench":
        tests_dict = results.get("tests", {})
        if "unixbench_single_core" in tests_dict:
            idx = tests_dict["unixbench_single_core"].get("metrics", {}).get("index_score")
            if idx is not None:
                metrics.setdefault("unixbench_single_core", []).append(idx)
        if "unixbench_multi_core" in tests_dict:
            idx = tests_dict["unixbench_multi_core"].get("metrics", {}).get("index_score")
            if idx is not None:
                metrics.setdefault("unixbench_multi_core", []).append(idx)
        if "unixbench_scaling" in tests_dict:
            tp_list = tests_dict["unixbench_scaling"].get("throughput", [])
            metrics.setdefault("unixbench_scaling", []).extend(tp_list)

    elif b_name == "bw_mem":
        tests_dict = results.get("tests", {})
        for iteration_key, iteration_data in tests_dict.items():
            if isinstance(iteration_data, dict):
                for operation, op_data in iteration_data.items():
                    if isinstance(op_data, dict) and "plateau" in op_data:
                        plateau_val = op_data.get("plateau")
                        if plateau_val is not None:
                            metrics.setdefault(f"bw_mem_{operation}_plateau", []).append(plateau_val)
                        peak_val = op_data.get("plateau_analysis", {}).get("peak_observed")
                        if peak_val is not None:
                            metrics.setdefault(f"bw_mem_{operation}_peak_observed", []).append(peak_val)

    elif b_name == "lat_mem_rd":
        tests_dict = results.get("tests", {})
        for test_name, test_data in tests_dict.items():
            if not isinstance(test_data, dict):
                continue
            overall_plateau = test_data.get("overall_plateau_latency_ns")
            if overall_plateau is not None:
                metrics.setdefault(f"{test_name}_overall_plateau_ns", []).append(overall_plateau)
            per_iter_plateaus = test_data.get("per_iteration_plateau_ns", [])
            for idx, plateau_val in enumerate(per_iter_plateaus, start=1):
                metrics.setdefault(f"{test_name}_iter{idx}_plateau_ns", []).append(plateau_val)
            spread_pct = test_data.get("iteration_to_iteration_spread_pct")
            if spread_pct is not None:
                metrics.setdefault(f"{test_name}_iter_spread_pct", []).append(spread_pct)

    elif b_name == "tiobench":
        for key, val in results.items():
            if key == "metadata":
                continue
            if not isinstance(val, dict):
                continue
            # tiobench's results.json has no "per_iteration_bandwidth" field --
            # per-iteration write/read rates live under val["iterations"][i]["block_sizes"],
            # averaged across block sizes the same way the benchmark itself averages
            # its "average_bandwidth" summary (see src/benchmark/tiobench.py).
            for iter_data in val.get("iterations", []):
                block_sizes = iter_data.get("block_sizes", {}) if isinstance(iter_data, dict) else {}
                w_rates = [
                    b["performance"]["write_rate_mbs"] for b in block_sizes.values()
                    if isinstance(b, dict) and "write_rate_mbs" in b.get("performance", {})
                ]
                r_rates = [
                    b["performance"]["read_rate_mbs"] for b in block_sizes.values()
                    if isinstance(b, dict) and "read_rate_mbs" in b.get("performance", {})
                ]
                if w_rates:
                    metrics.setdefault(f"{key}_write_rate", []).append(sum(w_rates) / len(w_rates))
                if r_rates:
                    metrics.setdefault(f"{key}_read_rate", []).append(sum(r_rates) / len(r_rates))


    elif b_name == "geekbench":
        tests_dict = results.get("tests", {})
        for test_name, test_data in tests_dict.items():
            if not isinstance(test_data, dict):
                continue
            # Extract single-core and multi-core scores (mirrors aggregator.py).
            # Keys must be {test_name}_single_core / {test_name}_multi_core to
            # match the dashboard template's table_config entries.
            # Filter out None values defensively — geekbench.py defaults failed
            # parses to 0.0, but guard here prevents downstream statistics.mean()
            # TypeError if the schema ever changes.
            sc_scores = [s for s in test_data.get("single_core_scores", []) if s is not None]
            mc_scores = [s for s in test_data.get("multi_core_scores", []) if s is not None]

            if sc_scores:
                metrics.setdefault(f"{test_name}_single_core", []).extend(sc_scores)
            if mc_scores:
                metrics.setdefault(f"{test_name}_multi_core", []).extend(mc_scores)

    # Note: coremark has no dedicated branch here -- its results.json has a
    # top-level "tests" dict (e.g. {"coremark_default": {"throughput": [...]}}),
    # so it is correctly handled by the "tests" in results generic fallback
    # below, which extracts per-test-id keys (e.g. "coremark_default").

    elif b_name == "sysbench" or "tests" in results:
        tests_dict = results.get("tests", {})
        for test_name, test_data in tests_dict.items():
            tp_list = test_data.get("throughput", [])
            if not tp_list and "iterations" in test_data:
                tp_list = [it.get("cpu_events_per_sec") for it in test_data["iterations"] if it.get("cpu_events_per_sec") is not None]
            if tp_list:
                metrics.setdefault(test_name, []).extend(tp_list)

            extra_metric_names = [
                "latency_95", "latency_avg", "latency_min", "latency_max",
                "event_fairness_stddev", "event_fairness_avg",
                "execution_time_fairness_stddev", "execution_time_fairness_avg",
                "operations_per_sec", "data_transferred_mib",
                "read_mib_sec", "write_mib_sec"
            ]
            for metric in extra_metric_names:
                if metric in test_data and isinstance(test_data[metric], list):
                    metrics.setdefault(f"{test_name}_{metric}", []).extend(test_data[metric])

    return metrics
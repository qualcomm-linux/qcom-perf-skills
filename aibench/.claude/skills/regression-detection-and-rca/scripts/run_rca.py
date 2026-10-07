"""
run_rca.py - Main orchestrator for the regression-detection-and-rca skill.

Implements the 3-tier automatic regression detection described in the
skill's design (no explicit invocation needed -- this is called by main.py
right after every single benchmark run completes):

  Tier 1 (Run-level): A single build with multiple suite runs already
      present on disk. Compares br1 vs br2 vs br3 (i.e. the most-recent
      run's aggregated stats vs the previous run's aggregated stats, both
      within the same build).

  Tier 2 (Build-level): Multiple builds present on disk for this benchmark.
      Compares b1rN vs b2rN (same run-index N) across the two most recent
      builds, in addition to whatever Tier 1 comparisons apply within the
      current build.

  Tier 3 (Trend-level): Multiple runs on disk (>=4). Uses CUSUM and 
      Mann-Kendall to detect sustained shifts or monotonic degrading trends.

  Explicit baseline comparison: If the user has previously stored a named
  baseline (see baseline_manager.py) for this benchmark, it is ALWAYS
  compared against as well, regardless of which tier(s) above also fired.

All applicable tiers run every time (they are not mutually exclusive) --
e.g. a benchmark with 3 iterations, 2 runs, and 2 builds on disk will get
Tier 1 + Tier 2 + Tier 3 + baseline (if stored) comparisons, each producing
its own regression/RCA entries in rca_report.json.

Any missing telemetry file is a WARNING (not a fatal error) per project
requirements -- these warnings are collected into the report's
"telemetry_warnings" list for HTML display.

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import json
import statistics
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Allow running this script directly (python run_rca.py ...) or importing it
# as part of main.py's lifecycle, from either the aibench/ cwd or this
# skill's scripts/ folder.
_THIS_DIR = Path(__file__).resolve().parent
_BENCHMARKS_ROOT = _THIS_DIR.parent.parent.parent.parent  # .../benchmarks
if str(_BENCHMARKS_ROOT) not in sys.path:
    sys.path.insert(0, str(_BENCHMARKS_ROOT))
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from src.reporting.regression_detector import RegressionDetector
from src.reporting.rca_detector import RCADetector
from src.reporting.telemetry_parser import TelemetryParser

import telemetry_thresholds
import baseline_manager
import metrics_extractor
from ai_skill_client import call_ai_skill, AISkillError


def _stats_from_values(values: List[float]) -> Dict[str, float]:
    if not values:
        return {"mean": 0.0, "stddev": 0.0}
    mean = statistics.mean(values)
    stddev = statistics.stdev(values) if len(values) > 1 else 0.0
    return {"mean": mean, "stddev": stddev}


def _resolve_direction(metric_name: str, bench_config: Optional[Dict[str, Any]]) -> str:
    """
    Resolves whether a higher or lower value is "better" for a given metric.

    Resolution order (most specific wins):
      1. An explicit per-metric override in the benchmark's yaml
         `metric_config` dict (e.g. sysbench's per-submetric map).
      2. The benchmark's top-level `metric_direction` (higher/lower), when
         it's not "mixed"/missing.
      3. "higher" (the historical default, applied to every existing caller
         that predates direction-awareness).
    """
    if not bench_config:
        return "higher"
    metric_config = bench_config.get("metric_config", {}) or {}
    if metric_name in metric_config and metric_config[metric_name] in ("higher", "lower"):
        return metric_config[metric_name]
    direction = bench_config.get("metric_direction")
    return direction if direction in ("higher", "lower") else "higher"


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        # File exists but failed to read/parse -- distinct from "missing",
        # and worth surfacing since callers otherwise treat this identically
        # to a simple missing-file case and silently skip the comparison.
        print(f"[RCA] WARNING: {path} exists but could not be parsed ({e}); treating as missing.")
        return None


def _validate_regression_schema(data: Any) -> None:
    if not isinstance(data, dict):
        raise AISkillError("AI regression result was not a JSON object")
    for metric_name, result in data.items():
        if not isinstance(result, dict) or "throughput_regression" not in result or "latency_regression" not in result:
            raise AISkillError(f"AI regression result for '{metric_name}' is missing required keys")


def _validate_rca_schema(data: Any) -> None:
    if not isinstance(data, dict):
        raise AISkillError("AI RCA result was not a JSON object")
    for metric_name, result in data.items():
        if not isinstance(result, dict) or "cause" not in result or "confidence" not in result:
            raise AISkillError(f"AI RCA result for '{metric_name}' is missing required keys")


def _generate_rca_with_ai_fallback(regressions: Dict[str, Any], anomalies: Dict[str, Any], use_ai_skill: bool) -> Dict[str, Any]:
    if use_ai_skill:
        try:
            ai_rca = call_ai_skill("rca_detector.md", {"regressions": regressions, "anomalies": anomalies})
            _validate_rca_schema(ai_rca)
            return ai_rca
        except AISkillError as e:
            print(f"[RCA] AI RCA failed ({e}); falling back to Python RCADetector.")
    return RCADetector.generate_rca(regressions, anomalies)


def _ai_regression_payload(
    baseline_stats: Dict[str, Dict[str, float]],
    current_stats: Dict[str, Dict[str, float]],
    metric_directions: Optional[Dict[str, str]],
    baseline_raw: Optional[Dict[str, List[float]]],
    current_raw: Optional[Dict[str, List[float]]],
) -> Dict[str, Any]:
    return {
        "baseline_stats": baseline_stats,
        "current_stats": current_stats,
        "metric_directions": metric_directions or {},
        "baseline_raw": baseline_raw or {},
        "current_raw": current_raw or {},
    }


def _compare_and_rca(
    comparison_label: str,
    baseline_stats: Dict[str, Dict[str, float]],
    current_stats: Dict[str, Dict[str, float]],
    detector: RegressionDetector,
    anomalies: Dict[str, Any],
    skip_rca: bool = False,
    metric_directions: Optional[Dict[str, str]] = None,
    use_ai_skill: bool = False,
    baseline_raw: Optional[Dict[str, List[float]]] = None,
    current_raw: Optional[Dict[str, List[float]]] = None,
) -> Dict[str, Any]:
    """
    Runs RegressionDetector across every metric present in both
    baseline_stats and current_stats, then RCADetector for any regressions
    found. Returns a dict shaped for inclusion in rca_report.json's
    "comparisons" list.

    `metric_directions`, when provided, maps metric_name -> "higher"/"lower"
    so lower-is-better metrics (latency, fairness stddev, etc.) aren't
    flagged as regressions when they improve. Defaults to None, which
    preserves the historical "higher is better for everything" behavior.

    `use_ai_skill`, when True, attempts the AI-driven regression_detector.md /
    rca_detector.md Chain-of-Thought skills first (via the local AI CLI),
    falling back to the deterministic Python engine on any failure or
    schema mismatch. Defaults to False, which preserves the historical
    Python-only behavior exactly.
    """
    regressions: Dict[str, Any] = {}

    ai_regressions = None
    if use_ai_skill:
        try:
            payload = _ai_regression_payload(baseline_stats, current_stats, metric_directions, baseline_raw, current_raw)
            ai_regressions = call_ai_skill("regression_detector.md", payload)
            _validate_regression_schema(ai_regressions)
        except AISkillError as e:
            print(f"[RCA] AI regression detection failed ({e}); falling back to Python detector.")
            ai_regressions = None

    if ai_regressions is not None:
        regressions = ai_regressions
    else:
        common_metrics = [m for m in current_stats if m in baseline_stats]
        batch_baseline = {m: baseline_stats[m] for m in common_metrics}
        batch_current = {m: current_stats[m] for m in common_metrics}
        batch_directions = {m: (metric_directions or {}).get(m, "higher") for m in common_metrics}
        regressions = detector.detect_regressions_batch(batch_baseline, batch_current, batch_directions)

    rca_out = {}
    if not skip_rca and regressions:
        rca_out = _generate_rca_with_ai_fallback(regressions, anomalies, use_ai_skill)

    has_regression = any(
        r.get("throughput_regression") or r.get("latency_regression")
        for r in regressions.values()
    )

    return {
        "label": comparison_label,
        "regression_detected": has_regression,
        "regressions": regressions,
        "rca": rca_out,
    }


def _re_run_benchmark(
    run_dir: Path,
    original_run_dir: Path,
    benchmark_name: str,
    serial_executor: Any,
    adb_manager: Any,
    bench_config: Dict[str, Any],
    tier: int
) -> bool:
    """
    Helper to execute a benchmark again in a new run directory with specific telemetry enabled.
    """
    from src.benchmark.factory import get_benchmark
    from src.reporting.individual import write_json_results
    import time
    
    # We only want one iteration for RCA reruns to save time, unless configured otherwise
    rca_config = bench_config.copy()
    
    # Setup telemetry based on tier
    if tier == 1:
        # Tier 1: Lightweight telemetry
        rca_config["collect_telemetry"] = True
        rca_config["telemetry_tier"] = 1
    elif tier == 2:
        # Tier 2: Tier 1 + ftrace
        rca_config["collect_telemetry"] = True
        rca_config["telemetry_tier"] = 2

    # Tell start_telemetry_device.sh (via an on-device marker it reads once
    # and deletes) whether to skip ftrace for this specific re-run, so Tier 1
    # actually stays at its documented lightweight (<2% overhead) profile
    # instead of always collecting ftrace regardless of tier.
    if adb_manager is not None:
        try:
            if tier == 1:
                adb_manager.execute_shell_command("touch /root/telemetry_tier1_only")
            else:
                # Defensive: clear any stale marker so a Tier 2+ re-run never
                # inherits a leftover Tier-1-only marker from an earlier,
                # possibly-interrupted re-run.
                adb_manager.execute_shell_command("rm -f /root/telemetry_tier1_only")
        except Exception as e:
            print(f"[RCA Tier {tier}] Could not set telemetry tier marker on device (non-fatal): {e}")

    try:
        runner = get_benchmark(benchmark_name, rca_config, run_dir)
        results = runner.execute_lifecycle(serial_executor, adb_manager)
        write_json_results(results, run_dir)
        
        # Give system time to cool down/settle after a diagnostic run
        time.sleep(30)
        return True
    except Exception as e:
        print(f"[RCA Tier {tier}] Failed to re-run benchmark {benchmark_name}: {e}")
        return False

def run_rca_for_run(
    output_dir: Path,
    benchmark_name: str,
    build_id: str,
    run_dir: Path,
    config: Dict[str, Any],
    baseline_tag: Optional[str] = None,
    rca_all_runs: bool = False,
    rca_all_iterations: bool = False,
    rca_mode: str = "smart",  # "report", "full", "smart"
    serial_executor: Any = None,
    adb_manager: Any = None,
    bench_config: Dict[str, Any] = None,
    use_ai_skill: bool = False,
) -> Dict[str, Any]:
    """
    Entry point called by main.py immediately after a single suite run's
    execute_lifecycle() + write_json_results() + aggregate_build_runs()
    have completed for `run_dir`.

    Writes <run_dir>/rca_report.json and returns its content.

    `use_ai_skill`, when True, routes regression detection and RCA through
    the AI-driven Chain-of-Thought skills first, falling back to the
    deterministic Python engine on any failure. Defaults to False.
    """
    output_dir = Path(output_dir)
    run_dir = Path(run_dir)
    bench_dir = output_dir / benchmark_name
    build_dir = bench_dir / f"build_{build_id}"

    thresholds = telemetry_thresholds.load_thresholds(config)
    detector = RegressionDetector.from_thresholds(thresholds)
    telemetry_parser = TelemetryParser(thresholds=thresholds)

    def _directions_for(names) -> Dict[str, str]:
        return {n: _resolve_direction(n, bench_config) for n in names}

    report: Dict[str, Any] = {
        "benchmark": benchmark_name,
        "build_id": build_id,
        "run_id": run_dir.name,
        "device_codename": thresholds.get("codename"),
        "used_fallback_thresholds": thresholds.get("_used_fallback", True),
        "comparisons": [],
        "telemetry_warnings": [],
    }

    skip_rca = (rca_mode == "report")
    smart_rca = (rca_mode == "smart")
    
    # Check if we have executors for smart RCA re-runs
    can_rerun = serial_executor is not None and bench_config is not None
    if smart_rca and not can_rerun:
        report["telemetry_warnings"].append("Smart RCA requested but executors not provided. Falling back to parsing existing logs.")
        smart_rca = False

    # ------------------------------------------------------------------
    # Parse telemetry anomalies for THIS run (used by every comparison's RCA)
    # ------------------------------------------------------------------
    logs_dir = run_dir / "logs"
    anomalies: Dict[str, Any] = {}
    
    # If in full RCA mode, or smart RCA mode but we can't re-run, just parse existing logs
    if not smart_rca or not can_rerun:
        if logs_dir.exists():
            anomalies = telemetry_parser.parse_anomalies(str(logs_dir))
            report["telemetry_warnings"].extend(anomalies.get("warnings", []))
        else:
            if not skip_rca:
                report["telemetry_warnings"].append(
                    f"No logs/ directory found for this run ({logs_dir}) -- all telemetry-based RCA skipped for this run."
                )

    current_results = _load_json(run_dir / "results.json")
    if current_results is None:
        report["telemetry_warnings"].append(
            f"Could not load this run's own results.json ({run_dir / 'results.json'}) -- metrics-based regression/RCA will be skipped for this run."
        )
        current_results = {}

    # ------------------------------------------------------------------
    # Extract iteration metrics for use in run/build comparisons
    # ------------------------------------------------------------------
    iter_metrics = metrics_extractor.extract_iteration_metrics(current_results)

    try:
        # ------------------------------------------------------------------
        # Tier 1: Run-level (this build's most recent 2 runs, if >1 exist)
        # ------------------------------------------------------------------
        run_dirs = sorted([d for d in build_dir.glob("run_*") if d.is_dir()])
    
        # Process run-level comparisons
        if len(run_dirs) > 1:
            current_run_idx = -1
            try:
                current_run_idx = run_dirs.index(run_dir)
            except ValueError:
                current_run_idx = len(run_dirs) - 1
            
            if current_run_idx > 0:
                # If rca_all_runs is true, compare current against ALL previous runs
                # Otherwise, just compare against the immediately preceding run
                start_idx = 0 if rca_all_runs else max(0, current_run_idx - 1)
            
                for prev_idx in range(start_idx, current_run_idx):
                    prev_run_dir = run_dirs[prev_idx]
                    prev_results = _load_json(prev_run_dir / "results.json")
                    if prev_results:
                        prev_metrics = metrics_extractor.extract_iteration_metrics(prev_results)
                        baseline_stats = {k: _stats_from_values(v) for k, v in prev_metrics.items() if v}
                        current_stats = {k: _stats_from_values(v) for k, v in iter_metrics.items() if v}
                        cmp_result = _compare_and_rca(
                            f"run-level: {prev_run_dir.name} vs {run_dir.name}",
                            baseline_stats, current_stats, detector, anomalies, skip_rca=True,
                            metric_directions=_directions_for(set(baseline_stats) | set(current_stats)),
                            use_ai_skill=use_ai_skill, baseline_raw=prev_metrics, current_raw=iter_metrics
                        )
                        report["comparisons"].append(cmp_result)
                    else:
                        report["telemetry_warnings"].append(
                            f"Could not load previous run's results.json ({prev_run_dir}) for run-level comparison."
                        )
            
                # ------------------------------------------------------------------
                # Trend Analysis (if rca_all_runs and >=4 runs exist)
                # ------------------------------------------------------------------
                if rca_all_runs and current_run_idx >= 3:
                    # We have at least 4 runs (idx 0, 1, 2, 3), and we are at the 4th or later
                    # Import trend detector
                    try:
                        from src.reporting.trend_detector import TrendDetector
                        trend_detector = TrendDetector()
                    
                        # Collect metrics across all runs up to current
                        all_run_metrics = {}
                        runs_processed = []
                    
                        for idx in range(0, current_run_idx + 1):
                            r_dir = run_dirs[idx]
                            r_res = _load_json(r_dir / "results.json")
                            if r_res:
                                runs_processed.append(r_dir.name)
                                r_mets = metrics_extractor.extract_iteration_metrics(r_res)
                                for k, v in r_mets.items():
                                    if v:
                                        if k not in all_run_metrics:
                                            all_run_metrics[k] = []
                                        # Use mean of iteration values for this run
                                        all_run_metrics[k].append(statistics.mean(v))
                                    
                        if len(runs_processed) >= 4:
                            trend_regressions = {}
                            for metric_name, run_values in all_run_metrics.items():
                                if len(run_values) >= 4:
                                    metric_direction = _resolve_direction(metric_name, bench_config)
                                    is_lower_better = (metric_direction == "lower")
                                    trend_res = trend_detector.detect_trends(run_values, direction=metric_direction)
                                    if trend_res.get("trend_detected"):
                                        # Format for rca generator
                                        delta = trend_res.get("delta_percent", 0.0)
                                        trend_regressions[metric_name] = {
                                            "throughput_regression": not is_lower_better,
                                            "latency_regression": is_lower_better,
                                            "metrics": {
                                                "throughput_delta_percent": 0.0 if is_lower_better else delta,
                                                "latency_delta_percent": delta if is_lower_better else 0.0
                                            },
                                            "anomalies": [f"Degrading trend detected across {len(runs_processed)} runs. Type: {trend_res.get('trend_type')}"]
                                        }

                            if trend_regressions:
                                # Generate RCA for trends
                                trend_rca = RCADetector.generate_rca(trend_regressions, anomalies) if not skip_rca else {}
                                report["comparisons"].append({
                                    "label": f"trend-level: across {len(runs_processed)} runs ({runs_processed[0]} to {runs_processed[-1]})",
                                    "regression_detected": True,
                                    "regressions": trend_regressions,
                                    "rca": trend_rca,
                                })
                    except ImportError as e:
                        report["telemetry_warnings"].append(f"Trend detector not available for multi-run analysis: {e}")

        # ------------------------------------------------------------------
        # Tier 2: Build-level (same run-index across the 2 most recent builds)
        # ------------------------------------------------------------------
        build_dirs = sorted([d for d in bench_dir.glob("build_*") if d.is_dir()])
        if len(build_dirs) > 1:
            current_run_index = run_dirs.index(run_dir) if run_dir in run_dirs else len(run_dirs) - 1
            prev_build_dir = build_dirs[-2] if build_dirs[-1] == build_dir else build_dirs[-1]
            if prev_build_dir != build_dir:
                prev_build_run_dirs = sorted([d for d in prev_build_dir.glob("run_*") if d.is_dir()])
                if current_run_index < len(prev_build_run_dirs):
                    prev_build_run_dir = prev_build_run_dirs[current_run_index]
                    prev_build_results = _load_json(prev_build_run_dir / "results.json")
                    if prev_build_results:
                        prev_build_metrics = metrics_extractor.extract_iteration_metrics(prev_build_results)
                        baseline_stats = {k: _stats_from_values(v) for k, v in prev_build_metrics.items() if v}
                        current_stats = {k: _stats_from_values(v) for k, v in iter_metrics.items() if v}
                        cmp_result = _compare_and_rca(
                            f"build-level: {prev_build_dir.name}/{prev_build_run_dir.name} vs {build_dir.name}/{run_dir.name}",
                            baseline_stats, current_stats, detector, anomalies, skip_rca=True,
                            metric_directions=_directions_for(set(baseline_stats) | set(current_stats)),
                            use_ai_skill=use_ai_skill, baseline_raw=prev_build_metrics, current_raw=iter_metrics
                        )
                        report["comparisons"].append(cmp_result)
                    else:
                        report["telemetry_warnings"].append(
                            f"Could not load previous build's matching run results.json ({prev_build_run_dir}) for build-level comparison."
                        )
                else:
                    report["telemetry_warnings"].append(
                        f"Previous build {prev_build_dir.name} does not have a run at index {current_run_index} -- build-level comparison skipped."
                    )

        # ------------------------------------------------------------------
        # Explicit stored baseline comparison (if one exists for this benchmark)
        # ------------------------------------------------------------------
        tag = baseline_tag or baseline_manager.DEFAULT_TAG
        stored_baseline = baseline_manager.load_baseline(output_dir, benchmark_name, tag)
        if stored_baseline:
            baseline_stats = stored_baseline.get("statistics", {})
            current_stats = {k: _stats_from_values(v) for k, v in iter_metrics.items() if v}
            cmp_result = _compare_and_rca(
                f"baseline comparison: stored baseline (tag='{tag}', build={stored_baseline.get('metadata', {}).get('build_id', '?')}) vs current ({build_id}/{run_dir.name})",
                baseline_stats, current_stats, detector, anomalies, skip_rca=True,
                metric_directions=_directions_for(set(baseline_stats) | set(current_stats)),
                use_ai_skill=use_ai_skill, current_raw=iter_metrics
            )
            report["comparisons"].append(cmp_result)

        report["any_regression_detected"] = any(c["regression_detected"] for c in report["comparisons"])
    
        # ------------------------------------------------------------------
        # Smart RCA: If regressions detected and in smart mode, re-run with telemetry
        # ------------------------------------------------------------------
        if smart_rca and can_rerun and report["any_regression_detected"]:
            # Find which metrics regressed
            regressed_metrics = []
            for cmp in report["comparisons"]:
                if cmp.get("regression_detected"):
                    for m_name, m_data in cmp.get("regressions", {}).items():
                        if m_data.get("throughput_regression") or m_data.get("latency_regression"):
                            if m_name not in regressed_metrics:
                                regressed_metrics.append(m_name)
                            
            if regressed_metrics:
                print(f"[Smart RCA] Regressions detected in {len(regressed_metrics)} metrics. Initiating Tier 1 diagnostic re-run...")
            
                # Create Tier 1 rerun directory (e.g. run_001.1)
                tier1_dir = run_dir.parent / f"{run_dir.name}.1"
                tier1_dir.mkdir(parents=True, exist_ok=True)
            
                # Execute Tier 1 re-run (vmstat, dmesg, thermal, cpufreq)
                success = _re_run_benchmark(tier1_dir, run_dir, benchmark_name, serial_executor, adb_manager, bench_config, 1)
            
                if success:
                    # Parse Tier 1 telemetry
                    t1_logs = tier1_dir / "logs"
                    if t1_logs.exists():
                        anomalies = telemetry_parser.parse_anomalies(str(t1_logs))
                    
                        # Re-generate RCA for all comparisons using this new telemetry
                        needs_tier2 = False
                    
                        for cmp in report["comparisons"]:
                            if cmp.get("regression_detected"):
                                cmp["rca"] = _generate_rca_with_ai_fallback(cmp["regressions"], anomalies, use_ai_skill)
                            
                                # Check if Tier 1 analysis is inconclusive (low confidence but has anomalies)
                                for m_rca in cmp["rca"].values():
                                    conf_str = m_rca.get("confidence", "0%")
                                    try:
                                        # Handle "85%" -> 85.0
                                        if isinstance(conf_str, str):
                                            conf_clean = conf_str.replace('%', '').strip()
                                            conf_num = float(conf_clean) if conf_clean else 0.0
                                        else:
                                            conf_num = float(conf_str)
                                    except (ValueError, TypeError):
                                        conf_num = 0.0
                                    
                                    if 0 < conf_num < 85: # Has some evidence but not conclusive
                                        needs_tier2 = True
                                    
                        # If Tier 1 was inconclusive, run Tier 2 (includes ftrace)
                        if needs_tier2:
                            print(f"[Smart RCA] Tier 1 analysis inconclusive. Initiating Tier 2 (ftrace) diagnostic re-run...")
                            tier2_dir = run_dir.parent / f"{run_dir.name}.2"
                            tier2_dir.mkdir(parents=True, exist_ok=True)
                        
                            t2_success = _re_run_benchmark(tier2_dir, run_dir, benchmark_name, serial_executor, adb_manager, bench_config, 2)
                        
                            if t2_success:
                                t2_logs = tier2_dir / "logs"
                                if t2_logs.exists():
                                    t2_anomalies = telemetry_parser.parse_anomalies(str(t2_logs))
                                    # Re-generate RCA with Tier 2 telemetry
                                    for cmp in report["comparisons"]:
                                        if cmp.get("regression_detected"):
                                            cmp["rca"] = _generate_rca_with_ai_fallback(cmp["regressions"], t2_anomalies, use_ai_skill)
                else:
                    report["telemetry_warnings"].append("Smart RCA Tier 1 re-run failed.")
        elif not skip_rca and not smart_rca:
            # Full RCA mode - already have anomalies from the original run
            for cmp in report["comparisons"]:
                if cmp.get("regression_detected"):
                    cmp["rca"] = _generate_rca_with_ai_fallback(cmp["regressions"], anomalies, use_ai_skill)
    except Exception as e:
        # A failure anywhere in the comparison pipeline above must not
        # discard comparisons that already succeeded -- surface it as a
        # warning and still fall through to writing whatever was
        # accumulated in `report` so far.
        report["telemetry_warnings"].append(
            f"RCA comparison pipeline hit an unexpected error and may be incomplete: {e}"
        )

    report_path = run_dir / "rca_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    return report


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run regression-detection-and-rca for a single run directory.")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--benchmark", required=True)
    parser.add_argument("--build-id", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--config", required=True, help="Path to benchmarks.yaml")
    parser.add_argument("--baseline-tag", default=None)
    parser.add_argument("--rca-all-runs", action="store_true")
    parser.add_argument("--rca-all-iterations", action="store_true")
    parser.add_argument("--rca-mode", type=str, default="smart", choices=["report", "full", "smart"])
    parser.add_argument("--ssh-connection", action="store_true", help="Connect via SSH (required for smart RCA re-runs via CLI if using SSH)")
    parser.add_argument("--default-connection", action="store_true", help="Connect via Serial/ADB (required for smart RCA re-runs via CLI if using ADB)")
    args = parser.parse_args()

    from src.utils.config_loader import load_yaml_config
    cfg = load_yaml_config(Path(args.config))
    
    # Establish connections for Smart RCA re-runs if requested
    serial_executor = None
    adb_manager = None
    conn = None
    
    # Only establish connection if smart mode is requested via CLI
    if args.rca_mode == "smart" and (args.ssh_connection or args.default_connection):
        import time
        if args.ssh_connection:
            from src.utils.ssh_manager import SshManager
            # SshManager will load credentials from credential_manager automatically
            ssh_manager = SshManager()
            try:
                ssh_manager.connect()
                ssh_manager.check_device_status()
                conn = ssh_manager
                adb_manager = ssh_manager
                serial_executor = ssh_manager
            except Exception as exc:
                print(f"Warning: Target connection via SSH failed ({exc}). Smart RCA re-runs will be disabled.")
        else:
            from src.utils.serial_connect import open_serial_connection, handle_login, send_cmd, close_connection
            from src.utils.adb_manager import AdbManager
            from src.utils.serial_executor import SerialCommandExecutor
            
            port = cfg.get("port", "COM7")
            baud = cfg.get("baud", 115200)
            
            try:
                conn = open_serial_connection(port, baud)
                if handle_login(conn):
                    send_cmd(conn, "touch /etc/usb-debugging-enabled")
                    send_cmd(conn, "systemctl start android-tools-adbd")
                    time.sleep(2)
                    adb_manager = AdbManager()
                    adb_manager.check_device_status()
                    serial_executor = SerialCommandExecutor(conn)
                else:
                    print("Warning: Serial login failed. Smart RCA re-runs disabled.")
            except Exception as exc:
                print(f"Warning: Target connection via Serial/ADB failed ({exc}). Smart RCA re-runs disabled.")

    try:
        bench_config = cfg.get("benchmarks", {}).get(args.benchmark, {})
        result = run_rca_for_run(
            Path(args.output_dir), args.benchmark, args.build_id, Path(args.run_dir), cfg,
            baseline_tag=args.baseline_tag,
            rca_all_runs=args.rca_all_runs,
            rca_all_iterations=args.rca_all_iterations,
            rca_mode=args.rca_mode,
            serial_executor=serial_executor,
            adb_manager=adb_manager,
            bench_config=bench_config
        )
        print(json.dumps(result, indent=2))
    finally:
        # Cleanup connections
        if conn:
            if args.ssh_connection:
                conn.close()
            else:
                from src.utils.serial_connect import close_connection
                close_connection(conn)

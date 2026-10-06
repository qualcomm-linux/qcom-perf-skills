"""
regression_detector.py - Statistically-rigorous build-over-build regression detector
Implements standard thresholds combined with Z-score significance filters.

Thresholds default to the historical hardcoded values below for full
backward compatibility, but can be sourced from config/benchmarks.yaml's
`telemetry_thresholds` section via `RegressionDetector.from_config()` (see
aibench/.claude/skills/regression-detection-and-rca/scripts/telemetry_thresholds.py),
enabling device/SoC-specific tuning without code changes.

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import json
import statistics
from typing import Any, Dict, List, Optional

class RegressionDetector:
    """
    Analyzes performance differences between a baseline build and a current build.
    Uses multi-method consensus (Median, Mann-Whitney, Quantiles, Cohen's d) 
    instead of Z-score, making it robust for non-Gaussian IIOT workloads.
    """
    def __init__(self, 
                 throughput_threshold: float = -0.05, 
                 latency_threshold: float = 0.10, 
                 stability_gate: float = 0.10, 
                 lat_abs_warn: float = 500, 
                 lat_abs_fail: float = 2000,
                 use_median: bool = True,
                 use_mann_whitney: bool = True,
                 use_cohens_d: bool = True,
                 use_quantile: bool = True,
                 consensus_threshold: int = 2,
                 cohens_d_threshold: float = 0.5,
                 max_outlier_fraction: float = 1.0 / 3.0,
                 fdr_alpha: float = 0.05):
        # Default: -5% for throughput, +10% for latency
        self.throughput_threshold = throughput_threshold
        self.latency_threshold = latency_threshold
        self.STABILITY_GATE = stability_gate
        self.LATENCY_ABSOLUTE_WARN = lat_abs_warn
        self.LATENCY_ABSOLUTE_FAIL = lat_abs_fail

        # New IIOT-optimized robust methods
        self.use_median = use_median
        self.use_mann_whitney = use_mann_whitney
        self.use_cohens_d = use_cohens_d
        self.use_quantile = use_quantile
        self.consensus_threshold = consensus_threshold
        self.cohens_d_threshold = cohens_d_threshold

        # Cap on the fraction of samples the MAD outlier filter may discard.
        # Beyond this, a "noisy" run is actually a sustained distribution
        # shift (e.g. thermal throttling for part of the run), not isolated
        # noise, so filtering is skipped entirely rather than erasing evidence.
        self.max_outlier_fraction = max_outlier_fraction

        # Significance level used for the Benjamini-Hochberg FDR correction
        # applied across a batch of metrics in detect_regressions_batch().
        self.fdr_alpha = fdr_alpha

    @classmethod
    def from_thresholds(cls, thresholds: Optional[Dict[str, Any]]) -> "RegressionDetector":
        """
        Constructs a RegressionDetector using a resolved device-threshold
        dict (as returned by telemetry_thresholds.load_thresholds()).
        Falls back to the class defaults for any missing keys, so a
        partially-specified `thresholds` dict is safe to pass.
        """
        if not thresholds:
            return cls()
        reg = thresholds.get("regression", {})
        return cls(
            throughput_threshold=reg.get("throughput_threshold_percent", -5) / 100.0,
            latency_threshold=reg.get("latency_threshold_percent", 10) / 100.0,
            stability_gate=reg.get("stability_gate_cv_percent", 10) / 100.0,
            lat_abs_warn=reg.get("latency_absolute_warn_ms", 500),
            lat_abs_fail=reg.get("latency_absolute_fail_ms", 2000),
            use_median=reg.get("use_median_for_comparison", True),
            use_mann_whitney=reg.get("use_mann_whitney", True),
            use_cohens_d=reg.get("use_cohens_d", True),
            use_quantile=reg.get("use_quantile", True),
            consensus_threshold=reg.get("consensus_threshold", 2),
            cohens_d_threshold=reg.get("cohens_d_threshold", 0.5),
            max_outlier_fraction=reg.get("max_outlier_fraction_percent", 33) / 100.0,
            fdr_alpha=reg.get("fdr_alpha", 0.05)
        )
        
    def _mann_whitney_pvalue(self, baseline_data: List[float], current_data: List[float]):
        """
        Computes the raw Mann-Whitney U p-value for a pair of samples,
        with no significance threshold applied. Used both by the
        single-metric `_detect_mann_whitney` helper (which applies the
        threshold) and by `detect_regressions_batch()`, which needs every
        metric's raw p-value - including ones that wouldn't be "significant"
        on their own - to rank them for the Benjamini-Hochberg correction.

        Returns (p_value, used_fallback, delta_percent):
          - p_value is a float when scipy is available and both samples
            have >= 2 points, else None (no real p-value to rank).
          - used_fallback is True when scipy is unavailable and the
            non-parametric ">=60% worse than baseline median" heuristic
            was used instead (that heuristic has no p-value, so it never
            participates in FDR correction).
          - delta_percent is the mean-based delta, for evidence/reporting.
        """
        if len(baseline_data) < 2 or len(current_data) < 2:
            return None, False, None
        try:
            from scipy import stats
            _, p_value = stats.mannwhitneyu(baseline_data, current_data, alternative='two-sided')
            baseline_mean = statistics.mean(baseline_data)
            current_mean = statistics.mean(current_data)
            delta = (current_mean - baseline_mean) / baseline_mean if baseline_mean > 0 else 0.0
            return p_value, False, delta * 100
        except ImportError:
            return None, True, None
        except Exception:
            return None, False, None

    def detect_regressions(self, baseline_metrics: Dict[str, Any], current_metrics: Dict[str, Any], test_name: str = "unknown", direction: str = "higher", _suppress_mann_whitney: bool = False) -> Dict[str, Any]:
        """
        Compares baseline and current metrics.

        `direction` indicates whether a higher or lower value is considered
        "better" for this metric. Defaults to "higher" (the historical
        assumption for every existing caller). When "lower", the throughput
        decision points are polarity-flipped so that an *increase* beyond
        the threshold is treated as the regression instead of a decrease.
        Raw deltas/means reported under result["metrics"] are unaffected by
        this flip - only the pass/fail decision is.

        Returns: {
            "test": test_name,
            "stability_valid": bool,
            "stability_reason": str,
            "throughput_regression": bool,
            "latency_regression": bool,
            "anomalies": [],
            "metrics": { ... }
        }
        """
        if direction not in ("higher", "lower"):
            direction = "higher"
        result = {
            "test": test_name,
            "stability_valid": True,
            "stability_reason": "",
            "throughput_regression": False,
            "latency_regression": False,
            "anomalies": [],
            "metrics": {},
            "outliers_detected": 0,
            "outlier_discarded_values": [],
            "outlier_masking_risk": False,
            "noise_classification": "stable",
            "decision_reason": "",
            "evidence": [],
            "confidence_score": 0.0,
            "methods_triggered": [],
            "method_details": {}
        }

        # Helper for MAD outlier detection
        def _detect_outliers_mad(samples):
            if len(samples) < 3:
                return samples, []
            median = statistics.median(samples)
            mad = statistics.median([abs(x - median) for x in samples])
            if mad == 0:
                return samples, []
            outlier_indices = [i for i, x in enumerate(samples) if abs(x - median) > 3 * mad]
            # If MAD would flag a large fraction of the run as "outliers,"
            # this looks like a genuine sustained shift (e.g. thermal
            # throttling for part of the run), not isolated noise - don't
            # filter, so the consensus methods below still see it.
            if len(outlier_indices) > len(samples) * self.max_outlier_fraction:
                return samples, []
            cleaned = [x for i, x in enumerate(samples) if i not in outlier_indices]
            return cleaned if cleaned else samples, outlier_indices

        # Helper for noise classification
        def _classify_noise(cv_percent):
            if cv_percent < 1.0: return "very_stable"
            if cv_percent < 3.0: return "stable"
            if cv_percent < 5.0: return "moderate"
            if cv_percent < 10.0: return "noisy"
            return "very_noisy"
        
        # Helper: Robust median-based comparison
        def _detect_median_delta(baseline_data, current_data):
            if not baseline_data or not current_data:
                return None
            baseline_median = statistics.median(baseline_data)
            current_median = statistics.median(current_data)
            delta = (current_median - baseline_median) / baseline_median if baseline_median > 0 else 0.0
            # A regression means the current value moved the "wrong" way for
            # this metric's direction (decrease for higher-is-better, increase
            # for lower-is-better), by more than threshold.
            # Example: threshold is -0.05 (-5%), delta of -0.20 (-20%) is a regression
            effective_delta = delta if direction == "higher" else -delta
            if effective_delta < self.throughput_threshold:
                return {"delta_percent": delta * 100, "baseline_median": baseline_median, "current_median": current_median}
            return None

        # Helper: Non-parametric Mann-Whitney U test (fallback to simple comparison if scipy missing)
        def _detect_mann_whitney(baseline_data, current_data, alpha=0.05):
            if len(baseline_data) < 2 or len(current_data) < 2:
                return None
            p_value, used_fallback, _ = self._mann_whitney_pvalue(baseline_data, current_data)
            if not used_fallback:
                if p_value is not None and p_value < alpha:
                    baseline_mean = statistics.mean(baseline_data)
                    current_mean = statistics.mean(current_data)
                    delta = (current_mean - baseline_mean) / baseline_mean if baseline_mean > 0 else 0.0
                    effective_delta = delta if direction == "higher" else -delta
                    if effective_delta < self.throughput_threshold: # Only flag if current is worse AND exceeds threshold
                        return {"p_value": p_value, "delta_percent": delta * 100}
                return None
            # Fallback implementation if scipy is not installed (common in some IIOT testing environments)
            # We'll use a simpler non-parametric approach: count how many current samples are worse than baseline median
            baseline_median = statistics.median(baseline_data)

            # Require that the difference between current and baseline median is actually significant
            # (i.e. at least as big as the threshold)
            def _sample_effective_delta(x):
                d = (x - baseline_median) / baseline_median if baseline_median > 0 else 0.0
                return d if direction == "higher" else -d
            worse_count = sum(1 for x in current_data if _sample_effective_delta(x) < self.throughput_threshold)

            # If more than 60% of current samples are worse than the baseline median by the threshold, flag it
            if len(current_data) > 0 and (worse_count / len(current_data)) >= 0.6:
                baseline_mean = statistics.mean(baseline_data)
                current_mean = statistics.mean(current_data)
                delta = (current_mean - baseline_mean) / baseline_mean if baseline_mean > 0 else 0.0
                effective_delta = delta if direction == "higher" else -delta
                if effective_delta < self.throughput_threshold:
                    return {"p_value": "fallback_>60%_worse", "delta_percent": delta * 100}
            return None

        # Helper: Cohen's d effect size
        def _detect_cohens_d(baseline_data, current_data):
            if len(baseline_data) < 2 or len(current_data) < 2:
                return None
            baseline_mean = statistics.mean(baseline_data)
            current_mean = statistics.mean(current_data)
            baseline_std = statistics.stdev(baseline_data)
            current_std = statistics.stdev(current_data)
            
            # Pooled standard deviation
            n1, n2 = len(baseline_data), len(current_data)
            if n1 + n2 - 2 <= 0:
                return None
            pooled_std = (((n1-1)*(baseline_std**2) + (n2-1)*(current_std**2)) / (n1+n2-2)) ** 0.5
            
            cohens_d = (current_mean - baseline_mean) / pooled_std if pooled_std > 0 else 0.0

            # Only flag if there's a practical effect size AND the mean delta is actually a regression
            delta = (current_mean - baseline_mean) / baseline_mean if baseline_mean > 0 else 0.0
            effective_cohens_d = cohens_d if direction == "higher" else -cohens_d
            effective_delta = delta if direction == "higher" else -delta

            if effective_cohens_d < -self.cohens_d_threshold and effective_delta < self.throughput_threshold:
                return {"cohens_d": cohens_d, "delta_percent": delta * 100}
            return None

        # Helper: Quantile-based comparison (25th percentile)
        def _detect_quantile_delta(baseline_data, current_data):
            if len(baseline_data) < 3 or len(current_data) < 3:
                return None
            # Basic percentile without numpy to avoid dependency issues if not installed
            def _percentile(data, p):
                s = sorted(data)
                k = (len(s) - 1) * (p / 100.0)
                f = int(k)
                c = int(k + 0.5) if k % 1 != 0 else f
                if f == c: return s[f]
                return s[f] + (s[c] - s[f]) * (k - f)
            
            baseline_q25 = _percentile(baseline_data, 25)
            current_q25 = _percentile(current_data, 25)
            delta_q25 = (current_q25 - baseline_q25) / baseline_q25 if baseline_q25 > 0 else 0.0

            effective_delta_q25 = delta_q25 if direction == "higher" else -delta_q25
            if effective_delta_q25 < self.throughput_threshold:
                return {"delta_percent": delta_q25 * 100, "baseline_q25": baseline_q25, "current_q25": current_q25}
            return None

        # Ensure we have throughput data. Handle both raw lists and pre-calculated stats.
        baseline_tp = baseline_metrics.get("throughput", [])
        current_tp = current_metrics.get("throughput", [])
        
        is_precalculated = False
        if not baseline_tp and not current_tp and "mean" in baseline_metrics and "mean" in current_metrics:
            is_precalculated = True
            baseline_mean = baseline_metrics.get("mean", 0.0)
            current_mean = current_metrics.get("mean", 0.0)
            baseline_std = baseline_metrics.get("stddev", 0.0)
            current_std = current_metrics.get("stddev", 0.0)
        else:
            # If exactly one side lacks raw throughput samples but does
            # provide a precalculated mean, treat that mean as a single-
            # sample series rather than forcing BOTH sides down to the
            # bare mean/stddev comparison above - that would throw away
            # the full distribution on the side that DOES have raw data.
            if not baseline_tp and "mean" in baseline_metrics:
                baseline_tp = [baseline_metrics["mean"]]
            if not current_tp and "mean" in current_metrics:
                current_tp = [current_metrics["mean"]]

            if not baseline_tp or not current_tp:
                result["anomalies"].append("Missing throughput data for comparison.")
                return result

            # Detect outliers on current
            raw_current_tp = list(current_tp)
            cleaned_current, outliers = _detect_outliers_mad(current_tp)
            result["outliers_detected"] = len(outliers)
            result["outlier_discarded_values"] = [raw_current_tp[i] for i in outliers]
                
            baseline_mean = statistics.mean(baseline_tp)
            current_mean = statistics.mean(cleaned_current)
            
            baseline_std = statistics.stdev(baseline_tp) if len(baseline_tp) > 1 else 0.0
            current_std = statistics.stdev(cleaned_current) if len(cleaned_current) > 1 else 0.0
            
            # Use cleaned data for current
            current_tp = cleaned_current
        
        # Stability Gate & Noise Classification
        # Use median and MAD for robustness if data has outliers that weren't caught
        if current_tp:
            median_current = statistics.median(current_tp)
            mad_current = statistics.median([abs(x - median_current) for x in current_tp]) if len(current_tp) > 0 else 0
            
            # Robust CV (using MAD instead of stdev, scaled to be comparable)
            # 1.4826 is the scaling factor to make MAD comparable to standard deviation for normal distributions
            robust_cv = (1.4826 * mad_current) / median_current if median_current > 0 else 0.0
            cv_percent = robust_cv * 100
            result["noise_classification"] = _classify_noise(cv_percent)
            
            # Note: For bimodal distributions (like thermal throttling), the robust CV might be high.
            # We don't want to skip regression detection for thermal throttling!
            # So we only enforce the stability gate if there ISN'T a clear regression trend.
            
            # tp_delta = (current_mean - baseline_mean) / baseline_mean if baseline_mean > 0 else 0.0
            # Use median for delta to be robust against any remaining outliers
            baseline_median = statistics.median(baseline_tp) if baseline_tp else 0
            current_median = statistics.median(current_tp) if current_tp else 0
            tp_delta = (current_median - baseline_median) / baseline_median if baseline_median > 0 else 0.0
            effective_tp_delta = tp_delta if direction == "higher" else -tp_delta

            # Only enforce stability gate if there ISN'T a clear regression trend
            if robust_cv > self.STABILITY_GATE and effective_tp_delta >= self.throughput_threshold:
                result["stability_valid"] = False
                result["stability_reason"] = f"Unstable: Robust CV = {cv_percent:.1f}% (threshold {self.STABILITY_GATE*100:.1f}%)"
                result["decision_reason"] = result["stability_reason"]
                return result
        else:
            # Fallback for precalculated stats
            tp_delta = (current_mean - baseline_mean) / baseline_mean if baseline_mean > 0 else 0.0
            effective_tp_delta = tp_delta if direction == "higher" else -tp_delta
            cv = current_std / current_mean if current_mean > 0 else 0.0
            cv_percent = cv * 100
            result["noise_classification"] = _classify_noise(cv_percent)

            if cv > self.STABILITY_GATE and effective_tp_delta >= self.throughput_threshold:
                result["stability_valid"] = False
                result["stability_reason"] = f"Unstable: CV = {cv_percent:.1f}% (threshold {self.STABILITY_GATE*100:.1f}%)"
                result["decision_reason"] = result["stability_reason"]
                return result
        
        # MULTI-METHOD CONSENSUS REGRESSION TRIGGER (Replaces Z-score)
        is_tp_regression = False

        def _run_consensus(data_for_current, suppress_mw=False):
            local_methods = []
            local_details = {}
            baseline_median_lc = statistics.median(baseline_tp) if baseline_tp else 0
            current_median_lc = statistics.median(data_for_current) if data_for_current else 0
            delta_lc = (current_median_lc - baseline_median_lc) / baseline_median_lc if baseline_median_lc > 0 else 0.0
            effective_delta_lc = delta_lc if direction == "higher" else -delta_lc

            # Primary methods
            if self.use_median:
                med_res = _detect_median_delta(baseline_tp, data_for_current)
                if med_res:
                    local_methods.append("median_delta")
                    local_details["median_delta"] = med_res

            if self.use_mann_whitney and not suppress_mw:
                mw_res = _detect_mann_whitney(baseline_tp, data_for_current)
                if mw_res:
                    local_methods.append("mann_whitney")
                    local_details["mann_whitney"] = mw_res

            # Secondary methods
            if self.use_cohens_d:
                cohens_res = _detect_cohens_d(baseline_tp, data_for_current)
                if cohens_res:
                    local_methods.append("cohens_d")
                    local_details["cohens_d"] = cohens_res

            if self.use_quantile:
                quant_res = _detect_quantile_delta(baseline_tp, data_for_current)
                if quant_res:
                    local_methods.append("quantile_delta")
                    local_details["quantile_delta"] = quant_res

            # Consensus Evaluation
            primary_hits = sum(1 for m in local_methods if m in ["median_delta", "mann_whitney"])
            secondary_hits = sum(1 for m in local_methods if m in ["cohens_d", "quantile_delta"])

            # In scipy fallback (fallback_>60%_worse), p_value is a string, which triggers "mann_whitney" in methods_triggered
            # However, for pure noise with 5 samples, it might accidentally cross 60% worse but not be a real regression.
            # To fix the noise filtering test, we need stronger consensus if Mann-Whitney used the fallback.
            used_fallback = any("fallback" in str(v.get("p_value", "")) for m, v in local_details.items() if m == "mann_whitney")

            is_regression = False
            confidence = 0.0
            reason = ""

            # High confidence: Both primary methods agree
            if primary_hits >= 2:
                # If we used fallback for MW, require more strict consensus (need both secondaries) to confirm it wasn't just noise
                if used_fallback and secondary_hits < 2:
                    is_regression = False
                    reason = f"No consensus: Used fallback MW, and secondary methods completely disagreed"
                else:
                    is_regression = True
                    confidence = 95.0
                    reason = f"High confidence consensus (Primary methods matched: {primary_hits})"
            # Medium confidence: 1 primary + at least 1 secondary
            elif primary_hits >= 1 and secondary_hits >= 1:
                # If we used fallback for MW (which might be the only primary hit), require more strict consensus
                if used_fallback and primary_hits == 1 and effective_delta_lc >= self.throughput_threshold * 2 and secondary_hits < 2:
                    is_regression = False
                    reason = f"No consensus: Used fallback MW, but effect size/quantile didn't strongly agree"
                else:
                    is_regression = True
                    confidence = 75.0
                    reason = f"Medium confidence consensus (Primary: {primary_hits}, Secondary: {secondary_hits})"
            # Low confidence fallback: just delta
            elif effective_delta_lc < self.throughput_threshold and len(baseline_tp) < 3:
                # Not enough data for robust stats, fallback to simple delta
                is_regression = True
                local_methods.append("small_sample_delta")
                confidence = 50.0
                reason = f"Small sample delta fallback. Delta {delta_lc*100:.1f}% exceeds threshold {self.throughput_threshold*100:.1f}%"
            else:
                reason = f"No consensus reached. Triggered methods: {local_methods}"

            return {
                "is_regression": is_regression,
                "methods_triggered": local_methods,
                "confidence_score": confidence,
                "decision_reason": reason,
                "method_details": local_details,
            }

        if is_precalculated:
            # Fallback for precalculated stats: use simple delta threshold
            if effective_tp_delta < self.throughput_threshold:
                is_tp_regression = True
                result["methods_triggered"].append("delta_threshold")
                result["method_details"]["delta_threshold"] = {"delta_percent": tp_delta * 100}
                result["confidence_score"] = 50.0  # Low confidence due to precalculated stats
        else:
            consensus = _run_consensus(current_tp, suppress_mw=_suppress_mann_whitney)
            is_tp_regression = consensus["is_regression"]
            result["methods_triggered"] = consensus["methods_triggered"]
            result["method_details"] = consensus["method_details"]
            result["confidence_score"] = consensus["confidence_score"]
            result["decision_reason"] = consensus["decision_reason"]

            # Outlier-masking safeguard: if outliers were discarded and that's
            # what turned a would-be regression into a "pass," don't hide it -
            # flag the risk and demote confidence rather than silently moving on.
            if outliers and not is_tp_regression:
                raw_consensus = _run_consensus(raw_current_tp, suppress_mw=_suppress_mann_whitney)
                if raw_consensus["is_regression"]:
                    result["outlier_masking_risk"] = True
                    result["confidence_score"] = min(result["confidence_score"], 50.0)
                    result["evidence"].append({
                        "type": "CAVEAT",
                        "source": "regression_detector",
                        "value": f"{len(outliers)} iteration(s) discarded as outliers: {result['outlier_discarded_values']}",
                        "interpretation": f"Without outlier filtering, raw data would have flagged a regression via {raw_consensus['methods_triggered']}. Treat this result with reduced confidence."
                    })
                
        if is_tp_regression:
            result["throughput_regression"] = True
            methods_str = ", ".join(result["methods_triggered"])
            msg = f"Throughput regressed by {tp_delta*100:.1f}% (Methods: {methods_str}). Baseline Mean: {baseline_mean:.2f}, Current Mean: {current_mean:.2f}"
            result["anomalies"].append(msg)
            
            if not result["decision_reason"]: # If not set by consensus logic
                result["decision_reason"] = f"Delta {tp_delta*100:.1f}% exceeds threshold {self.throughput_threshold*100:.1f}%"
                
            result["evidence"].append({
                "type": "OBSERVED",
                "source": "regression_detector",
                "value": f"{tp_delta*100:.1f}%",
                "interpretation": f"Throughput degradation detected via consensus: {methods_str}"
            })
        else:
            if not result["decision_reason"]: # If not set by consensus logic
                result["decision_reason"] = f"Delta {tp_delta*100:.1f}% within threshold {self.throughput_threshold*100:.1f}% or lacking consensus"
            
        # Latency check (if present)
        # Note: In pre-calculated stats, latency is stored under a different test name (e.g. latency_95_...)
        # or passed via current_metrics.get("latency_mean")
        lat_delta = 0.0
        base_lat_mean = 0.0
        curr_lat_mean = 0.0
        
        if "latency_mean" in baseline_metrics and "latency_mean" in current_metrics:
            base_lat_mean = baseline_metrics.get("latency_mean", 0.0)
            curr_lat_mean = current_metrics.get("latency_mean", 0.0)
        else:
            baseline_lat = baseline_metrics.get("latency_95", [])
            current_lat = current_metrics.get("latency_95", [])
            
            if baseline_lat and current_lat:
                base_lat_mean = statistics.mean(baseline_lat)
                curr_lat_mean = statistics.mean(current_lat)
        
        if base_lat_mean > 0 and curr_lat_mean > 0:
            
            lat_delta = (curr_lat_mean - base_lat_mean) / base_lat_mean if base_lat_mean > 0 else 0.0
            if lat_delta > self.latency_threshold:
                result["latency_regression"] = True
                result["anomalies"].append(
                    f"95th-percentile latency spiked by {lat_delta*100:.1f}%. "
                    f"Baseline: {base_lat_mean:.2f}ms, Current: {curr_lat_mean:.2f}ms"
                )
            
            # Absolute latency thresholds
            if curr_lat_mean > self.LATENCY_ABSOLUTE_FAIL:
                result["anomalies"].append(f"FAIL: Latency 95% = {curr_lat_mean:.2f}ms (> {self.LATENCY_ABSOLUTE_FAIL}ms)")
            elif curr_lat_mean > self.LATENCY_ABSOLUTE_WARN:
                result["anomalies"].append(f"WARN: Latency 95% = {curr_lat_mean:.2f}ms (> {self.LATENCY_ABSOLUTE_WARN}ms)")
                
        result["metrics"] = {
            "baseline_throughput_mean": baseline_mean,
            "baseline_throughput_stdev": baseline_std,
            "current_throughput_mean": current_mean,
            "current_throughput_stdev": current_std,
            "throughput_delta_percent": tp_delta * 100.0,
            "latency_delta_percent": lat_delta * 100.0
        }

        return result

    def detect_regressions_batch(self, baseline_stats: Dict[str, Dict[str, Any]], current_stats: Dict[str, Dict[str, Any]], directions: Optional[Dict[str, str]] = None) -> Dict[str, Dict[str, Any]]:
        """
        Runs detect_regressions() across every metric present in both
        baseline_stats and current_stats, then applies a Benjamini-Hochberg
        false-discovery-rate correction to the Mann-Whitney p-values across
        the whole batch before finalizing each metric's verdict.

        Without this, independently testing many metrics at a flat p<0.05
        cutoff inflates the family-wise false-positive rate - e.g. with 20
        unrelated metrics, ~1 is expected to cross p<0.05 by chance alone.
        BH correction bounds the expected proportion of false positives
        among the metrics flagged, at the cost of needing a joint view of
        the whole comparison (hence this being a batch method rather than
        a per-metric one).

        Metrics whose Mann-Whitney check used the non-scipy ">=60% worse"
        fallback (no real p-value) are left untouched by the correction -
        there's no p-value to rank, so their hit/no-hit stands as computed.
        Metrics using precalculated mean/stddev stats (no raw throughput
        samples) never run Mann-Whitney at all and are likewise untouched.

        Returns a dict shaped exactly like {metric_name: detect_regressions() result},
        with an added result["metrics"]["mann_whitney_p_adjusted"] on every
        metric that contributed a real p-value to the correction.
        """
        directions = directions or {}
        common_metrics = [m for m in current_stats if m in baseline_stats]

        raw_results: Dict[str, Dict[str, Any]] = {}
        pvalue_family: List[Any] = []  # (metric_name, p_value)

        for metric_name in common_metrics:
            base = baseline_stats[metric_name]
            curr = current_stats[metric_name]
            direction = directions.get(metric_name, "higher")
            raw_results[metric_name] = self.detect_regressions(base, curr, test_name=metric_name, direction=direction)

            p_value, used_fallback, _ = self._mann_whitney_pvalue(base.get("throughput", []), curr.get("throughput", []))
            if p_value is not None and not used_fallback:
                pvalue_family.append((metric_name, p_value))

        if not pvalue_family:
            return raw_results

        # Benjamini-Hochberg step-up procedure: rank p-values ascending,
        # adjusted[i] = min over j >= i of (p[j] * m / rank[j]), enforcing
        # monotonicity from the largest rank down.
        m = len(pvalue_family)
        sorted_family = sorted(pvalue_family, key=lambda kv: kv[1])
        pvalue_lookup = dict(pvalue_family)
        adjusted: Dict[str, float] = {}
        running_min = 1.0
        for rank in range(m, 0, -1):
            metric_name, p = sorted_family[rank - 1]
            candidate = min(p * m / rank, 1.0)
            running_min = min(running_min, candidate)
            adjusted[metric_name] = running_min

        for metric_name, p_adj in adjusted.items():
            result = raw_results[metric_name]
            result["metrics"]["mann_whitney_p_adjusted"] = p_adj

            mw_hit_raw = "mann_whitney" in result["methods_triggered"]
            if mw_hit_raw and p_adj >= self.fdr_alpha:
                # Raw p<0.05 doesn't survive FDR correction across this
                # batch - recompute without crediting mann_whitney as a hit,
                # so the verdict/confidence reflect the remaining consensus.
                base = baseline_stats[metric_name]
                curr = current_stats[metric_name]
                direction = directions.get(metric_name, "higher")
                corrected = self.detect_regressions(
                    base, curr, test_name=metric_name, direction=direction,
                    _suppress_mann_whitney=True,
                )
                corrected["metrics"]["mann_whitney_p_adjusted"] = p_adj
                corrected["evidence"].append({
                    "type": "CAVEAT",
                    "source": "regression_detector",
                    "value": f"p_adjusted={p_adj:.4f} (raw p={pvalue_lookup.get(metric_name):.4f}, m={m})",
                    "interpretation": "Mann-Whitney hit did not survive Benjamini-Hochberg FDR correction across this comparison's metrics; verdict recomputed without it."
                })
                raw_results[metric_name] = corrected

        return raw_results
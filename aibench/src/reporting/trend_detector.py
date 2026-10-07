"""
trend_detector.py - Detects performance degradation trends across multiple runs.
Used by the RCA orchestrator when analyzing 4 or more runs.

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import statistics
from typing import List, Dict, Any, Optional

class TrendDetector:
    """
    Analyzes sequences of benchmark runs for sustained degradation trends.
    Uses robust, non-parametric methods suitable for IIOT devices.
    """
    
    def __init__(self, degradation_threshold: float = -0.05):
        """
        Args:
            degradation_threshold: The minimum total percentage drop across 
                                   the sequence to flag as a regression (-5%).
        """
        self.degradation_threshold = degradation_threshold
        
    def detect_trends(self, run_metrics: List[float], direction: str = "higher") -> Dict[str, Any]:
        """
        Analyzes a sequence of run metrics for degradation trends.

        Args:
            run_metrics: A chronological list of throughput values
                         (e.g., [run1_mean, run2_mean, run3_mean, run4_mean])
            direction: "higher" (default, preserves original behavior) if higher
                       values are better for this metric, or "lower" if lower
                       values are better (e.g. latency) -- for "lower", a
                       sustained *upward* trend is the degradation, not downward.

        Returns:
            Dict containing trend analysis results and whether regression was flagged.
        """
        if len(run_metrics) < 4:
            return {
                "trend_detected": False,
                "reason": "Not enough runs for trend analysis (need >= 4)",
            }

        result = {
            "trend_detected": False,
            "trend_type": None,
            "delta_percent": 0.0,
            "methods_triggered": [],
            "metrics": run_metrics
        }

        # Calculate overall delta (first vs last), reported as the raw,
        # non-direction-normalized value (consistent with the rest of the
        # codebase's delta_percent convention).
        first_val = run_metrics[0]
        last_val = run_metrics[-1]

        overall_delta = (last_val - first_val) / first_val if first_val > 0 else 0.0
        result["delta_percent"] = overall_delta * 100

        # All three detection methods below assume degradation shows up as a
        # downward shift in the data. For "lower is better" metrics (e.g.
        # latency), degradation is actually an *upward* shift, so we negate
        # the series first -- this makes "downward in effective_data" always
        # mean "degradation", regardless of the metric's real direction.
        is_lower_better = (direction == "lower")
        effective_data = [-x for x in run_metrics] if is_lower_better else run_metrics
        effective_delta = -overall_delta if is_lower_better else overall_delta

        # Method 1: CUSUM (Cumulative Sum Control Chart) for sustained shifts
        cusum_detected = self._detect_cusum(effective_data)
        if cusum_detected:
            result["methods_triggered"].append("cusum")

        # Method 2: Mann-Kendall test for monotonic downward trend
        mk_detected = self._detect_mann_kendall(effective_data)
        if mk_detected:
            result["methods_triggered"].append("mann_kendall")

        # Method 3: Linear slope detection (simple heuristic fallback)
        slope_detected = self._detect_linear_slope(effective_data)
        if slope_detected:
            result["methods_triggered"].append("linear_slope")

        # Evaluate consensus: Trend regression is flagged if overall delta exceeds threshold
        # AND at least two trend methods confirm it's a structural trend (not just noise)
        # OR one strong method (cusum/mann_kendall) confirms it
        strong_methods = sum(1 for m in result["methods_triggered"] if m in ["cusum", "mann_kendall"])

        if effective_delta < self.degradation_threshold:
            if strong_methods >= 1 or len(result["methods_triggered"]) >= 2:
                result["trend_detected"] = True
                result["trend_type"] = ", ".join(result["methods_triggered"])

        return result
        
    def _detect_cusum(self, data: List[float]) -> bool:
        """
        Cumulative Sum Control Chart.
        Detects if there is a sustained shift in the mean of the process.
        """
        mean = statistics.mean(data)
        std = statistics.stdev(data) if len(data) > 1 else 0
        
        if std == 0:
            return False
            
        # Target shift to detect
        k = 0.25 * std 
        
        # Control limit (lower for 5-sample data)
        h = 1.2 * std
        
        # We only care about downward shifts (degradation) for throughput
        # (lower values mean degradation)
        c_minus = 0
        
        for x in data:
            # For lower-is-worse metrics, x - mean is negative when x drops
            # CUSUM traditionally accumulates (mean - x - k) for downward shifts
            c_minus = max(0, c_minus + (mean - x - k))
            if c_minus > h:
                return True
                
        return False
        
    def _detect_mann_kendall(self, data: List[float]) -> bool:
        """
        Simplified Mann-Kendall test for monotonic downward trend.
        Non-parametric, robust to outliers.
        """
        n = len(data)
        s = 0
        
        for k in range(n - 1):
            for j in range(k + 1, n):
                if data[j] < data[k]:
                    s -= 1
                elif data[j] > data[k]:
                    s += 1
                    
        # Max possible negative S is n*(n-1)/2
        max_neg_s = -1 * (n * (n - 1)) / 2
        
        # If S is highly negative (e.g., > 60% of pairs are decreasing), flag trend
        if s <= max_neg_s * 0.6:
            return True
            
        return False
        
    def _detect_linear_slope(self, data: List[float]) -> bool:
        """
        Simple linear slope calculation without external dependencies like numpy.
        """
        n = len(data)
        sum_x = sum(range(n))
        sum_y = sum(data)
        sum_xy = sum(i * data[i] for i in range(n))
        sum_xx = sum(i * i for i in range(n))
        
        denominator = n * sum_xx - sum_x * sum_x
        if denominator == 0:
            return False
            
        slope = (n * sum_xy - sum_x * sum_y) / denominator
        
        # Calculate expected total drop based on slope
        expected_drop = slope * (n - 1)
        
        # If expected drop is greater than 5% of mean, flag as downward slope.
        # Use abs(mean) rather than mean: callers may pass a sign-flipped
        # ("effective") series for lower-is-better metrics, whose mean is
        # negative even though the magnitude-relative check below is still
        # meaningful. For higher-is-better data (the original behavior),
        # mean is already positive, so abs(mean) == mean -- no behavior change.
        mean = statistics.mean(data)

        # For false positive prevention, also check if standard error is too high
        std_err = statistics.stdev(data) / (n**0.5) if n > 1 else 0
        if std_err > abs(expected_drop):
            return False # Too noisy to trust linear slope

        if mean != 0 and (expected_drop / abs(mean)) < self.degradation_threshold:
            return True

        return False

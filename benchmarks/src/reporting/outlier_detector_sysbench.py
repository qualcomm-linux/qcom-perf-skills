"""
outlier_detector_sysbench.py - Sysbench-specific outlier detection module.

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import copy
import logging
from typing import Any, Dict, List, Optional, Tuple
from src.reporting.outlier_detector_base import OutlierDetectorBase

logger = logging.getLogger(__name__)

_LOG_PREFIX = "[outlier_detector]"

class OutlierDetector(OutlierDetectorBase):
    """Sysbench outlier detector"""
    
    @property
    def METRIC_THRESHOLDS(self) -> Dict[str, Dict[str, float]]:
        return {
            "cpu_events_per_sec":     {"pct": 0.05, "iqr_mult": 1.5, "mad_z": 2.5},
            "total_events":           {"pct": 0.05, "iqr_mult": 1.5, "mad_z": 2.5},
            "latency_min_ms":         {"pct": 0.05, "iqr_mult": 1.5, "mad_z": 2.5},
            "latency_avg_ms":         {"pct": 0.10, "iqr_mult": 1.5, "mad_z": 2.5},
            "latency_p95_ms":         {"pct": 0.10, "iqr_mult": 1.5, "mad_z": 2.5},
            "latency_max_ms":         {"pct": 0.25, "iqr_mult": 2.0, "mad_z": 3.0},
            "events_stddev":            {"pct": 0.15, "iqr_mult": 1.5, "mad_z": 2.5},
            "execution_time_stddev_sec": {"pct": 0.15, "iqr_mult": 1.5, "mad_z": 2.5},
        }

    def _active_metrics(self, iterations: List[Dict[str, Any]]) -> List[str]:
        """Determine which metrics should participate in outlier detection"""
        _OPTIONAL_METRICS = {
            "events_stddev",
            "execution_time_stddev_sec",
        }
        
        active = []
        for metric in self.METRIC_THRESHOLDS.keys():
            if metric in _OPTIONAL_METRICS:
                values = [it.get(metric) for it in iterations]
                if all(v is None for v in values):
                    continue
            active.append(metric)
        return active

    def run_detection(self, iterations: List[Dict[str, Any]], **kwargs) -> Dict[str, Any]:
        """
        Analyze a series of sysbench CPU iteration dicts for outliers.
        """
        benchmark_variant = kwargs.get("benchmark_variant", "cpu_1t")
        run_id = kwargs.get("run_id", "")
        min_iterations = kwargs.get("min_iterations", 2)
        n_iterations = kwargs.get("n_iterations", len(iterations))
        
        working = copy.deepcopy(iterations)
        effective_n = len(working)
        
        # Select method based on sample size
        if effective_n <= 6:
            method = "median_pct"
        elif effective_n <= 29:
            method = "iqr"
        else:
            method = "mad_zscore"
            
        logger.info(
            "%s %s",
            _LOG_PREFIX,
            {"event": "detection_method_selected", "resolved_n": effective_n, "method": method},
        )
        
        active_metrics = self._active_metrics(working)
        
        if method == "median_pct":
            flagged_indices, flagged_metrics = self.median_pct_method(working, active_metrics)
        elif method == "iqr":
            flagged_indices, flagged_metrics = self.iqr_method(working, active_metrics)
        else:
            flagged_indices, flagged_metrics = self.mad_zscore_method(working, active_metrics)
            
        num_flagged = len(flagged_indices)
        
        if num_flagged == 0:
            status = "CLEAN"
            clean_iterations = working
            discarded_indices: List[int] = []
            discarded_metrics: Dict[int, List[str]] = {}
        elif num_flagged == 1:
            status = "VALID"
            bad_idx = flagged_indices[0]
            clean_iterations = [it for i, it in enumerate(working) if i != bad_idx]
            discarded_indices = [bad_idx]
            discarded_metrics = {bad_idx: flagged_metrics[bad_idx]}
            logger.warning(f"{_LOG_PREFIX} Outlier discarded: index {bad_idx}, metrics {flagged_metrics[bad_idx]}")
        else:
            status = "UNSTABLE"
            # Return unstable result rather than raising exception so calling code can decide what to do
            clean_iterations = [it for i, it in enumerate(working) if i not in flagged_indices]
            discarded_indices = flagged_indices
            discarded_metrics = flagged_metrics
            logger.warning(f"{_LOG_PREFIX} Series unstable! {num_flagged} outliers detected.")

        return {
            "status": status,
            "benchmark_variant": benchmark_variant,
            "resolved_n": n_iterations,
            "effective_n": len(clean_iterations),
            "detection_method": method,
            "discarded_indices": discarded_indices,
            "discarded_metrics": {str(k): v for k, v in discarded_metrics.items()},
            "clean_iterations": clean_iterations
        }
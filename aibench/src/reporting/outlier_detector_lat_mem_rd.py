"""
outlier_detector_lat_mem_rd.py - lat_mem_rd-specific outlier detection module.

Detects outlier iterations based on the per-iteration plateau latency (ns).
Since lower latency is better for this benchmark, thresholds are still applied
on absolute percentage deviation (direction-agnostic outlier detection).

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import copy
import logging
from typing import Any, Dict, List
from src.reporting.outlier_detector_base import OutlierDetectorBase

logger = logging.getLogger(__name__)

_LOG_PREFIX = "[outlier_detector_lat_mem_rd]"


class OutlierDetector(OutlierDetectorBase):
    """lat_mem_rd outlier detector - operates on per-iteration plateau_latency_ns."""

    @property
    def METRIC_THRESHOLDS(self) -> Dict[str, Dict[str, float]]:
        return {
            "plateau_latency_ns": {"pct": 0.05, "iqr_mult": 1.5, "mad_z": 2.5}
        }

    def run_detection(self, iterations: List[Dict[str, Any]], **kwargs) -> Dict[str, Any]:
        """
        Analyze a series of lat_mem_rd iteration dicts (each containing
        'plateau_latency_ns') for outliers.
        """
        benchmark_variant = kwargs.get("benchmark_variant", "lat_mem_rd")
        run_id = kwargs.get("run_id", "")
        n_iterations = kwargs.get("n_iterations", len(iterations))

        working = copy.deepcopy(iterations)
        effective_n = len(working)

        # Select method based on sample size (consistent with other detectors)
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

        active_metrics = ["plateau_latency_ns"]

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

# REQUIRED FOR AUTO-DISCOVERY
OutlierDetector = OutlierDetector
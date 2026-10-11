"""
outlier_detector_geekbench.py - Outlier detection for Geekbench benchmark

Monitors all 6 metrics (Single-Core, Multi-Core, and their Integer/Float components)
for statistical anomalies using IQR or Median-Pct methods.

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import copy
from typing import Any, Dict, List
from src.reporting.outlier_detector_base import OutlierDetectorBase


class OutlierDetector(OutlierDetectorBase):
    """
    Outlier detector for Geekbench CPU benchmark.
    
    Monitors all 6 metrics:
    - single_core_score (primary)
    - single_core_integer_score
    - single_core_float_score
    - multi_core_score (primary)
    - multi_core_integer_score
    - multi_core_float_score
    """
    
    @property
    def METRIC_THRESHOLDS(self) -> Dict[str, Dict[str, float]]:
        """
        Define thresholds for all 6 Geekbench metrics.
        
        Returns:
            Dict mapping metric names to threshold configurations
        """
        return {
            "single_core_score": {
                "pct": 0.05,        # 5% deviation for median-pct method
                "iqr_mult": 1.5,    # IQR multiplier
                "mad_z": 2.5        # MAD z-score threshold
            },
            "single_core_integer_score": {
                "pct": 0.05,
                "iqr_mult": 1.5,
                "mad_z": 2.5
            },
            "single_core_float_score": {
                "pct": 0.05,
                "iqr_mult": 1.5,
                "mad_z": 2.5
            },
            "multi_core_score": {
                "pct": 0.05,
                "iqr_mult": 1.5,
                "mad_z": 2.5
            },
            "multi_core_integer_score": {
                "pct": 0.05,
                "iqr_mult": 1.5,
                "mad_z": 2.5
            },
            "multi_core_float_score": {
                "pct": 0.05,
                "iqr_mult": 1.5,
                "mad_z": 2.5
            }
        }
    
    def run_detection(self, iterations: List[Dict[str, Any]], **kwargs) -> Dict[str, Any]:
        """
        Run outlier detection on Geekbench iterations.
        
        Args:
            iterations: List of iteration dicts with all 6 metrics
            **kwargs: Additional parameters (n_iterations, min_iterations, etc.)
        
        Returns:
            Dict with:
                - status: "VALID" or "UNSTABLE"
                - clean_iterations: List of non-outlier iterations
                - discarded_indices: List of outlier indices
                - detection_method: Method used ("iqr", "median_pct", or "mad")
                - flagged_metrics: Dict of which metrics flagged which iterations
        """
        if not iterations:
            return {
                "status": "INVALID",
                "clean_iterations": [],
                "discarded_indices": [],
                "detection_method": "none",
                "flagged_metrics": {}
            }
        
        working = copy.deepcopy(iterations)
        n = len(working)
        
        # Decide method based on sample size
        if n <= 6:
            method = "median_pct"
        elif n <= 15:
            method = "iqr"
        else:
            method = "mad"
        
        # All 6 metrics to monitor
        metrics_to_check = [
            "single_core_score",
            "single_core_integer_score",
            "single_core_float_score",
            "multi_core_score",
            "multi_core_integer_score",
            "multi_core_float_score"
        ]
        
        # Run detection
        if method == "median_pct":
            flagged_indices, flagged_by_metric = self.median_pct_method(working, metrics_to_check)
        elif method == "iqr":
            flagged_indices, flagged_by_metric = self.iqr_method(working, metrics_to_check)
        else:  # mad
            flagged_indices, flagged_by_metric = self.mad_zscore_method(working, metrics_to_check)
        
        # Filter clean iterations
        clean = [it for i, it in enumerate(working) if i not in flagged_indices]
        
        # Determine status
        # Allow up to 1 outlier for small samples (n<=5), otherwise max 20% outliers
        max_outliers = 1 if n <= 5 else max(1, int(n * 0.2))
        status = "VALID" if len(flagged_indices) <= max_outliers else "UNSTABLE"
        
        return {
            "status": status,
            "clean_iterations": clean,
            "discarded_indices": sorted(flagged_indices),
            "detection_method": method,
            "flagged_metrics": flagged_by_metric,
            "total_iterations": n,
            "outliers_detected": len(flagged_indices)
        }


# REQUIRED FOR AUTO-DISCOVERY
OutlierDetector = OutlierDetector
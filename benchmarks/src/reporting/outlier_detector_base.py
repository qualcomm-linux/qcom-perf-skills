"""
outlier_detector_base.py - Base class for benchmark-specific outlier detectors
Provides common statistical methods; subclasses define thresholds and logic.

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import statistics
import logging
from typing import List, Dict, Tuple, Any
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

class OutlierDetectorBase(ABC):
    """Abstract base for all benchmark outlier detectors"""
    
    @property
    @abstractmethod
    def METRIC_THRESHOLDS(self) -> Dict[str, Dict[str, float]]:
        """
        Define per-benchmark metric thresholds.
        Example:
        {
            "throughput": {"pct": 0.05, "iqr_mult": 1.5, "mad_z": 2.5}
        }
        """
        pass

    def median_pct_method(self, iterations: List[Dict], metrics: List[str]) -> Tuple[List[int], Dict]:
        """Detect outliers using % deviation from median"""
        flagged_metrics: Dict[int, List[str]] = {}
        
        for metric in metrics:
            pairs = []
            for idx, it in enumerate(iterations):
                val = it.get(metric)
                if val is not None:
                    pairs.append((idx, float(val)))
                    
            if len(pairs) < 2:
                continue
                
            values = [v for _, v in pairs]
            if len(set(values)) <= 1:
                continue
                
            median = statistics.median(values)
            threshold = self.METRIC_THRESHOLDS.get(metric, {}).get("pct", 0.05)
            
            for idx, value in pairs:
                deviation = abs(value - median) / abs(median) if median != 0 else (1.0 if value != 0 else 0.0)
                if deviation > threshold:
                    flagged_metrics.setdefault(idx, []).append(metric)
                    
        return sorted(flagged_metrics.keys()), flagged_metrics

    def iqr_method(self, iterations: List[Dict], metrics: List[str]) -> Tuple[List[int], Dict]:
        """Detect outliers using IQR (Tukey fences)"""
        flagged_metrics: Dict[int, List[str]] = {}
        
        for metric in metrics:
            pairs = []
            for idx, it in enumerate(iterations):
                val = it.get(metric)
                if val is not None:
                    pairs.append((idx, float(val)))
                    
            if len(pairs) < 4:
                # Fallback to median_pct if not enough data
                median_indices, m_metrics = self.median_pct_method(iterations, [metric])
                for idx in median_indices:
                    flagged_metrics.setdefault(idx, []).extend(m_metrics.get(idx, []))
                continue
                
            values = [v for _, v in pairs]
            if len(set(values)) <= 1:
                continue
                
            sorted_values = sorted(values)
            
            # Simple quantile logic
            def get_q(q):
                pos = q * (len(sorted_values) - 1)
                l = int(pos)
                u = min(l + 1, len(sorted_values) - 1)
                return sorted_values[l] + (sorted_values[u] - sorted_values[l]) * (pos - l)
                
            q1 = get_q(0.25)
            q3 = get_q(0.75)
            iqr = q3 - q1
            mult = self.METRIC_THRESHOLDS.get(metric, {}).get("iqr_mult", 1.5)
            
            if iqr == 0:
                continue
                
            lower_fence = q1 - mult * iqr
            upper_fence = q3 + mult * iqr
            
            for idx, value in pairs:
                if value < lower_fence or value > upper_fence:
                    flagged_metrics.setdefault(idx, []).append(metric)
                    
        return sorted(flagged_metrics.keys()), flagged_metrics

    def mad_zscore_method(self, iterations: List[Dict], metrics: List[str]) -> Tuple[List[int], Dict]:
        """Detect outliers using Modified Z-score (MAD-based)"""
        flagged_metrics: Dict[int, List[str]] = {}
        
        for metric in metrics:
            pairs = []
            for idx, it in enumerate(iterations):
                val = it.get(metric)
                if val is not None:
                    pairs.append((idx, float(val)))
                    
            if len(pairs) < 2:
                continue
                
            values = [v for _, v in pairs]
            if len(set(values)) <= 1:
                continue
                
            median = statistics.median(values)
            abs_devs = [abs(v - median) for v in values]
            mad = statistics.median(abs_devs)
            z_threshold = self.METRIC_THRESHOLDS.get(metric, {}).get("mad_z", 2.5)
            
            if mad == 0:
                for idx, value in pairs:
                    if value != median:
                        flagged_metrics.setdefault(idx, []).append(metric)
                continue
                
            for idx, value in pairs:
                modified_z = 0.6745 * (value - median) / mad
                if abs(modified_z) > z_threshold:
                    flagged_metrics.setdefault(idx, []).append(metric)
                    
        return sorted(flagged_metrics.keys()), flagged_metrics
        
    @abstractmethod
    def run_detection(self, iterations: List[Dict[str, Any]], **kwargs) -> Dict[str, Any]:
        """
        Main entry point for outlier detection.
        Must be implemented by subclass.
        """
        pass
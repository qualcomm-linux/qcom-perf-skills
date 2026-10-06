"""
test_trend_detector.py - Tests for the multi-run trend detection logic
"""

import sys
from pathlib import Path
import unittest

# Allow importing from src
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.reporting.trend_detector import TrendDetector

class TestTrendDetector(unittest.TestCase):
    def setUp(self):
        # We need a drop of at least 5% from first to last run to flag a trend regression
        self.detector = TrendDetector(degradation_threshold=-0.05)
        
    def test_not_enough_runs(self):
        # Needs at least 4 runs
        metrics = [100.0, 99.0, 95.0]
        res = self.detector.detect_trends(metrics)
        self.assertFalse(res["trend_detected"])
        self.assertEqual(res["reason"], "Not enough runs for trend analysis (need >= 4)")

    def test_stable_trend(self):
        # Data is stable, no downward trend
        metrics = [100.0, 101.0, 99.0, 100.0, 102.0]
        res = self.detector.detect_trends(metrics)
        self.assertFalse(res["trend_detected"])
        # Overall delta is positive
        self.assertGreaterEqual(res["delta_percent"], 0.0)

    def test_obvious_degradation_trend(self):
        # Clear step-down degradation trend.
        # Drops from 100 to 88 (12% drop). Should be caught by multiple methods.
        metrics = [100.0, 96.0, 93.0, 90.0, 88.0]
        res = self.detector.detect_trends(metrics)
        
        self.assertTrue(res["trend_detected"])
        self.assertLess(res["delta_percent"], -5.0)
        self.assertIn("mann_kendall", res["methods_triggered"])
        self.assertIn("linear_slope", res["methods_triggered"])

    def test_cusum_sustained_shift(self):
        # First two runs are great, then a sustained shift downward (e.g., thermal throttle engages and stays on)
        metrics = [100.0, 101.0, 85.0, 84.0, 86.0]
        res = self.detector.detect_trends(metrics)
        
        self.assertTrue(res["trend_detected"])
        # CUSUM is specifically designed to catch sustained shifts like this
        self.assertIn("cusum", res["methods_triggered"])

    def test_false_positive_prevention(self):
        # Overall delta from first to last might be -6%, but the trend isn't structural/monotonic.
        # It's just noisy data where the last run happens to be a bit low.
        metrics = [100.0, 90.0, 105.0, 88.0, 94.0]
        res = self.detector.detect_trends(metrics)
        
        # In this noisy data, Mann-Kendall and CUSUM shouldn't trigger strongly
        # If no methods trigger, it shouldn't be flagged as a trend
        self.assertFalse(res["trend_detected"])

if __name__ == "__main__":
    unittest.main()
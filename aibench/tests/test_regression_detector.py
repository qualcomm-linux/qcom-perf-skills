"""
Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import sys
from pathlib import Path
import unittest

# Allow importing from src
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.reporting.regression_detector import RegressionDetector

class TestRegressionDetector(unittest.TestCase):
    def setUp(self):
        self.detector = RegressionDetector(throughput_threshold=-0.05, latency_threshold=0.10)

    def test_no_regression(self):
        baseline = {"throughput": [100.0, 102.0, 98.0]}
        current = {"throughput": [101.0, 99.0, 100.5]}
        res = self.detector.detect_regressions(baseline, current, "test_cpu")
        self.assertFalse(res["throughput_regression"])
        self.assertFalse(res["latency_regression"])

    def test_regression_threshold_breach(self):
        # Throughput dropped significantly (100 -> 90, i.e., -10%)
        # Standard deviation is 0.0 (only one data point), so statistical filter is bypassed
        baseline = {"throughput": [100.0]}
        current = {"throughput": [90.0]}
        res = self.detector.detect_regressions(baseline, current, "test_cpu")
        self.assertTrue(res["throughput_regression"])

    def test_noise_filtering_via_z_score(self):
        # Baseline has high variance (stdev is large)
        # Drop is -6%, but statistically insignificant because variance is high
        baseline = {"throughput": [100.0, 80.0, 120.0]}  # mean = 100, stdev = 20.0
        current = {"throughput": [94.0, 93.0, 95.0]}     # mean = 94.0, delta = -6%
        res = self.detector.detect_regressions(baseline, current, "test_cpu")
        # Should NOT trigger regression because Z-score is -0.3, which is within normal jitter
        self.assertFalse(res["throughput_regression"])

    def test_lower_is_better_decrease_is_not_a_regression(self):
        # Metric dropped 100 -> 90 (-10%). For a "lower is better" metric
        # (e.g. latency), a decrease is an improvement, not a regression.
        baseline = {"throughput": [100.0]}
        current = {"throughput": [90.0]}
        res = self.detector.detect_regressions(baseline, current, "test_latency", direction="lower")
        self.assertFalse(res["throughput_regression"])

    def test_lower_is_better_increase_is_a_regression(self):
        # Metric rose 100 -> 110 (+10%). For a "lower is better" metric,
        # an increase beyond the threshold is a genuine regression.
        baseline = {"throughput": [100.0]}
        current = {"throughput": [110.0]}
        res = self.detector.detect_regressions(baseline, current, "test_latency", direction="lower")
        self.assertTrue(res["throughput_regression"])

if __name__ == "__main__":
    unittest.main()
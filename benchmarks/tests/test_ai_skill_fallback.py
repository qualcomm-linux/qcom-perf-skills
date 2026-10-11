import unittest
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import sys
base_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(base_dir))
# Add the scripts directory to path to import run_rca
scripts_dir = base_dir / ".claude" / "skills" / "regression-detection-and-rca" / "scripts"
sys.path.insert(0, str(scripts_dir))

from src.reporting.regression_detector import RegressionDetector
from run_rca import _compare_and_rca

class TestAISkillFallback(unittest.TestCase):
    def setUp(self):
        self.detector = RegressionDetector(
            throughput_threshold=-0.05,
            latency_threshold=0.10,
            use_median=True,
            use_mann_whitney=True,
            use_cohens_d=True,
            use_quantile=True
        )
        self.anomalies = {}
        
        # Simulated baseline and current stats
        self.baseline_stats = {
            "test_throughput": {"mean": 100.0, "stddev": 5.0}
        }
        self.current_stats = {
            "test_throughput": {"mean": 90.0, "stddev": 5.0} # 10% drop, should be regression
        }

    @patch('run_rca.RCADetector')
    def test_python_fallback_executes(self, mock_rca):
        """
        Verify that when AI skill invocation fails/NotImplemented,
        the Python RegressionDetector correctly executes as a fallback
        and populates the regressions dict.
        """
        # We expect a regression since 90 is 10% less than 100, which is > 5% threshold
        result = _compare_and_rca(
            "test_fallback",
            self.baseline_stats,
            self.current_stats,
            self.detector,
            self.anomalies,
            skip_rca=True
        )
        
        # Verify the fallback worked
        self.assertIn("test_throughput", result["regressions"])
        self.assertTrue(result["regression_detected"])
        
        # Verify the regression was actually flagged by the Python fallback logic
        throughput_res = result["regressions"]["test_throughput"]
        self.assertTrue(throughput_res["throughput_regression"])
        
    @patch('run_rca.RCADetector')
    def test_metric_direction_preservation(self, mock_rca):
        """
        Verify the Python fallback still correctly identifies latency spikes.
        """
        # RegressionDetector expects the metric under the test_name key,
        # but for precalculated stats it looks inside for "mean" and "stddev".
        # However, for latency it explicitly checks current_metrics.get("latency_mean")
        # Let's mock a standard latency array instead to avoid precalculated edge cases.
        baseline_stats = {
            "test_latency_max": [100.0, 101.0, 99.0, 100.5, 99.5]
        }
        current_stats = {
            "test_latency_max": [115.0, 116.0, 114.0, 115.5, 114.5] # 15% increase
        }
        
        # We need to test the actual detector directly first to see why it's failing
        test_result = self.detector.detect_regressions(
            {"latency_mean": 100.0},
            {"latency_mean": 115.0},
            test_name="test_latency_max"
        )
        
        # In run_rca, baseline_stats looks like {"metric_name": {"mean": X, "stddev": Y}}
        # But RegressionDetector expects {"mean": X, "stddev": Y, "latency_mean": Z}
        # Let's adjust the structure to match what run_rca actually passes
        baseline_stats_formatted = {
            "test_latency_max": {"latency_mean": 100.0, "mean": 10.0} # Added mean to trigger precalculated path
        }
        current_stats_formatted = {
            "test_latency_max": {"latency_mean": 115.0, "mean": 10.0}
        }
        
        result = _compare_and_rca(
            "test_latency",
            baseline_stats_formatted,
            current_stats_formatted,
            self.detector,
            self.anomalies,
            skip_rca=True
        )
        
        self.assertTrue(result["regression_detected"])
        self.assertTrue(result["regressions"]["test_latency_max"]["latency_regression"])

if __name__ == '__main__':
    unittest.main()
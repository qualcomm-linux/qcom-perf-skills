import unittest
import sys
from pathlib import Path
from unittest.mock import patch

base_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(base_dir))
# Add the scripts directory to path to import run_rca
scripts_dir = base_dir / ".claude" / "skills" / "regression-detection-and-rca" / "scripts"
sys.path.insert(0, str(scripts_dir))

from src.reporting.regression_detector import RegressionDetector
from run_rca import _compare_and_rca

class TestRCASkillFallback(unittest.TestCase):
    def setUp(self):
        self.detector = RegressionDetector(
            throughput_threshold=-0.05,
            latency_threshold=0.10,
            use_median=True,
            use_mann_whitney=True,
            use_cohens_d=True,
            use_quantile=True
        )
        
        # Simulated regression
        self.baseline_stats = {
            "test_throughput": {"mean": 100.0, "stddev": 5.0}
        }
        self.current_stats = {
            "test_throughput": {"mean": 85.0, "stddev": 5.0} # 15% drop
        }

    def test_rca_fallback_with_thermals(self):
        """
        Verify that when AI skill RCA invocation fails/NotImplemented,
        the Python RCADetector executes as a fallback and correctly attributes
        a thermal throttle.
        """
        anomalies = {
            "thermal_throttles": [{"zone": "cpu-0", "temp_c": 96.0, "event": "throttle"}]
        }
        
        result = _compare_and_rca(
            "test_fallback",
            self.baseline_stats,
            self.current_stats,
            self.detector,
            anomalies,
            skip_rca=False
        )
        
        # Verify the regression was detected
        self.assertTrue(result["regression_detected"])
        
        # Verify RCA fallback executed
        self.assertIn("test_throughput", result["rca"])
        
        rca_output = result["rca"]["test_throughput"]
        
        # The python fallback uses slightly different strings than our new COT
        # e.g., "DVFS / Thermal Throttling" instead of "Severe Thermal Throttling"
        self.assertEqual(rca_output["cause"], "DVFS / Thermal Throttling")
        self.assertEqual(rca_output["confidence"], "92%")
        
    def test_rca_fallback_with_oom(self):
        """
        Verify OOM kills take precedence in the fallback Python logic
        if no thermals are present.
        """
        anomalies = {
            # Python parser expects "oom_kills" list inside anomalies
            "oom_kills": ["system_server", "benchmark_app"]
        }
        
        result = _compare_and_rca(
            "test_fallback",
            self.baseline_stats,
            self.current_stats,
            self.detector,
            anomalies,
            skip_rca=False
        )
        
        rca_output = result["rca"]["test_throughput"]
        self.assertEqual(rca_output["cause"], "Severe Memory Pressure")
        self.assertEqual(rca_output["confidence"], "85%")

    def test_compare_and_rca_batches_metrics_together(self):
        """
        Verify the non-AI-skill path calls detect_regressions_batch once
        with every common metric, instead of looping detect_regressions
        per-metric (which would inflate the family-wise false-positive
        rate across many metrics at a flat p<0.05 cutoff).
        """
        baseline_stats = {
            "metric_a": {"mean": 100.0, "stddev": 5.0},
            "metric_b": {"mean": 50.0, "stddev": 2.0},
        }
        current_stats = {
            "metric_a": {"mean": 85.0, "stddev": 5.0},
            "metric_b": {"mean": 49.0, "stddev": 2.0},
        }

        with patch.object(
            RegressionDetector, "detect_regressions_batch",
            wraps=self.detector.detect_regressions_batch,
        ) as batch_spy:
            _compare_and_rca(
                "test_batching",
                baseline_stats,
                current_stats,
                self.detector,
                {},
                skip_rca=True,
            )

        batch_spy.assert_called_once()
        called_baseline, called_current = batch_spy.call_args[0][:2]
        self.assertEqual(set(called_baseline.keys()), {"metric_a", "metric_b"})
        self.assertEqual(set(called_current.keys()), {"metric_a", "metric_b"})

if __name__ == '__main__':
    unittest.main()
"""
test_outlier_detector_geekbench.py - Regression test for finding #4:
outlier_detector_geekbench.py's mad-zscore branch (triggered when
n_iterations > 15) must call the real OutlierDetectorBase method
(mad_zscore_method), not a nonexistent mad_method.

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.reporting.outlier_detector_geekbench import OutlierDetector


def _make_iteration(single_core, multi_core):
    return {
        "single_core_score": single_core,
        "single_core_integer_score": single_core,
        "single_core_float_score": single_core,
        "multi_core_score": multi_core,
        "multi_core_integer_score": multi_core,
        "multi_core_float_score": multi_core,
    }


class TestOutlierDetectorGeekbenchMad(unittest.TestCase):
    def test_mad_branch_does_not_raise_and_flags_extreme_outlier(self):
        """>15 iterations selects the 'mad' detection method. Previously
        this crashed with AttributeError (self.mad_method does not exist
        on OutlierDetectorBase)."""
        detector = OutlierDetector()
        iterations = [_make_iteration(1000.0, 4000.0) for _ in range(19)]
        # Inject one extreme outlier.
        iterations[10] = _make_iteration(50000.0, 200000.0)

        result = detector.run_detection(iterations, n_iterations=len(iterations))

        self.assertEqual(result["detection_method"], "mad")
        self.assertIn(10, result["discarded_indices"])


if __name__ == "__main__":
    unittest.main()

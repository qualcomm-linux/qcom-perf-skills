"""
test_outlier_detector_sysbench.py - Regression test for finding #6:
outlier_detector_sysbench.py's fairness metrics must match the key names
the producer (sysbench.py) actually writes onto each iteration dict
(events_stddev / execution_time_stddev_sec), not the never-written
fairness_events_stddev / fairness_time_stddev names.

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.reporting.outlier_detector_sysbench import OutlierDetector


def _make_iteration(events_stddev):
    return {
        "cpu_events_per_sec": 1000.0,
        "total_events": 50000.0,
        "latency_min_ms": 1.0,
        "latency_avg_ms": 2.0,
        "latency_p95_ms": 3.0,
        "latency_max_ms": 4.0,
        "events_stddev": events_stddev,
        "execution_time_stddev_sec": events_stddev / 100.0,
    }


class TestOutlierDetectorSysbenchFairness(unittest.TestCase):
    def test_fairness_metric_participates_in_detection(self):
        """A single engineered high-events_stddev iteration among otherwise
        stable (but not perfectly identical -- IQR needs some spread to
        compute a non-zero fence) iterations must actually be flagged --
        this fails if the detector's METRIC_THRESHOLDS/_active_metrics keys
        don't match what the iteration dicts contain (previously
        fairness_* vs events_stddev)."""
        detector = OutlierDetector()
        baseline = [0.40, 0.45, 0.50, 0.55, 0.60, 0.65]
        iterations = [_make_iteration(v) for v in baseline]
        iterations.insert(3, _make_iteration(50.0))  # extreme stddev outlier

        result = detector.run_detection(iterations, n_iterations=len(iterations))

        self.assertIn(3, result["discarded_indices"])
        self.assertIn("events_stddev", result["discarded_metrics"]["3"])

    def test_active_metrics_includes_fairness_keys_when_present(self):
        detector = OutlierDetector()
        iterations = [_make_iteration(0.5) for _ in range(5)]
        active = detector._active_metrics(iterations)
        self.assertIn("events_stddev", active)
        self.assertIn("execution_time_stddev_sec", active)


if __name__ == "__main__":
    unittest.main()

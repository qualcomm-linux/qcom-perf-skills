"""
test_run_rca_integration.py - End-to-end integration tests for the
regression-detection-and-rca skill's main orchestrator (run_rca.py),
covering all 3 comparison tiers plus explicit baseline comparison.

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import json
import sys
import tempfile
import shutil
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
_SKILL_SCRIPTS = Path(__file__).resolve().parent.parent / ".claude" / "skills" / "regression-detection-and-rca" / "scripts"
sys.path.insert(0, str(_SKILL_SCRIPTS))

import run_rca
import baseline_manager


def _make_coremark_results(score: float):
    return {
        "metadata": {"benchmark_name": "coremark"},
        "tests": {"coremark_default": {"throughput": [score]}},
    }


class TestRunRcaIntegration(unittest.TestCase):
    def setUp(self):
        self.output_dir = Path(tempfile.mkdtemp())
        self.config = {
            "active_device": "TEST-DEVICE",
            "telemetry_thresholds": {
                "devices": {
                    "TEST-DEVICE": {
                        "codename": "TestCodename",
                        "regression": {
                            "throughput_threshold_percent": -5,
                            "latency_threshold_percent": 10,
                            "stability_gate_cv_percent": 50,  # relaxed for single-value stats
                        }
                    }
                }
            }
        }

    def tearDown(self):
        shutil.rmtree(self.output_dir, ignore_errors=True)

    def _make_run_dir(self, benchmark, build_id, run_name, results, with_logs=False, thermal_throttle=False):
        run_dir = self.output_dir / benchmark / f"build_{build_id}" / run_name
        run_dir.mkdir(parents=True, exist_ok=True)
        with open(run_dir / "results.json", "w") as f:
            json.dump(results, f)
        if with_logs:
            logs_dir = run_dir / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            if thermal_throttle:
                (logs_dir / "dmesg_metrics_test.log").write_text("[1.0] thermal: cpu0 throttled\n")
        return run_dir

    def test_no_regression_no_history(self):
        """First-ever run: no prior runs/builds/baseline -> no comparisons fire."""
        run_dir = self._make_run_dir("coremark", "b1", "run_001", _make_coremark_results(1000.0))
        report = run_rca.run_rca_for_run(self.output_dir, "coremark", "b1", run_dir, self.config)
        self.assertFalse(report["any_regression_detected"])
        self.assertEqual(len(report["comparisons"]), 0)

    def test_tier2_run_level_regression_detected(self):
        """Two runs in the same build; second run regresses -> run-level comparison fires."""
        self._make_run_dir("coremark", "b1", "run_001", _make_coremark_results(1000.0))
        run_dir2 = self._make_run_dir("coremark", "b1", "run_002", _make_coremark_results(800.0))  # -20%

        report = run_rca.run_rca_for_run(self.output_dir, "coremark", "b1", run_dir2, self.config)
        self.assertTrue(report["any_regression_detected"])
        run_level_comparisons = [c for c in report["comparisons"] if c["label"].startswith("run-level")]
        self.assertEqual(len(run_level_comparisons), 1)
        self.assertTrue(run_level_comparisons[0]["regression_detected"])

    def test_tier2_no_regression_when_stable(self):
        """Two runs, second run within normal noise -> no regression flagged."""
        self._make_run_dir("coremark", "b1", "run_001", _make_coremark_results(1000.0))
        run_dir2 = self._make_run_dir("coremark", "b1", "run_002", _make_coremark_results(990.0))  # -1%

        report = run_rca.run_rca_for_run(self.output_dir, "coremark", "b1", run_dir2, self.config)
        run_level_comparisons = [c for c in report["comparisons"] if c["label"].startswith("run-level")]
        self.assertEqual(len(run_level_comparisons), 1)
        self.assertFalse(run_level_comparisons[0]["regression_detected"])

    def test_tier3_build_level_regression_detected(self):
        """Two builds, same run-index; second build regresses -> build-level comparison fires."""
        self._make_run_dir("coremark", "b1", "run_001", _make_coremark_results(1000.0))
        run_dir_b2 = self._make_run_dir("coremark", "b2", "run_001", _make_coremark_results(700.0))  # -30%

        report = run_rca.run_rca_for_run(self.output_dir, "coremark", "b2", run_dir_b2, self.config)
        build_level_comparisons = [c for c in report["comparisons"] if c["label"].startswith("build-level")]
        self.assertEqual(len(build_level_comparisons), 1)
        self.assertTrue(build_level_comparisons[0]["regression_detected"])

    def test_explicit_baseline_comparison(self):
        """Stored baseline exists -> baseline comparison always fires regardless of tier."""
        baseline_manager.store_baseline(
            self.output_dir, "coremark", "baseline_build",
            {"coremark_default": {"mean": 1000.0, "stddev": 5.0}}
        )
        run_dir = self._make_run_dir("coremark", "new_build", "run_001", _make_coremark_results(600.0))  # -40%

        report = run_rca.run_rca_for_run(self.output_dir, "coremark", "new_build", run_dir, self.config)
        baseline_comparisons = [c for c in report["comparisons"] if c["label"].startswith("baseline comparison")]
        self.assertEqual(len(baseline_comparisons), 1)
        self.assertTrue(baseline_comparisons[0]["regression_detected"])
        self.assertTrue(report["any_regression_detected"])

    def test_no_baseline_comparison_when_none_stored(self):
        run_dir = self._make_run_dir("coremark", "b1", "run_001", _make_coremark_results(1000.0))
        report = run_rca.run_rca_for_run(self.output_dir, "coremark", "b1", run_dir, self.config)
        baseline_comparisons = [c for c in report["comparisons"] if c["label"].startswith("baseline comparison")]
        self.assertEqual(len(baseline_comparisons), 0)

    def test_missing_logs_dir_produces_warning_not_crash(self):
        run_dir = self._make_run_dir("coremark", "b1", "run_001", _make_coremark_results(1000.0), with_logs=False)
        report = run_rca.run_rca_for_run(self.output_dir, "coremark", "b1", run_dir, self.config)
        self.assertTrue(any("No logs/ directory" in w for w in report["telemetry_warnings"]))

    def test_rca_report_written_to_disk(self):
        run_dir = self._make_run_dir("coremark", "b1", "run_001", _make_coremark_results(1000.0))
        run_rca.run_rca_for_run(self.output_dir, "coremark", "b1", run_dir, self.config)
        report_path = run_dir / "rca_report.json"
        self.assertTrue(report_path.exists())
        with open(report_path) as f:
            data = json.load(f)
        self.assertEqual(data["benchmark"], "coremark")

    def test_regression_with_thermal_throttle_rca_evidence(self):
        """Run-level regression WITH thermal throttle telemetry -> RCA identifies DVFS cause."""
        self._make_run_dir("coremark", "b1", "run_001", _make_coremark_results(1000.0))
        run_dir2 = self._make_run_dir(
            "coremark", "b1", "run_002", _make_coremark_results(800.0),
            with_logs=True, thermal_throttle=True
        )
        report = run_rca.run_rca_for_run(self.output_dir, "coremark", "b1", run_dir2, self.config)
        run_level = [c for c in report["comparisons"] if c["label"].startswith("run-level")][0]
        self.assertTrue(run_level["regression_detected"])
        rca_entries = run_level["rca"]
        self.assertTrue(len(rca_entries) > 0)
        first_rca = next(iter(rca_entries.values()))
        self.assertEqual(first_rca["cause"], "DVFS / Thermal Throttling")


if __name__ == "__main__":
    unittest.main()
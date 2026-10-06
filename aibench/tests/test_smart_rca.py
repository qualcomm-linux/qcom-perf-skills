"""
test_smart_rca.py - Tests for the 2-tier Smart RCA feature.
"""

import sys
import json
import unittest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

# Allow importing from src and scripts
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / ".claude" / "skills" / "regression-detection-and-rca" / "scripts"))

try:
    from run_rca import run_rca_for_run, _re_run_benchmark
    RUN_RCA_AVAILABLE = True
except ImportError:
    RUN_RCA_AVAILABLE = False


class TestSmartRCA(unittest.TestCase):
    def setUp(self):
        if not RUN_RCA_AVAILABLE:
            self.skipTest("run_rca.py not available in path")
            
        self.test_dir = tempfile.mkdtemp()
        self.output_dir = Path(self.test_dir) / "output"
        self.bench_dir = self.output_dir / "testbench"
        self.build_dir = self.bench_dir / "build_test1"
        self.build_dir.mkdir(parents=True)
        
        self.config = {
            "telemetry_thresholds": {
                "devices": {
                    "generic-fallback": {
                        "regression": {
                            "throughput_threshold_percent": -5,
                            "use_median_for_comparison": True
                        }
                    }
                }
            }
        }
        
        # Create 2 runs with a clear regression to trigger RCA
        self.run1_dir = self.build_dir / "run_20260101_001"
        self.run1_dir.mkdir()
        
        self.run2_dir = self.build_dir / "run_20260101_002"
        self.run2_dir.mkdir()
        
        results_run1 = {
            "metadata": {"benchmark_name": "testbench"},
            "tests": {
                "test_metric": {
                    "throughput": [100.0, 99.0, 101.0],
                    "iterations": [
                        {"cpu_events_per_sec": 100.0},
                        {"cpu_events_per_sec": 99.0},
                        {"cpu_events_per_sec": 101.0}
                    ]
                }
            }
        }
        
        # Run 2 is 50% slower (clear regression)
        results_run2 = {
            "metadata": {"benchmark_name": "testbench"},
            "tests": {
                "test_metric": {
                    "throughput": [50.0, 49.0, 51.0],
                    "iterations": [
                        {"cpu_events_per_sec": 50.0},
                        {"cpu_events_per_sec": 49.0},
                        {"cpu_events_per_sec": 51.0}
                    ]
                }
            }
        }
        
        with open(self.run1_dir / "results.json", "w") as f:
            json.dump(results_run1, f)
            
        with open(self.run2_dir / "results.json", "w") as f:
            json.dump(results_run2, f)
            
        self.mock_executor = MagicMock()
        self.mock_adb = MagicMock()
        self.bench_config = {"runs": 1, "iterations": 1}

    def tearDown(self):
        shutil.rmtree(self.test_dir)
        
    @patch('run_rca._re_run_benchmark')
    def test_smart_rca_triggers_rerun_on_regression(self, mock_rerun):
        """Test that detecting a regression triggers a Tier 1 re-run."""
        mock_rerun.return_value = True
        
        report = run_rca_for_run(
            output_dir=self.output_dir,
            benchmark_name="testbench",
            build_id="test1",
            run_dir=self.run2_dir,
            config=self.config,
            rca_mode="smart",
            serial_executor=self.mock_executor,
            adb_manager=self.mock_adb,
            bench_config=self.bench_config
        )
        
        # Should detect regression
        self.assertTrue(report["any_regression_detected"])
        
        # Should call _re_run_benchmark at least once (for Tier 1)
        self.assertTrue(mock_rerun.called)
        
        # First call should be for Tier 1
        args, kwargs = mock_rerun.call_args_list[0]
        self.assertEqual(args[6], 1) # tier is the 7th positional argument
        
        # Rerun directory should be .1
        expected_rerun_dir = self.run2_dir.parent / f"{self.run2_dir.name}.1"
        self.assertEqual(args[0], expected_rerun_dir)

    @patch('run_rca._re_run_benchmark')
    def test_smart_rca_skips_rerun_if_clean(self, mock_rerun):
        """Test that no re-runs happen if there's no regression."""
        # Make run 2 exactly the same as run 1
        shutil.copy(self.run1_dir / "results.json", self.run2_dir / "results.json")
        
        report = run_rca_for_run(
            output_dir=self.output_dir,
            benchmark_name="testbench",
            build_id="test1",
            run_dir=self.run2_dir,
            config=self.config,
            rca_mode="smart",
            serial_executor=self.mock_executor,
            adb_manager=self.mock_adb,
            bench_config=self.bench_config
        )
        
        self.assertFalse(report["any_regression_detected"])
        self.assertFalse(mock_rerun.called)

    def test_report_mode_skips_rca(self):
        """Test that report mode doesn't even try to do RCA."""
        report = run_rca_for_run(
            output_dir=self.output_dir,
            benchmark_name="testbench",
            build_id="test1",
            run_dir=self.run2_dir,
            config=self.config,
            rca_mode="report"
        )
        
        self.assertTrue(report["any_regression_detected"])
        
        # The rca dictionary should be empty because we skipped RCA
        for cmp in report["comparisons"]:
            if cmp.get("regression_detected"):
                self.assertEqual(cmp["rca"], {})

    @patch('run_rca.RCADetector.generate_rca')
    @patch('run_rca._re_run_benchmark')
    def test_confidence_parsing_handles_strings(self, mock_rerun, mock_gen_rca):
        """Test that the confidence score parsing handles string values correctly (Bug #2 fix)."""
        mock_rerun.return_value = True
        
        # Mock generate_rca to return string confidence percentages like the real one does
        mock_gen_rca.return_value = {
            "test_metric": {
                "cause": "Test Cause",
                "confidence": "55%",  # This caused the TypeError previously
                "evidence": []
            }
        }
        
        # Should not raise TypeError when processing the 55% confidence
        report = run_rca_for_run(
            output_dir=self.output_dir,
            benchmark_name="testbench",
            build_id="test1",
            run_dir=self.run2_dir,
            config=self.config,
            rca_mode="smart",
            serial_executor=self.mock_executor,
            adb_manager=self.mock_adb,
            bench_config=self.bench_config
        )
        
        # Mocking the folder creation before we run RCA so it finds the logs
        tier1_dir = self.run2_dir.parent / f"{self.run2_dir.name}.1"
        t1_logs = tier1_dir / "logs"
        t1_logs.mkdir(parents=True, exist_ok=True)
        
        # Write a dummy log file so telemetry_parser.parse_anomalies returns something
        with open(t1_logs / "dmesg_metrics_1.log", "w") as f:
            f.write("dummy log content")
            
        # Re-run RCA to trigger Tier 2
        report = run_rca_for_run(
            output_dir=self.output_dir,
            benchmark_name="testbench",
            build_id="test1",
            run_dir=self.run2_dir,
            config=self.config,
            rca_mode="smart",
            serial_executor=self.mock_executor,
            adb_manager=self.mock_adb,
            bench_config=self.bench_config
        )

        # Verify it triggered Tier 2 (since 55% < 85%)
        # call_count is 3 (1 from first call + 2 from second call)
        self.assertEqual(mock_rerun.call_count, 3)
        args_call_tier1 = mock_rerun.call_args_list[1][0]
        args_call_tier2 = mock_rerun.call_args_list[2][0]
        
        self.assertEqual(args_call_tier1[6], 1) # Tier 1
        self.assertEqual(args_call_tier2[6], 2) # Tier 2 (triggered by 55% confidence)

if __name__ == "__main__":
    unittest.main()

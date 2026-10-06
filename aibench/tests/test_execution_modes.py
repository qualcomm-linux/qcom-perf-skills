"""
test_execution_modes.py - Tests for --report-mode, --rca-mode, and --collect-telemetry

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import unittest
from unittest.mock import patch, MagicMock, mock_open
import sys
import os
import json
from pathlib import Path

# Add parent directory to path so we can import src
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../.claude/skills/regression-detection-and-rca/scripts')))

from main import parse_args
from run_rca import run_rca_for_run

class TestExecutionModesCLI(unittest.TestCase):
    
    @patch('sys.argv', ['main.py'])
    def test_default_mode(self):
        """Test that smart-rca is the default when no flags are provided."""
        args = parse_args()
        self.assertTrue(args.smart_rca)
        self.assertFalse(args.report_mode)
        self.assertFalse(args.rca_mode)
        self.assertFalse(args.collect_telemetry)
        self.assertFalse(getattr(args, '_telemetry_conflict', False))

    @patch('sys.argv', ['main.py', '--rca-mode'])
    def test_rca_mode_only(self):
        """Test passing --rca-mode sets the mode correctly."""
        args = parse_args()
        self.assertTrue(args.rca_mode)
        self.assertFalse(args.report_mode)
        self.assertFalse(args.collect_telemetry)
        self.assertFalse(getattr(args, '_telemetry_conflict', False))

    @patch('sys.argv', ['main.py', '--report-mode'])
    def test_report_mode_only(self):
        """Test passing --report-mode explicitly."""
        args = parse_args()
        self.assertTrue(args.report_mode)
        self.assertFalse(args.rca_mode)
        self.assertFalse(args.collect_telemetry)
        self.assertFalse(getattr(args, '_telemetry_conflict', False))

    @patch('sys.argv', ['main.py', '--rca-mode', '--collect-telemetry'])
    def test_rca_mode_with_telemetry(self):
        """Test RCA mode can successfully enable telemetry collection."""
        args = parse_args()
        self.assertTrue(args.rca_mode)
        self.assertTrue(args.collect_telemetry)
        self.assertFalse(getattr(args, '_telemetry_conflict', False))

    @patch('sys.argv', ['main.py', '--report-mode', '--collect-telemetry'])
    def test_report_mode_telemetry_conflict(self):
        """Test that --collect-telemetry is ignored and issues a warning in report-mode."""
        args = parse_args()
        self.assertTrue(args.report_mode)
        # Telemetry should be forcefully disabled
        self.assertFalse(args.collect_telemetry)
        # Conflict flag should be True
        self.assertTrue(getattr(args, '_telemetry_conflict', False))

    @patch('sys.argv', ['main.py', '--collect-telemetry'])
    def test_default_mode_telemetry_conflict(self):
        """Test that default smart-rca mode allows --collect-telemetry (no conflict)."""
        args = parse_args()
        self.assertTrue(args.smart_rca)
        self.assertFalse(args.report_mode)
        self.assertTrue(args.collect_telemetry)
        self.assertFalse(getattr(args, '_telemetry_conflict', False))

    @patch('sys.argv', ['main.py', '--report-mode', '--rca-mode'])
    def test_mode_mutual_exclusion(self):
        """Test that specifying both modes raises an error."""
        with self.assertRaises(SystemExit):
            parse_args()


class TestRunRCAExecution(unittest.TestCase):
    
    def setUp(self):
        self.config = {
            "telemetry_thresholds": {
                "active_device": "test_device",
                "devices": {
                    "test_device": {
                        "cpu_temp_max_c": 90,
                    }
                }
            }
        }

    @patch('src.reporting.telemetry_parser.TelemetryParser.parse_anomalies')
    @patch('pathlib.Path.exists')
    @patch('run_rca._load_json')
    @patch('builtins.open', new_callable=mock_open)
    def test_skip_rca_flag(self, mock_file, mock_load, mock_exists, mock_parse_anomalies):
        """Test that skip_rca=True does not generate RCA output."""
        mock_exists.return_value = True
        
        # Setup fake current results with dummy metrics to force a comparison
        mock_load.side_effect = [
            # current run results
            {"tests": {"test_1": {"iterations": [{"is_warmup": False, "score": 100}, {"is_warmup": False, "score": 100}]}}},
            # prev run results (Tier 1 run-level)
            {"tests": {"test_1": {"iterations": [{"is_warmup": False, "score": 200}, {"is_warmup": False, "score": 200}]}}},
            None # default baseline
        ]
        
        mock_parse_anomalies.return_value = {"warnings": []}
        # Fake directory structures for run_dirs
        with patch('pathlib.Path.glob') as mock_glob, patch('pathlib.Path.is_dir', return_value=True):
            # Mock glob to return two run directories to trigger Tier 1 Run-level comparison
            run1 = Path("/tmp/bench/build_1/run_1")
            run2 = Path("/tmp/bench/build_1/run_2")
            mock_glob.side_effect = [
                [run1, run2], # glob for run_dirs
                [] # glob for build_dirs
            ]
            
            # Execute with rca_mode="report" (successor of the old skip_rca=True)
            report = run_rca_for_run(
                output_dir=Path("/tmp"),
                benchmark_name="bench",
                build_id="1",
                run_dir=run2,
                config=self.config,
                rca_mode="report"
            )

            # Since rca_mode="report", rca object should be empty {} for all comparisons
            for comp in report["comparisons"]:
                self.assertEqual(comp["rca"], {})

    @patch('src.reporting.telemetry_parser.TelemetryParser.parse_anomalies')
    @patch('pathlib.Path.exists')
    @patch('run_rca._load_json')
    @patch('builtins.open', new_callable=mock_open)
    def test_tier_1_iteration_comparison_removed(self, mock_file, mock_load, mock_exists, mock_parse_anomalies):
        """Test that Tier 1 (Iteration-level) comparison does not occur."""
        mock_exists.return_value = True
        
        # Setup fake current results with multi-iterations that would previously trigger Tier 1
        mock_load.side_effect = [
            # current run results
            {"tests": {"test_1": {"iterations": [
                {"is_warmup": False, "score": 100},
                {"is_warmup": False, "score": 90},
                {"is_warmup": False, "score": 80}
            ]}}},
            None # default baseline
        ]
        
        mock_parse_anomalies.return_value = {"warnings": []}
        with patch('pathlib.Path.glob') as mock_glob, patch('pathlib.Path.is_dir', return_value=True):
            # Return only ONE run directory, so Tier 1 (Run-level) and Tier 2 (Build-level) are skipped
            run1 = Path("/tmp/bench/build_1/run_1")
            mock_glob.side_effect = [
                [run1], # glob for run_dirs
                [Path("/tmp/bench/build_1")] # glob for build_dirs
            ]
            
            report = run_rca_for_run(
                output_dir=Path("/tmp"),
                benchmark_name="bench",
                build_id="1",
                run_dir=run1,
                config=self.config,
                rca_mode="smart"
            )
            
            # There should be exactly ZERO comparisons in the report, since Iteration-level is removed,
            # and there are no previous runs or builds or baselines.
            self.assertEqual(len(report["comparisons"]), 0)


if __name__ == '__main__':
    unittest.main()
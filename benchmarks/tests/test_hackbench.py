import unittest
from unittest.mock import MagicMock, patch
import sys
import os

# Add parent directory to path so we can import src
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.benchmark.hackbench import Hackbench

class TestHackbench(unittest.TestCase):
    def setUp(self):
        self.mock_serial = MagicMock()
        
        self.config = {
            "command": "/usr/bin/hackbench",
            "iterations": 3,
            "test_params": {
                "sched_ipc_default": {
                    "category": "scheduler_ipc_default_test",
                    "-p": "",
                    "-T": "",
                    "-g": 4,
                    "-f": 8,
                    "-l": 150000,
                    "-s": 100
                }
            },
            "tests": ["sched_ipc_default"]
        }
        
        self.hackbench = Hackbench("hackbench", self.config, "/tmp/test")

    def test_build_command(self):
        params = self.config["test_params"]["sched_ipc_default"]
        cmd = self.hackbench._build_command("sched_ipc_default", params)
        
        # category should not be in the command
        self.assertNotIn("category", cmd)
        self.assertNotIn("scheduler_ipc_default_test", cmd)
        
        # Check command parts
        self.assertTrue(cmd.startswith("/usr/bin/hackbench"))
        self.assertIn("-p", cmd)
        self.assertIn("-T", cmd)
        self.assertIn("-g 4", cmd)
        self.assertIn("-f 8", cmd)
        self.assertIn("-l 150000", cmd)
        self.assertIn("-s 100", cmd)

    def test_calculate_total_messages(self):
        params = self.config["test_params"]["sched_ipc_default"]
        total = self.hackbench._calculate_total_messages(params)
        
        # 4 * 8 * 150000 = 4800000
        self.assertEqual(total, 4800000)
        
        # Test with missing parameters
        bad_params = {"-g": 4, "-f": 8}
        total = self.hackbench._calculate_total_messages(bad_params)
        self.assertEqual(total, 0)

    def test_parse_output(self):
        output = """Running in threaded mode with 4 groups using 16 file descriptors each (== 64 tasks)
Each sender will pass 150000 messages of 100 bytes
Time: 6.787"""
        
        params = self.config["test_params"]["sched_ipc_default"]
        res = self.hackbench._parse_output(output, 1, "sched_ipc_default", params)
        
        self.assertEqual(res.iteration, 1)
        self.assertEqual(res.test_name, "sched_ipc_default")
        self.assertEqual(res.total_messages, 4800000)
        self.assertEqual(res.time_taken, 6.787)
        # 4800000 / 6.787 = 707234.418741712
        self.assertAlmostEqual(res.throughput, 707234.42, places=2)
        
    def test_parse_output_failure(self):
        output = """Command failed"""
        
        params = self.config["test_params"]["sched_ipc_default"]
        res = self.hackbench._parse_output(output, 1, "sched_ipc_default", params)
        
        self.assertEqual(res.iteration, 1)
        self.assertEqual(res.total_messages, 4800000)
        # Should set a small non-zero time to avoid division by zero
        self.assertEqual(res.time_taken, 0.0001)
        # Throughput will be large but finite
        self.assertEqual(res.throughput, 4800000 / 0.0001)

    @patch('time.sleep')
    @patch('src.reporting.outlier_registry.OutlierDetectorRegistry.get')
    def test_run(self, mock_outlier_get, mock_sleep):
        # Mock serial output
        self.mock_serial.execute_command.return_value = "Time: 6.787"
        
        # Mock outlier detection
        mock_detector = MagicMock()
        def side_effect(iterations, **kwargs):
            return {"clean_iterations": iterations}
        mock_detector.run_detection.side_effect = side_effect
        mock_outlier_get.return_value = mock_detector
        
        results = self.hackbench.execute_lifecycle(self.mock_serial)
        
        # Check results
        self.assertIn("sched_ipc_default", results["tests"])
        
        res = results["tests"]["sched_ipc_default"]
        self.assertEqual(res["category"], "scheduler_ipc_default_test")
        # 3 regular iterations
        self.assertEqual(len(res["iterations"]), 3)
        self.assertEqual(res["clean_iterations_count"], 3)
        self.assertEqual(res["outlier_discarded_count"], 0)
        self.assertEqual(len(res["throughput"]), 3)
        # 4800000 / 6.787 = 707234.418741712
        self.assertAlmostEqual(res["throughput"][0], 707234.42, places=2)
        
        # Check sleep was called 2 times (between 3 iterations)
        self.assertEqual(mock_sleep.call_count, 2)
        mock_sleep.assert_called_with(5)

if __name__ == '__main__':
    unittest.main()
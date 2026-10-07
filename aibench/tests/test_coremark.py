"""
test_coremark.py - Unit tests for Coremark benchmark

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path
import sys
import os

# Add parent directory to path so we can import src
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.benchmark.coremark import CoremarkBenchmark

class TestCoremark(unittest.TestCase):
    
    def setUp(self):
        """Set up test fixtures"""
        self.config = {
            "command": "/usr/bin/coremark",
            "iterations": 3,
            "test_params": {
                "default": {
                    "category": "performance",
                    "--iterations": "0"
                }
            },
            "tests": ["default"]
        }
        self.run_dir = Path("/tmp/test_run")
        self.benchmark = CoremarkBenchmark("coremark", self.config, self.run_dir)
    
    def test_build_command(self):
        """Test command building"""
        params = {"--iterations": "0", "--verbose": "1"}
        cmd = self.benchmark._build_command("default", params)
        self.assertIn("/usr/bin/coremark", cmd)
        self.assertIn("--iterations 0", cmd)
        self.assertIn("--verbose 1", cmd)
    
    def test_parse_output(self):
        """Test output parsing"""
        output = """
        2K performance run parameters for coremark.
        CoreMark Size    : 666
        Total ticks      : 12958
        Total time (secs): 12.958788
        Iterations/Sec   : 23150.312601
        Iterations       : 300000
        Compiler version : GCC11.2.0
        Compiler flags   : -O3 -fno-common -funroll-loops -finline-functions
        Memory location  : Please put data memory location here
        seedcrc          : 0x0
        [0]crclist       : 0xe714
        [0]crcmatrix     : 0x1fd7
        [0]crcstate      : 0x8e3a
        [0]crcfinal      : 0xa14c
        Correct operation validated. See readme.txt for run and reporting rules.
        CoreMark 1.0 : 23150.312601 / GCC11.2.0 -O3 -fno-common -funroll-loops -finline-functions / Heap
        """
        result = self.benchmark._parse_output(output, 1, "default")
        self.assertAlmostEqual(result.score, 23150.31, places=1)
        self.assertAlmostEqual(result.iterations_per_sec, 23150.31, places=1)
        self.assertAlmostEqual(result.time_taken, 12.96, places=1)
    
    @patch('time.sleep')
    @patch('src.reporting.outlier_registry.OutlierDetectorRegistry.get')
    def test_execute_lifecycle(self, mock_outlier_get, mock_sleep):
        """Test full execution lifecycle"""
        # Mock serial executor
        mock_executor = MagicMock()
        mock_executor.execute_command.return_value = """
        Total time (secs): 12.958788
        Iterations/Sec   : 23150.312601
        CoreMark 1.0 : 23150.312601 / GCC11.2.0
        """
        
        # Mock ADB manager
        mock_adb = Mock()
        mock_adb.get_build_id.return_value = "test_build"
        
        # Mock outlier detector
        mock_detector = MagicMock()
        def side_effect(iterations, **kwargs):
            return {"clean_iterations": iterations}
        mock_detector.run_detection.side_effect = side_effect
        mock_outlier_get.return_value = mock_detector
        
        # Execute
        results = self.benchmark.execute_lifecycle(mock_executor, mock_adb)
        
        # Verify
        self.assertIn("metadata", results)
        self.assertIn("tests", results)
        self.assertEqual(results["metadata"]["benchmark"], "coremark")
        self.assertIn("default", results["tests"])
        self.assertEqual(len(results["tests"]["default"]["iterations"]), 3)

if __name__ == "__main__":
    unittest.main()
"""
test_geekbench.py - Unit tests for Geekbench benchmark

Tests command building, output parsing, and execution flow.

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import unittest
from unittest.mock import Mock, MagicMock, patch
from pathlib import Path
import sys

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.benchmark.geekbench import GeekbenchBenchmark, GeekbenchIterationResult


class TestGeekbenchBenchmark(unittest.TestCase):
    """Test suite for Geekbench benchmark"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.config = {
            "command": "/root/geekbench_aarch64",
            "iterations": 3,
            "test_params": {
                "geekbench_cpu": {
                    "category": "cpu_benchmark",
                    "--no-upload": "",
                    "--cpu": ""
                }
            },
            "tests": ["geekbench_cpu"]
        }
        self.run_dir = Path("/tmp/test_run")
        self.benchmark = GeekbenchBenchmark("geekbench", self.config, self.run_dir)
    
    def test_initialization(self):
        """Test benchmark initialization"""
        self.assertEqual(self.benchmark.name, "geekbench")
        self.assertEqual(self.benchmark.command_base, "/root/geekbench_aarch64")
        self.assertEqual(self.benchmark.iterations, 3)
        self.assertEqual(len(self.benchmark.tests_to_run), 1)
        self.assertIn("geekbench_cpu", self.benchmark.tests_to_run)
    
    def test_build_command(self):
        """Test command building"""
        params = {
            "category": "cpu_benchmark",
            "--no-upload": "",
            "--cpu": ""
        }
        cmd = self.benchmark._build_command("geekbench_cpu", params)
        
        self.assertIn("/root/geekbench_aarch64", cmd)
        self.assertIn("--no-upload", cmd)
        self.assertIn("--cpu", cmd)
        self.assertNotIn("category", cmd)
    
    def test_parse_output_valid(self):
        """Test parsing valid Geekbench output"""
        sample_output = """
Geekbench 6.5.0 Corporate : https://www.geekbench.com/

System Information
  Operating System              Qualcomm Linux Reference Distro 2.0
  Kernel                        Linux 6.18.37-02225-g3167b1238438-dirty aarch64

Single-Core
  File Compression               1128             162.0 MB/sec
  Integer Score                 1171
  Floating Point Score          1044

Multi-Core
  File Compression               3347             480.7 MB/sec
  Integer Score                 5187
  Floating Point Score          5967

Benchmark Summary
  Single-Core Score             1125
    Integer Score                 1171
    Floating Point Score          1044
  Multi-Core Score              5448
    Integer Score                 5187
    Floating Point Score          5967
"""
        
        result = self.benchmark._parse_output(sample_output, 1, "geekbench_cpu")
        
        self.assertIsInstance(result, GeekbenchIterationResult)
        self.assertEqual(result.iteration, 1)
        self.assertEqual(result.test_name, "geekbench_cpu")
        self.assertEqual(result.single_core_score, 1125.0)
        self.assertEqual(result.single_core_integer_score, 1171.0)
        self.assertEqual(result.single_core_float_score, 1044.0)
        self.assertEqual(result.multi_core_score, 5448.0)
        self.assertEqual(result.multi_core_integer_score, 5187.0)
        self.assertEqual(result.multi_core_float_score, 5967.0)
    
    def test_parse_output_missing_scores(self):
        """Test parsing output with missing scores"""
        incomplete_output = """
Geekbench 6.5.0

Benchmark Summary
  Single-Core Score             1125
"""
        
        result = self.benchmark._parse_output(incomplete_output, 1, "geekbench_cpu")
        
        # Should still create result but with zeros for missing values
        self.assertEqual(result.single_core_score, 1125.0)
        self.assertEqual(result.multi_core_score, 0.0)
    
    @patch('src.benchmark.geekbench.setup_telemetry')
    def test_setup(self, mock_setup_telemetry):
        """Test setup phase"""
        mock_setup_telemetry.return_value = "20260917_220000"
        
        serial_executor = Mock()
        adb_manager = Mock()
        
        self.benchmark.config['collect_telemetry'] = True
        self.benchmark.setup(serial_executor, adb_manager)
        
        mock_setup_telemetry.assert_called_once_with(adb_manager)
        self.assertEqual(self.benchmark.telemetry_timestamp, "20260917_220000")
    
    @patch('src.benchmark.geekbench.teardown_telemetry')
    def test_teardown(self, mock_teardown_telemetry):
        """Test teardown phase"""
        serial_executor = Mock()
        adb_manager = Mock()
        self.benchmark.telemetry_timestamp = "20260917_220000"
        
        self.benchmark.teardown(serial_executor, adb_manager)
        
        mock_teardown_telemetry.assert_called_once_with(
            adb_manager, 
            self.run_dir, 
            "20260917_220000"
        )
    
    @patch('src.benchmark.geekbench.OutlierDetectorRegistry')
    @patch('src.benchmark.geekbench.time.sleep')
    def test_execute_lifecycle(self, mock_sleep, mock_registry):
        """Test full lifecycle execution"""
        # Mock serial executor
        serial_executor = Mock()
        serial_executor.execute_command.return_value = """
Benchmark Summary
  Single-Core Score             1125
    Integer Score                 1171
    Floating Point Score          1044
  Multi-Core Score              5448
    Integer Score                 5187
    Floating Point Score          5967
"""
        
        # Mock ADB manager
        adb_manager = Mock()
        adb_manager.get_build_id.return_value = "test_build_123"
        
        # Mock outlier detector
        mock_detector = Mock()
        mock_detector.run_detection.return_value = {
            "clean_iterations": [{"single_core_score": 1125, "multi_core_score": 5448}],
            "discarded_indices": []
        }
        mock_registry.get.return_value = mock_detector
        
        # Execute
        results = self.benchmark.execute_lifecycle(serial_executor, adb_manager)
        
        # Verify results structure
        self.assertIn("metadata", results)
        self.assertIn("tests", results)
        self.assertEqual(results["metadata"]["benchmark_name"], "geekbench")
        self.assertIn("geekbench_cpu", results["tests"])
        
        test_results = results["tests"]["geekbench_cpu"]
        self.assertIn("single_core_scores", test_results)
        self.assertIn("multi_core_scores", test_results)
        self.assertEqual(len(test_results["iterations"]), 3)


class TestGeekbenchIterationResult(unittest.TestCase):
    """Test GeekbenchIterationResult dataclass"""
    
    def test_creation(self):
        """Test creating iteration result"""
        result = GeekbenchIterationResult(
            iteration=1,
            test_name="geekbench_cpu",
            single_core_score=1125.0,
            single_core_integer_score=1171.0,
            single_core_float_score=1044.0,
            multi_core_score=5448.0,
            multi_core_integer_score=5187.0,
            multi_core_float_score=5967.0
        )
        
        self.assertEqual(result.iteration, 1)
        self.assertEqual(result.single_core_score, 1125.0)
        self.assertEqual(result.multi_core_score, 5448.0)


if __name__ == '__main__':
    unittest.main()
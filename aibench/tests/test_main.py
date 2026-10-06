"""
test_main.py - Unit tests for main.py argument parsing and logic

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import unittest
from unittest.mock import patch, MagicMock
import sys
import os
from pathlib import Path

# Add parent directory to path so we can import main
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from main import parse_args, parse_unknown_args

class TestMainParsing(unittest.TestCase):
    
    @patch('sys.argv', ['main.py', '-b', 'sysbench'])
    def test_single_benchmark_parsing(self):
        """Test parsing a single benchmark"""
        args = parse_args()
        self.assertEqual(args.benchmark, 'sysbench')
        self.assertEqual(args.benchmarks, ['sysbench'])
        
    @patch('sys.argv', ['main.py', '-b', 'hackbench,sysbench'])
    def test_multiple_benchmark_parsing(self):
        """Test parsing multiple comma-separated benchmarks"""
        args = parse_args()
        self.assertEqual(args.benchmark, 'hackbench,sysbench')
        self.assertEqual(args.benchmarks, ['hackbench', 'sysbench'])
        
    @patch('sys.argv', ['main.py', '--benchmark=coremark, tiobench , sysbench'])
    def test_whitespace_trimming(self):
        """Test whitespace trimming around commas"""
        args = parse_args()
        self.assertEqual(args.benchmarks, ['coremark', 'tiobench', 'sysbench'])
        
    @patch('sys.argv', ['main.py'])
    def test_no_benchmark_parsing(self):
        """Test when no benchmark is specified"""
        args = parse_args()
        self.assertIsNone(args.benchmark)
        self.assertIsNone(args.benchmarks)
        
    @patch('sys.argv', ['main.py', '-b', 'c,b,a'])
    def test_order_preservation(self):
        """Test that the order of benchmarks is preserved"""
        args = parse_args()
        self.assertEqual(args.benchmarks, ['c', 'b', 'a'])
        
    def test_parse_unknown_args(self):
        """Test parsing of dynamic parameter overrides"""
        unknown = ['--threads=4', '--time=10', '--verbose', '1']
        overrides = parse_unknown_args(unknown)
        self.assertEqual(overrides['--threads'], '4')
        self.assertEqual(overrides['--time'], '10')
        self.assertEqual(overrides['--verbose'], '1')
        
    @patch('sys.argv', ['main.py', '--default-connection', '--ssh-connection'])
    def test_conflicting_connections(self):
        """Test that conflicting connection types raise an error"""
        # argparse.error exits the program, so we catch SystemExit
        with self.assertRaises(SystemExit):
            # We need to temporarily redirect stderr to avoid polluting test output
            with patch('sys.stderr', new=MagicMock()):
                parse_args()
                
    @patch('sys.argv', ['main.py', '-t', 'sysbench_cpu_prime_single_test'])
    def test_single_test_parsing(self):
        """Test parsing a single test argument"""
        args = parse_args()
        self.assertEqual(args.tests, ['sysbench_cpu_prime_single_test'])
        
    @patch('sys.argv', ['main.py', '--test', 'test1,test2,test3'])
    def test_multiple_comma_separated_test_parsing(self):
        """Test parsing multiple comma-separated tests"""
        args = parse_args()
        self.assertEqual(args.tests, ['test1', 'test2', 'test3'])
        
    @patch('sys.argv', ['main.py', '--test', 'test1, test2 , test3'])
    def test_multiple_comma_separated_with_spaces_test_parsing(self):
        """Test parsing multiple comma-separated tests with spaces"""
        args = parse_args()
        self.assertEqual(args.tests, ['test1', 'test2', 'test3'])
        
    @patch('sys.argv', ['main.py', '--test='])
    def test_empty_test_parameter(self):
        """Test parsing empty test parameter defaults to None"""
        args = parse_args()
        self.assertIsNone(args.tests)

    @patch('sys.argv', ['main.py', '--test', 't1,t2', 't3', 't4, t5'])
    def test_mixed_space_and_comma_separated_test_parsing(self):
        """Test parsing mixed space and comma separated tests"""
        args = parse_args()
        self.assertEqual(args.tests, ['t1', 't2', 't3', 't4', 't5'])

if __name__ == "__main__":
    unittest.main()

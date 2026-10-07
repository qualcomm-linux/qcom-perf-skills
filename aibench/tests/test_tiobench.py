import unittest
from unittest.mock import MagicMock, patch
import sys
import os

# Add parent directory to path so we can import src
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.benchmark.tiobench import TiobenchBenchmark, TiotestParser

class TestTiobench(unittest.TestCase):
    def setUp(self):
        self.mock_serial = MagicMock()
        self.mock_adb = MagicMock()
        
        self.config = {
            "iterations": 1,
            "test_params": {
                "sequential": {
                    "-t": 8,
                    "-d": "/opt/",
                    "-f": 256,
                    "-b": 4096,
                    "-k": "1,3"
                },
                "random": {
                    "-t": 8,
                    "-d": "/opt/",
                    "-f": 64,
                    "-b": 4096,
                    "-k": "0,2",
                    "-r": 12500
                }
            },
            "tests": ["sequential", "random"]
        }
        
        self.tiobench = TiobenchBenchmark("tiobench", self.config, "/tmp/test")
        self.parser = TiotestParser()

    def test_parse_output_sequential(self):
        output = """# Running: tiotest -t 8 -d /opt/ -f 256 -b 4096 -k3 -k1
Tiotest results for 8 concurrent io threads:
,----------------------------------------------------------------------.
| Item                  | Time     | Rate         | Usr CPU  | Sys CPU |
+-----------------------+----------+--------------+----------+---------+
| Write        2048 MBs |    5.9 s | 346.574 MB/s |  14.1 %  | 238.3 % |
| Read         2048 MBs |    0.1 s | 21662.101 MB/s | 1047.2 %  | 4547.0 % |
`----------------------------------------------------------------------'
Tiotest latency results:
,-------------------------------------------------------------------------.
| Item         | Average latency | Maximum latency | % >2 sec | % >10 sec |
+--------------+-----------------+-----------------+----------+-----------+
| Write        |        0.003 ms |        0.515 ms |  0.00000 |   0.00000 |
| Read         |        0.001 ms |        8.020 ms |  0.00000 |   0.00000 |
|--------------+-----------------+-----------------+----------+-----------|
| Total        |        0.002 ms |        8.020 ms |  0.00000 |   0.00000 |
`--------------+-----------------+-----------------+----------+-----------'
"""
        results = self.parser.parse(output)
        
        self.assertIn("4096", results)
        res = results["4096"]
        
        # Performance
        self.assertEqual(res.performance.write_rate_mbs, 346.574)
        self.assertEqual(res.performance.write_usr_cpu, 14.1)
        self.assertEqual(res.performance.write_sys_cpu, 238.3)
        self.assertEqual(res.performance.read_rate_mbs, 21662.101)
        self.assertEqual(res.performance.read_usr_cpu, 1047.2)
        self.assertEqual(res.performance.read_sys_cpu, 4547.0)
        
        # Latency
        self.assertEqual(res.latency["write"].avg_ms, 0.003)
        self.assertEqual(res.latency["write"].max_ms, 0.515)
        self.assertEqual(res.latency["read"].avg_ms, 0.001)
        self.assertEqual(res.latency["read"].max_ms, 8.020)

    def test_parse_output_random(self):
        output = """# Running: tiotest -t 8 -d /opt/ -f 64 -b 4096 -k2 -k0 -r 12500
Tiotest results for 8 concurrent io threads:
,----------------------------------------------------------------------.
| Item                  | Time     | Rate         | Usr CPU  | Sys CPU |
+-----------------------+----------+--------------+----------+---------+
| Random Write  391 MBs |    1.3 s | 292.372 MB/s |  11.1 %  | 1190.2 % |
| Random Read   391 MBs |    0.1 s | 5653.203 MB/s | 426.4 %  | 3159.5 % |
`----------------------------------------------------------------------'
Tiotest latency results:
,-------------------------------------------------------------------------.
| Item         | Average latency | Maximum latency | % >2 sec | % >10 sec |
+--------------+-----------------+-----------------+----------+-----------+
| Random Write |        0.005 ms |        0.335 ms |  0.00000 |   0.00000 |
| Random Read  |        0.004 ms |        8.118 ms |  0.00000 |   0.00000 |
|--------------+-----------------+-----------------+----------+-----------|
| Total        |        0.005 ms |        8.118 ms |  0.00000 |   0.00000 |
`--------------+-----------------+-----------------+----------+-----------'
"""
        results = self.parser.parse(output)
        
        self.assertIn("4096", results)
        res = results["4096"]
        
        # Performance
        self.assertEqual(res.performance.write_rate_mbs, 292.372)
        self.assertEqual(res.performance.write_usr_cpu, 11.1)
        self.assertEqual(res.performance.write_sys_cpu, 1190.2)
        self.assertEqual(res.performance.read_rate_mbs, 5653.203)
        self.assertEqual(res.performance.read_usr_cpu, 426.4)
        self.assertEqual(res.performance.read_sys_cpu, 3159.5)
        
        # Latency
        self.assertEqual(res.latency["write"].avg_ms, 0.005)
        self.assertEqual(res.latency["write"].max_ms, 0.335)
        self.assertEqual(res.latency["read"].avg_ms, 0.004)
        self.assertEqual(res.latency["read"].max_ms, 8.118)

    def test_build_command(self):
        # sequential
        cmd_seq = self.tiobench._build_command("sequential", self.config["test_params"]["sequential"])
        self.assertEqual(cmd_seq, "tiotest -t 8 -d /opt/ -f 256 -b 4096 -k1 -k3")
        
        # random
        cmd_rand = self.tiobench._build_command("random", self.config["test_params"]["random"])
        self.assertEqual(cmd_rand, "tiotest -t 8 -d /opt/ -f 64 -b 4096 -k0 -k2 -r 12500")

    @patch('src.benchmark.tiobench.open')
    @patch('src.benchmark.tiobench.Path.mkdir')
    def test_run(self, mock_mkdir, mock_open):
        self.mock_serial.execute_command.return_value = """Tiotest results for 8 concurrent io threads:
,----------------------------------------------------------------------.
| Item                  | Time     | Rate         | Usr CPU  | Sys CPU |
+-----------------------+----------+--------------+----------+---------+
| Write        2048 MBs |    5.9 s | 346.574 MB/s |  14.1 %  | 238.3 % |
| Read         2048 MBs |    0.1 s | 21662.101 MB/s | 1047.2 %  | 4547.0 % |
`----------------------------------------------------------------------'
Tiotest latency results:
,-------------------------------------------------------------------------.
| Item         | Average latency | Maximum latency | % >2 sec | % >10 sec |
+--------------+-----------------+-----------------+----------+-----------+
| Write        |        0.003 ms |        0.515 ms |  0.00000 |   0.00000 |
| Read         |        0.001 ms |        8.020 ms |  0.00000 |   0.00000 |
|--------------+-----------------+-----------------+----------+-----------|
| Total        |        0.002 ms |        8.020 ms |  0.00000 |   0.00000 |
`--------------+-----------------+-----------------+----------+-----------'"""
        
        self.mock_adb.get_os_release_info.return_value = {"pretty_name": "TestOS", "build_id": "12345"}
        
        results = self.tiobench.run(self.mock_serial, self.mock_adb)
        
        self.assertIn("metadata", results)
        self.assertEqual(results["metadata"]["benchmark_name"], "tiobench")
        self.assertEqual(results["metadata"]["iterations_run"], 3)
        self.assertEqual(results["metadata"]["os_pretty_name"], "TestOS")
        
        self.assertIn("sequential", results)
        self.assertIn("random", results)
        self.assertIn("iterations", results["sequential"])
        self.assertEqual(len(results["sequential"]["iterations"]), 3)

if __name__ == '__main__':
    unittest.main()
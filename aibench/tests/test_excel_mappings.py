"""
test_excel_mappings.py - Regression tests for findings #8 and #9:
excel_generator.py's _infer_unit() (backed by excel_mappings.UNIT_PATTERNS)
must resolve osbench keys to microseconds (not "ops/sec") and
hackbench/sched_ipc throughput keys to "msg/sec" (not "sec").

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.reporting.excel_generator import ExcelGenerator


class TestExcelUnitInference(unittest.TestCase):
    def test_osbench_key_resolves_to_microseconds(self):
        self.assertEqual(ExcelGenerator._infer_unit("osbench_launch_programs"), "µs")
        self.assertNotEqual(ExcelGenerator._infer_unit("osbench_launch_programs"), "ops/sec")

    def test_hackbench_sched_ipc_key_resolves_to_msg_per_sec(self):
        self.assertEqual(ExcelGenerator._infer_unit("sched_ipc_default"), "msg/sec")
        self.assertNotEqual(ExcelGenerator._infer_unit("sched_ipc_default"), "sec")


if __name__ == "__main__":
    unittest.main()

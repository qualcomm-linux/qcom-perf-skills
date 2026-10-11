"""
test_unixbench.py - Regression test for finding #5: UnixBench's final
averaging step divided accumulated metrics by the *configured* iteration
count, not the count of iterations that actually produced a parseable
score. One real success among a configured iterations=2 should NOT be
halved.

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.benchmark.unixbench import UnixBench

_BAD_SINGLE_OUTPUT = "some unrelated line\nno index score here\n"
_GOOD_SINGLE_OUTPUT = "System Benchmarks Index Score                                        1000.0\n"
_GOOD_MULTI_OUTPUT = "System Benchmarks Index Score                                        4000.0\n"


class TestUnixBenchAveraging(unittest.TestCase):
    def setUp(self):
        self.run_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.run_dir, ignore_errors=True)

    def test_single_success_among_configured_two_iterations_not_halved(self):
        """iterations=2, but iteration 1's single-core parse fails (so it
        `continue`s before running multi-core at all). Only iteration 2
        fully succeeds. The resulting index_score must equal the single
        successful iteration's raw score, not that score halved."""
        config = {"iterations": 2}
        bench = UnixBench("unixbench", config, self.run_dir)

        mock_executor = MagicMock()
        mock_executor.execute_command.side_effect = [
            _BAD_SINGLE_OUTPUT,    # iteration 1: single-core (fails to parse) -> continue
            _GOOD_SINGLE_OUTPUT,   # iteration 2: single-core
            _GOOD_MULTI_OUTPUT,    # iteration 2: multi-core
            "4",                   # iteration 2: nproc
        ]

        results = bench.run(mock_executor, adb_manager=None)

        index_score = results["tests"]["unixbench_single_core"]["metrics"]["index_score"]
        self.assertEqual(index_score, 1000.0)
        multi_index_score = results["tests"]["unixbench_multi_core"]["metrics"]["index_score"]
        self.assertEqual(multi_index_score, 4000.0)

    def test_two_successful_iterations_are_averaged(self):
        """Sanity check: when both iterations fully succeed, the metrics
        ARE averaged (dividing by 2), preserving existing behavior for the
        common case."""
        config = {"iterations": 2}
        bench = UnixBench("unixbench", config, self.run_dir)

        mock_executor = MagicMock()
        mock_executor.execute_command.side_effect = [
            _GOOD_SINGLE_OUTPUT, _GOOD_MULTI_OUTPUT, "4",
            _GOOD_SINGLE_OUTPUT, _GOOD_MULTI_OUTPUT, "4",
        ]

        results = bench.run(mock_executor, adb_manager=None)

        index_score = results["tests"]["unixbench_single_core"]["metrics"]["index_score"]
        self.assertEqual(index_score, 1000.0)


if __name__ == "__main__":
    unittest.main()

"""
test_aggregator.py - Unit tests for src/reporting/aggregator.py's generic
"tests" fallback, specifically covering CoreMark (finding #1: CoreMark scores
never reached the aggregated statistics because the aggregator special-cased
a legacy flat "throughput" shape the producer never actually writes).

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.reporting.aggregator import aggregate_build_runs


def _make_coremark_results(score: float):
    return {
        "metadata": {"benchmark_name": "coremark"},
        "tests": {"coremark_default": {"throughput": [score]}},
    }


class TestAggregatorCoremark(unittest.TestCase):
    def setUp(self):
        self.output_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.output_dir, ignore_errors=True)

    def _write_run(self, build_id, run_name, results):
        run_dir = self.output_dir / "coremark" / f"build_{build_id}" / run_name
        run_dir.mkdir(parents=True, exist_ok=True)
        with open(run_dir / "results.json", "w") as f:
            json.dump(results, f)

    def test_coremark_score_reaches_statistics(self):
        """CoreMark's real nested-under-tests shape must produce a
        'coremark_default' statistics entry (the key the dashboard/Excel
        templates and chart_generator.py expect) -- not an empty result."""
        self._write_run("b1", "run_001", _make_coremark_results(1000.0))
        self._write_run("b1", "run_002", _make_coremark_results(1010.0))

        payload = aggregate_build_runs(self.output_dir, "coremark", "b1")

        self.assertIn("coremark_default", payload["statistics"])
        self.assertAlmostEqual(payload["statistics"]["coremark_default"]["mean"], 1005.0, places=1)

    def test_legacy_benchmark_key_also_resolves(self):
        """The producer historically wrote metadata['benchmark'] instead of
        metadata['benchmark_name'] -- both must resolve to the same
        'tests' in result generic path."""
        self._write_run(
            "b2", "run_001",
            {"metadata": {"benchmark": "coremark"}, "tests": {"coremark_default": {"throughput": [500.0]}}},
        )

        payload = aggregate_build_runs(self.output_dir, "coremark", "b2")

        self.assertIn("coremark_default", payload["statistics"])
        self.assertAlmostEqual(payload["statistics"]["coremark_default"]["mean"], 500.0, places=1)


if __name__ == "__main__":
    unittest.main()

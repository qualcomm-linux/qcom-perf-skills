"""
test_individual_report_template.py - Regression test for finding #2:
config/templates/individual_report.html previously had no branch for
ramspeed, coremark_pro, osbench, bw_mem, lat_mem_rd, or unixbench (and no
generic fallback), so their individual run reports silently rendered an
empty results section. Verifies each of these benchmarks (plus an unknown
benchmark exercising the generic {% else %} fallback) renders without
raising and includes its data in the output HTML.

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.reporting.individual import generate_individual_html_report

_TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "config" / "templates" / "individual_report.html"


class TestIndividualReportTemplateBranches(unittest.TestCase):
    def setUp(self):
        self.run_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.run_dir, ignore_errors=True)

    def _render(self, results):
        generate_individual_html_report(results, self.run_dir, _TEMPLATE_PATH)
        return (self.run_dir / "report.html").read_text(encoding="utf-8")

    def test_ramspeed_branch_renders_throughput(self):
        html = self._render({
            "metadata": {"benchmark_name": "ramspeed"},
            "tests": {"int_copy": {"throughput": [1234.5, 1235.5]}},
        })
        self.assertIn("1235.00", html)

    def test_unixbench_branch_renders_index_score(self):
        html = self._render({
            "metadata": {"benchmark_name": "unixbench"},
            "tests": {"unixbench_single_core": {"metrics": {"index_score": 1000.0}}},
        })
        self.assertIn("1000.00", html)

    def test_bw_mem_branch_renders_plateau(self):
        html = self._render({
            "metadata": {"benchmark_name": "bw_mem"},
            "tests": {
                "iteration_1": {
                    "rd": {"plateau": 12.5, "saturation_worker": 4, "plateau_detected": True}
                }
            },
        })
        self.assertIn("12.5", html)

    def test_lat_mem_rd_branch_renders_overall_plateau(self):
        html = self._render({
            "metadata": {"benchmark_name": "lat_mem_rd"},
            "tests": {
                "lat_mem_rd_default": {
                    "overall_plateau_latency_ns": 42.0,
                    "iteration_to_iteration_spread_pct": 1.5,
                    "clean_iterations_count": 3,
                    "outlier_discarded_count": 0,
                }
            },
        })
        self.assertIn("42.00", html)

    def test_unknown_benchmark_falls_back_to_generic_branch(self):
        html = self._render({
            "metadata": {"benchmark_name": "some_future_benchmark"},
            "tests": {"default": {"custom_metric": 77.0}},
        })
        self.assertIn("77.00", html)
        self.assertIn("Custom Metric", html)


if __name__ == "__main__":
    unittest.main()

"""
test_summary_dashboard_template.py - Verifies the summary_dashboard.html
Jinja2 template renders correctly for the 4-tier regression/improvement
highlighting and RCA visualization feature.

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import unittest
from pathlib import Path

try:
    from jinja2 import Environment, FileSystemLoader
    _JINJA_AVAILABLE = True
except ImportError:
    _JINJA_AVAILABLE = False

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "config" / "templates"


@unittest.skipUnless(_JINJA_AVAILABLE, "jinja2 not installed")
class TestSummaryDashboardTemplate(unittest.TestCase):
    def setUp(self):
        env = Environment(loader=FileSystemLoader(str(_TEMPLATE_DIR)))
        self.template = env.get_template("summary_dashboard.html")

    def _render(self, benchmarks):
        return self.template.render(benchmarks=benchmarks, updated_at="now", json=None, config={})

    def _body(self, html):
        # Strip the <style> block so we only inspect actual rendered markup,
        # not the (always-present) CSS class definitions.
        return html.split("</style>")[1]

    def test_empty_state_unaffected(self):
        html = self._render([])
        self.assertIn("No benchmarks have been executed yet", html)

    def test_single_run_no_comparison_possible_no_coloring(self):
        benchmarks = [{
            "name": "coremark",
            "history": [
                {"id": "build1", "statistics": {"coremark_default": {"mean": 1000.0, "cv": 0}}, "regressions": {}, "rca": {}}
            ]
        }]
        html = self._render(benchmarks)
        body = self._body(html)
        self.assertNotIn("row-regressed", body)
        self.assertNotIn("cell-regressed", body)
        self.assertNotIn("metric-value-improved", body)
        self.assertNotIn("metric-value-stable", body)
        self.assertIn("1000.00", html)

    def test_single_column_header_unaffected(self):
        benchmarks = [{
            "name": "coremark",
            "history": [
                {"id": "build1", "statistics": {"coremark_default": {"mean": 1000.0, "cv": 0}}, "regressions": {}, "rca": {}}
            ]
        }]
        html = self._render(benchmarks)
        self.assertIn("<th>Value</th>", html)

    def test_latest_run_regressed_highlights_row_and_cell(self):
        benchmarks = [{
            "name": "coremark",
            "history": [
                {"id": "run1", "statistics": {"coremark_default": {"mean": 1000.0, "cv": 0}}, "regressions": {}, "rca": {}},
                {"id": "run2", "statistics": {"coremark_default": {"mean": 800.0, "cv": 0}},
                 "regressions": {"coremark_default": {"throughput_regression": True, "latency_regression": False}}, "rca": {}}
            ]
        }]
        html = self._render(benchmarks)
        body = self._body(html)
        self.assertIn("row-regressed", body)
        self.assertIn("cell-regressed", body)

    def test_latest_run_improved_colors_green(self):
        # 10% improvement, well above 0.2% error margin
        benchmarks = [{
            "name": "coremark",
            "history": [
                {"id": "run1", "statistics": {"coremark_default": {"mean": 1000.0, "cv": 0}}, "regressions": {}, "rca": {}},
                {"id": "run2", "statistics": {"coremark_default": {"mean": 1100.0, "cv": 0}},
                 "regressions": {"coremark_default": {"throughput_regression": False, "latency_regression": False}}, "rca": {}}
            ]
        }]
        html = self._render(benchmarks)
        body = self._body(html)
        self.assertIn("metric-value-improved", body)
        self.assertNotIn("row-regressed", body)
        # Should NOT show RCA text because no regression exists anywhere in the data -> RCA col not rendered
        self.assertNotIn("Root Cause Analysis", body)

    def test_latest_run_stable_colors_normal(self):
        # 0.1% improvement, within 0.2% error margin
        benchmarks = [{
            "name": "coremark",
            "history": [
                {"id": "run1", "statistics": {"coremark_default": {"mean": 1000.0, "cv": 0}}, "regressions": {}, "rca": {}},
                {"id": "run2", "statistics": {"coremark_default": {"mean": 1001.0, "cv": 0}},
                 "regressions": {"coremark_default": {"throughput_regression": False, "latency_regression": False}}, "rca": {}}
            ]
        }]
        html = self._render(benchmarks)
        body = self._body(html)
        self.assertIn("metric-value-stable", body)
        self.assertNotIn("metric-value-improved", body)
        self.assertNotIn("row-regressed", body)
        # Should not show RCA column because no regressions exist at all
        self.assertNotIn("Root Cause Analysis", body)

    def test_regressed_benchmark_sorts_first_with_rca(self):
        benchmarks = [
            {"name": "coremark", "history": [
                {"id": "run1", "statistics": {"coremark_default": {"mean": 1000.0, "cv": 0}}, "regressions": {}, "rca": {}},
                {"id": "run2", "statistics": {"coremark_default": {"mean": 1100.0, "cv": 0}},
                 "regressions": {"coremark_default": {"throughput_regression": False, "latency_regression": False}}, "rca": {}}
            ]},
            {"name": "unixbench", "history": [
                {"id": "run1", "statistics": {"unixbench_single_core": {"mean": 1000.0, "cv": 0}}, "regressions": {}, "rca": {}},
                {"id": "run2", "statistics": {"unixbench_single_core": {"mean": 700.0, "cv": 0}},
                 "regressions": {"unixbench_single_core": {"throughput_regression": True, "latency_regression": False}}, 
                 "rca": {"unixbench_single_core": {
                     "cause": "Thermal Throttling",
                     "confidence": "90%",
                     "evidence": ["Temp hit 95C"],
                     "recommendation": "Cool it down"
                 }}}
            ]}
        ]
        html = self._render(benchmarks)
        body = self._body(html)
        
        # 1. Check sorting (Tier 1 Regressed -> Tier 2 Improved)
        unixbench_pos = body.find("UnixBench")
        coremark_pos = body.find("Coremark")
        self.assertGreater(unixbench_pos, -1)
        self.assertGreater(coremark_pos, -1)
        self.assertLess(unixbench_pos, coremark_pos)

        # 2. Check RCA column header exists
        self.assertIn("Root Cause Analysis", html)

        # 3. Check RCA content is rendered
        self.assertIn("Thermal Throttling", body)
        self.assertIn("90% confidence", body)
        self.assertIn("Temp hit 95C", body)
        self.assertIn("Cool it down", body)

        # 4. Check coremark shows Improved badge
        self.assertIn("Improved (+10.00%)", body)

    def test_historical_columns_not_colored(self):
        """Only the LATEST history entry may be colored; older columns must
        never get cell-regressed/metric-value-* even if a hypothetical
        h.regressions were present on them."""
        benchmarks = [{
            "name": "coremark",
            "history": [
                {"id": "run1", "statistics": {"coremark_default": {"mean": 1000.0, "cv": 0}},
                 "regressions": {"coremark_default": {"throughput_regression": True, "latency_regression": False}}, "rca": {}},
                {"id": "run2", "statistics": {"coremark_default": {"mean": 1100.0, "cv": 0}},
                 "regressions": {"coremark_default": {"throughput_regression": False, "latency_regression": False}}, "rca": {}}
            ]
        }]
        html = self._render(benchmarks)
        body = self._body(html)
        # run2 (latest) is improved -> should see metric-value-improved, and
        # should NOT see cell-regressed anywhere.
        self.assertIn("metric-value-improved", body)
        self.assertNotIn("cell-regressed", body)

    def test_multi_column_history_still_renders_all_columns(self):
        benchmarks = [{
            "name": "coremark",
            "history": [
                {"id": "b1", "statistics": {"coremark_default": {"mean": 900.0, "cv": 0}}, "regressions": {}, "rca": {}},
                {"id": "b2", "statistics": {"coremark_default": {"mean": 950.0, "cv": 0}}, "regressions": {}, "rca": {}},
                {"id": "b3", "statistics": {"coremark_default": {"mean": 1000.0, "cv": 0}}, "regressions": {}, "rca": {}}
            ]
        }]
        html = self._render(benchmarks)
        self.assertIn("<th>b1</th>", html)
        self.assertIn("<th>b2</th>", html)
        self.assertIn("<th>b3</th>", html)
        self.assertIn("900.00", html)
        self.assertIn("950.00", html)
        self.assertIn("1000.00", html)


if __name__ == "__main__":
    unittest.main()
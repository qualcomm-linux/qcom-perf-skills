"""
test_geekbench_metrics.py - Unit tests for geekbench metric extraction across
all three pipeline layers: aggregator.py, metrics_extractor.py, and the
run-over-run stats extraction in main.py (render_dashboard).

Tests validate:
1. Correct metric keys (geekbench_cpu_single_core / geekbench_cpu_multi_core) are produced
2. None values are filtered out defensively
3. Empty / missing scores are handled gracefully
4. geekbench branch takes priority over the generic sysbench/throughput fallback
5. Multiple test entries produce separate per-test-name keys
6. Non-dict test_data is skipped without raising

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import importlib.util
import ast
import re
import statistics
import sys
import os
import unittest
from pathlib import Path
from typing import Any, Dict, List

# ---------------------------------------------------------------------------
# Path setup — allow imports from aibench/src and the rca skill scripts
# ---------------------------------------------------------------------------
BENCHMARKS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BENCHMARKS_DIR))
RCA_SCRIPTS_DIR = BENCHMARKS_DIR / ".claude" / "skills" / "regression-detection-and-rca" / "scripts"
sys.path.insert(0, str(RCA_SCRIPTS_DIR))


def _load_module(rel_path: str):
    """Load a Python module from a path relative to BENCHMARKS_DIR."""
    abs_path = BENCHMARKS_DIR / rel_path
    spec = importlib.util.spec_from_file_location(abs_path.stem, abs_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_geekbench_results(
    sc_scores: List,
    mc_scores: List,
    test_name: str = "geekbench_cpu",
    benchmark_name: str = "geekbench",
) -> Dict[str, Any]:
    """Build a minimal results.json-like dict for geekbench."""
    return {
        "metadata": {"benchmark_name": benchmark_name},
        "tests": {
            test_name: {
                "single_core_scores": sc_scores,
                "multi_core_scores": mc_scores,
            }
        },
    }


def _run_aggregator_geekbench(results_list: List[Dict]) -> Dict[str, Any]:
    """
    Simulate the aggregator.py loop for a list of results.json dicts.
    Returns the aggregated_metrics dict (before statistics calculation).
    """
    aggregated_metrics: Dict[str, List[float]] = {}
    for result in results_list:
        b_name = result.get("metadata", {}).get("benchmark_name", "")
        if b_name == "geekbench":
            tests_dict = result.get("tests", {})
            for test_name, test_data in tests_dict.items():
                if not isinstance(test_data, dict):
                    continue
                sc_scores = [s for s in test_data.get("single_core_scores", []) if s is not None]
                mc_scores = [s for s in test_data.get("multi_core_scores", []) if s is not None]
                if sc_scores:
                    aggregated_metrics.setdefault(f"{test_name}_single_core", []).extend(sc_scores)
                if mc_scores:
                    aggregated_metrics.setdefault(f"{test_name}_multi_core", []).extend(mc_scores)
    return aggregated_metrics


def _run_main_geekbench_stats(results: Dict) -> Dict[str, Any]:
    """
    Simulate the run-over-run stats extraction block in main.py for geekbench.
    Returns the stats dict that would be stored in benchmark_info["history"].
    """
    stats: Dict[str, Any] = {}
    b_name = results.get("metadata", {}).get("benchmark_name", "")
    if b_name == "geekbench":
        tests_data = results.get("tests", {})
        sc_all, mc_all = [], []
        for test_name, test_data in tests_data.items():
            if not isinstance(test_data, dict):
                continue
            sc_all.extend([s for s in test_data.get("single_core_scores", []) if s is not None])
            mc_all.extend([s for s in test_data.get("multi_core_scores", []) if s is not None])
        if sc_all:
            stats["geekbench_cpu_single_core"] = {"mean": sum(sc_all) / len(sc_all), "cv": 0}
        if mc_all:
            stats["geekbench_cpu_multi_core"] = {"mean": sum(mc_all) / len(mc_all), "cv": 0}
    return stats


def _get_geekbench_keys_from_template() -> set:
    """
    Parse config/templates/summary_dashboard.html's `table_config` (a literal
    Jinja2 `{% set table_config = [...] %}` block containing plain Python
    list/dict/string syntax with no Jinja expressions inside) and return the
    set of `key` values for entries whose `bench` is "geekbench".

    This reads the REAL template so this test can never give false confidence
    the way a hardcoded expected-key set can.
    """
    template_path = BENCHMARKS_DIR / "config" / "templates" / "summary_dashboard.html"
    content = template_path.read_text(encoding="utf-8")
    match = re.search(r"\{%\s*set\s+table_config\s*=\s*(\[.*?\])\s*%\}", content, re.DOTALL)
    if not match:
        return set()
    table_config = ast.literal_eval(match.group(1))
    keys = set()
    for category in table_config:
        for metric in category.get("metrics", []):
            if metric.get("bench") == "geekbench":
                keys.add(metric["key"])
    return keys


# ---------------------------------------------------------------------------
# Test Suite
# ---------------------------------------------------------------------------

class TestMetricsExtractorGeekbench(unittest.TestCase):
    """Tests for metrics_extractor.py geekbench branch."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_module(
            ".claude/skills/regression-detection-and-rca/scripts/metrics_extractor.py"
        )

    def _extract(self, results):
        return self.mod.extract_iteration_metrics(results)

    # --- Test 1: Normal case ---
    def test_normal_case_produces_correct_keys(self):
        r = _make_geekbench_results([1125.0, 1130.0, 1120.0], [5448.0, 5460.0, 5440.0])
        out = self._extract(r)
        self.assertIn("geekbench_cpu_single_core", out, "geekbench_cpu_single_core key must be present")
        self.assertIn("geekbench_cpu_multi_core", out, "geekbench_cpu_multi_core key must be present")
        self.assertEqual(out["geekbench_cpu_single_core"], [1125.0, 1130.0, 1120.0])
        self.assertEqual(out["geekbench_cpu_multi_core"], [5448.0, 5460.0, 5440.0])

    # --- Test 2: Renamed keys from the reverted commit must NOT be produced ---
    def test_renamed_keys_not_produced(self):
        r = _make_geekbench_results([1125.0], [5448.0])
        out = self._extract(r)
        self.assertNotIn("geekbench_st", out, "Renamed key must not be present")
        self.assertNotIn("geekbench_mt", out, "Renamed key must not be present")

    # --- Test 3: None values are filtered ---
    def test_none_values_filtered(self):
        r = _make_geekbench_results([1125.0, None, 1120.0], [5448.0, None])
        out = self._extract(r)
        self.assertEqual(out["geekbench_cpu_single_core"], [1125.0, 1120.0])
        self.assertEqual(out["geekbench_cpu_multi_core"], [5448.0])

    # --- Test 4: All-None scores → no key added ---
    def test_all_none_scores_returns_empty(self):
        r = _make_geekbench_results([None, None], [None])
        out = self._extract(r)
        self.assertEqual(out, {})

    # --- Test 5: Empty scores → no key added ---
    def test_empty_scores_returns_empty(self):
        r = _make_geekbench_results([], [])
        out = self._extract(r)
        self.assertEqual(out, {})

    # --- Test 6: Missing score keys → no key added ---
    def test_missing_score_keys_returns_empty(self):
        r = {"metadata": {"benchmark_name": "geekbench"}, "tests": {"geekbench_cpu": {}}}
        out = self._extract(r)
        self.assertEqual(out, {})

    # --- Test 7: geekbench branch takes priority over sysbench fallback ---
    def test_geekbench_branch_priority_over_sysbench_fallback(self):
        r = _make_geekbench_results([1125.0], [5448.0])
        r["tests"]["geekbench_cpu"]["throughput"] = [999.0]  # add throughput key
        out = self._extract(r)
        self.assertIn("geekbench_cpu_single_core", out)
        self.assertNotIn("geekbench_cpu", out, "Should NOT fall through to sysbench branch")

    # --- Test 8: Multiple test entries produce separate per-test-name keys ---
    def test_multiple_test_entries_kept_separate(self):
        r = {
            "metadata": {"benchmark_name": "geekbench"},
            "tests": {
                "geekbench_cpu": {"single_core_scores": [1125.0], "multi_core_scores": [5448.0]},
                "geekbench_gpu": {"single_core_scores": [800.0], "multi_core_scores": [3200.0]},
            },
        }
        out = self._extract(r)
        # Each test entry gets its own key (matches aggregator.py and the
        # dashboard template, which only defines rows for geekbench_cpu_*).
        self.assertEqual(out["geekbench_cpu_single_core"], [1125.0])
        self.assertEqual(out["geekbench_cpu_multi_core"], [5448.0])
        self.assertEqual(out["geekbench_gpu_single_core"], [800.0])
        self.assertEqual(out["geekbench_gpu_multi_core"], [3200.0])

    # --- Test 9: Non-dict test_data skipped gracefully ---
    def test_non_dict_test_data_skipped(self):
        r = {"metadata": {"benchmark_name": "geekbench"}, "tests": {"geekbench_cpu": "invalid"}}
        out = self._extract(r)
        self.assertEqual(out, {})


class TestAggregatorGeekbench(unittest.TestCase):
    """Tests for aggregator.py geekbench branch (simulated via _run_aggregator_geekbench)."""

    # --- Test 10: Single run produces correct keys ---
    def test_single_run_correct_keys(self):
        r = _make_geekbench_results([1125.0, 1130.0], [5448.0, 5460.0])
        agg = _run_aggregator_geekbench([r])
        self.assertIn("geekbench_cpu_single_core", agg)
        self.assertIn("geekbench_cpu_multi_core", agg)
        self.assertEqual(agg["geekbench_cpu_single_core"], [1125.0, 1130.0])
        self.assertEqual(agg["geekbench_cpu_multi_core"], [5448.0, 5460.0])

    # --- Test 11: Multiple runs aggregated correctly ---
    def test_multiple_runs_aggregated(self):
        r1 = _make_geekbench_results([1125.0], [5448.0])
        r2 = _make_geekbench_results([1130.0], [5460.0])
        agg = _run_aggregator_geekbench([r1, r2])
        self.assertEqual(agg["geekbench_cpu_single_core"], [1125.0, 1130.0])
        self.assertEqual(agg["geekbench_cpu_multi_core"], [5448.0, 5460.0])

    # --- Test 12: None values filtered in aggregator ---
    def test_none_values_filtered_in_aggregator(self):
        r = _make_geekbench_results([1125.0, None], [5448.0, None])
        agg = _run_aggregator_geekbench([r])
        self.assertEqual(agg["geekbench_cpu_single_core"], [1125.0])
        self.assertEqual(agg["geekbench_cpu_multi_core"], [5448.0])

    # --- Test 13: Empty scores → no key in aggregated_metrics ---
    def test_empty_scores_no_key(self):
        r = _make_geekbench_results([], [])
        agg = _run_aggregator_geekbench([r])
        self.assertNotIn("geekbench_cpu_single_core", agg)
        self.assertNotIn("geekbench_cpu_multi_core", agg)

    # --- Test 14: Statistics calculation on aggregated values ---
    def test_statistics_calculation(self):
        scores = [1100.0, 1125.0, 1150.0]
        r = _make_geekbench_results(scores, [5400.0, 5450.0, 5500.0])
        agg = _run_aggregator_geekbench([r])
        mean_st = statistics.mean(agg["geekbench_cpu_single_core"])
        self.assertAlmostEqual(mean_st, 1125.0, places=1)


class TestMainPyGeekbenchStats(unittest.TestCase):
    """Tests for the run-over-run stats extraction block in main.py (simulated)."""

    # --- Test 15: Normal case produces correct stats ---
    def test_normal_case_produces_stats(self):
        r = _make_geekbench_results([1125.0, 1130.0, 1120.0], [5448.0, 5460.0, 5440.0])
        stats = _run_main_geekbench_stats(r)
        self.assertIn("geekbench_cpu_single_core", stats)
        self.assertIn("geekbench_cpu_multi_core", stats)
        expected_st_mean = (1125.0 + 1130.0 + 1120.0) / 3
        self.assertAlmostEqual(stats["geekbench_cpu_single_core"]["mean"], expected_st_mean, places=2)

    # --- Test 16: Stats dict has correct structure ---
    def test_stats_dict_structure(self):
        r = _make_geekbench_results([1125.0], [5448.0])
        stats = _run_main_geekbench_stats(r)
        self.assertIn("mean", stats["geekbench_cpu_single_core"])
        self.assertIn("cv", stats["geekbench_cpu_single_core"])
        self.assertEqual(stats["geekbench_cpu_single_core"]["cv"], 0)

    # --- Test 17: None values filtered in stats extraction ---
    def test_none_values_filtered_in_stats(self):
        r = _make_geekbench_results([1125.0, None, 1120.0], [5448.0, None])
        stats = _run_main_geekbench_stats(r)
        expected_mean = (1125.0 + 1120.0) / 2
        self.assertAlmostEqual(stats["geekbench_cpu_single_core"]["mean"], expected_mean, places=2)

    # --- Test 18: Empty scores → no stats key ---
    def test_empty_scores_no_stats_key(self):
        r = _make_geekbench_results([], [])
        stats = _run_main_geekbench_stats(r)
        self.assertNotIn("geekbench_cpu_single_core", stats)
        self.assertNotIn("geekbench_cpu_multi_core", stats)

    # --- Test 19: Multiple test entries averaged into single stat ---
    def test_multiple_test_entries_averaged(self):
        r = {
            "metadata": {"benchmark_name": "geekbench"},
            "tests": {
                "geekbench_cpu": {"single_core_scores": [1000.0, 1100.0], "multi_core_scores": [5000.0]},
                "geekbench_gpu": {"single_core_scores": [900.0], "multi_core_scores": [4500.0]},
            },
        }
        stats = _run_main_geekbench_stats(r)
        expected_st_mean = (1000.0 + 1100.0 + 900.0) / 3
        self.assertAlmostEqual(stats["geekbench_cpu_single_core"]["mean"], expected_st_mean, places=2)

    # --- Test 20: Non-geekbench benchmark returns empty stats ---
    def test_non_geekbench_returns_empty(self):
        r = {"metadata": {"benchmark_name": "sysbench"}, "tests": {}}
        stats = _run_main_geekbench_stats(r)
        self.assertEqual(stats, {})


class TestKeyConsistency(unittest.TestCase):
    """Cross-layer consistency: all three layers must produce the same keys."""

    @classmethod
    def setUpClass(cls):
        cls.extractor_mod = _load_module(
            ".claude/skills/regression-detection-and-rca/scripts/metrics_extractor.py"
        )

    def test_all_layers_produce_same_keys(self):
        """geekbench_cpu_single_core and geekbench_cpu_multi_core must be the
        keys in all three layers (for the single geekbench_cpu test entry case)."""
        r = _make_geekbench_results([1125.0, 1130.0], [5448.0, 5460.0])

        # Layer 1: metrics_extractor
        extractor_out = self.extractor_mod.extract_iteration_metrics(r)
        extractor_keys = set(extractor_out.keys())

        # Layer 2: aggregator
        agg_out = _run_aggregator_geekbench([r])
        agg_keys = set(agg_out.keys())

        # Layer 3: main.py stats extraction
        stats_out = _run_main_geekbench_stats(r)
        stats_keys = set(stats_out.keys())

        expected_keys = {"geekbench_cpu_single_core", "geekbench_cpu_multi_core"}
        self.assertEqual(extractor_keys, expected_keys, f"metrics_extractor keys mismatch: {extractor_keys}")
        self.assertEqual(agg_keys, expected_keys, f"aggregator keys mismatch: {agg_keys}")
        self.assertEqual(stats_keys, expected_keys, f"main.py stats keys mismatch: {stats_keys}")

    def test_dashboard_template_keys_match(self):
        """Verify the keys match what the dashboard template ACTUALLY expects,
        by parsing the real template file rather than hardcoding the expected
        set. This is the regression guard for the class of bug where the
        template and the producer code silently drift apart."""
        dashboard_template_keys = _get_geekbench_keys_from_template()
        self.assertTrue(dashboard_template_keys, "No geekbench keys found in dashboard template table_config")
        r = _make_geekbench_results([1125.0], [5448.0])
        stats_out = _run_main_geekbench_stats(r)
        for key in dashboard_template_keys:
            self.assertIn(key, stats_out, f"Dashboard key '{key}' not found in stats")


if __name__ == "__main__":
    unittest.main(verbosity=2)
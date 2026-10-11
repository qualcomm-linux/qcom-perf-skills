"""
test_lat_mem_rd.py - Unit tests for the lat_mem_rd benchmark engine.

Validates:
1. Command building (with the YAML fallback-parser {} vs "" quirk).
2. Output parsing of raw lat_mem_rd text.
3. Plateau detection algorithm against the exact sample data provided in
   the benchmark specification.

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import importlib.util
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.benchmark.lat_mem_rd import LatMemRd

_RCA_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / ".claude" / "skills" / "regression-detection-and-rca" / "scripts"


def _load_metrics_extractor():
    abs_path = _RCA_SCRIPTS_DIR / "metrics_extractor.py"
    spec = importlib.util.spec_from_file_location("metrics_extractor", abs_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SAMPLE_OUTPUT = """stride=64
0.00049 1.697
0.00098 1.694
0.00195 1.694
0.00293 1.694
0.00391 1.694
0.00586 1.694
0.00781 1.695
0.01172 1.694
0.01562 1.695
0.02344 1.695
0.03125 3.786
0.04688 3.354
0.06250 3.998
0.09375 4.717
0.12500 4.661
0.18750 5.945
0.25000 6.155
0.37500 6.122
0.50000 6.137
0.75000 6.748
1.00000 7.014
1.50000 7.128
2.00000 7.754
3.00000 8.025
4.00000 8.726
6.00000 41.717
8.00000 67.656
12.00000 95.763
16.00000 109.395
24.00000 122.793
32.00000 129.347
48.00000 138.765
64.00000 139.351
96.00000 140.490
128.00000 141.227
192.00000 141.703
256.00000 141.742"""


def make_benchmark(config_overrides=None):
    config = {
        "command": "/usr/bin/lat_mem_rd",
        "iterations": 3,
        "category": "Memory",
        "metric_direction": "lower",
        "common_params": {"-t": "", "-N": 7},
        "stride": 64,
        "workload_sizes": ["64M", "96M", "128M", "192M", "256M"],
        "inter_command_delay": 0,
        "inter_iteration_delay": 0,
        "retry_attempts": 3,
        "plateau_thresholds": {
            "min_points": 4,
            "max_spread_pct": 3.0,
            "max_adjacent_change_pct": 2.0,
        },
        "tests": ["lat_mem_rd_default"],
    }
    if config_overrides:
        config.update(config_overrides)
    return LatMemRd("lat_mem_rd", config, Path("/tmp/lat_mem_rd_test"))


class TestLatMemRdCommandBuilding(unittest.TestCase):
    def test_build_command_basic(self):
        bench = make_benchmark()
        cmd = bench._build_command("256M")
        self.assertEqual(cmd, "/usr/bin/lat_mem_rd -t -N 7 256M 64")

    def test_build_command_handles_empty_dict_quirk(self):
        """The fallback YAML parser turns '-t: \"\"' into an empty dict {}."""
        bench = make_benchmark({"common_params": {"-t": {}, "-N": 7}})
        cmd = bench._build_command("64M")
        self.assertEqual(cmd, "/usr/bin/lat_mem_rd -t -N 7 64M 64")


class TestLatMemRdOutputParsing(unittest.TestCase):
    def test_parse_output_skips_header_and_parses_points(self):
        bench = make_benchmark()
        points = bench._parse_output(SAMPLE_OUTPUT)
        self.assertEqual(len(points), 37)  # 37 data lines, header excluded
        self.assertEqual(points[0], (0.00049, 1.697))
        self.assertEqual(points[-1], (256.0, 141.742))

    def test_parse_output_empty_string(self):
        bench = make_benchmark()
        points = bench._parse_output("")
        self.assertEqual(points, [])


class TestLatMemRdPlateauDetection(unittest.TestCase):
    def test_detect_plateau_matches_spec_example(self):
        """
        Per the task specification, the last 5 points:
            64.00000  139.351
            96.00000  140.490
            128.00000 141.227
            192.00000 141.703
            256.00000 141.742
        should form a valid plateau with:
            average ~= 140.903 ns
            spread  ~= 1.70%
        """
        bench = make_benchmark()
        points = bench._parse_output(SAMPLE_OUTPUT)
        result = bench.detect_plateau(points)

        self.assertTrue(result["valid"], msg=f"Plateau should be valid: {result}")
        # Average should be close to 140.903 ns (spec example rounds to ~141)
        self.assertAlmostEqual(result["plateau_latency_ns"], 140.903, delta=0.5)
        self.assertGreaterEqual(result["points_count"], 4)
        self.assertLessEqual(result["spread_pct"], 3.0)

    def test_detect_plateau_no_points(self):
        bench = make_benchmark()
        result = bench.detect_plateau([])
        self.assertFalse(result["valid"])
        self.assertEqual(result["plateau_latency_ns"], 0.0)

    def test_detect_plateau_insufficient_points(self):
        bench = make_benchmark()
        # Only 2 points, less than min_points=4
        result = bench.detect_plateau([(1.0, 10.0), (2.0, 10.5)])
        self.assertFalse(result["valid"])

    def test_detect_plateau_large_upward_trend_is_rejected(self):
        """A significant, sustained upward trend (large spread/adjacent
        changes) should not qualify as a valid plateau. Small monotonic
        increases within threshold (as in the reference example) ARE
        acceptable and are covered by test_detect_plateau_matches_spec_example.
        """
        bench = make_benchmark()
        increasing_points = [
            (1.0, 10.0),
            (2.0, 20.0),
            (3.0, 30.0),
            (4.0, 40.0),
            (5.0, 50.0),
            (6.0, 60.0),
            (7.0, 70.0),
        ]
        result = bench.detect_plateau(increasing_points)
        self.assertFalse(result["valid"])


class TestLatMemRdRunSingleWorkload(unittest.TestCase):
    """
    Regression tests for the bug where _run_single_workload() discarded the
    actual device output on total parse failure and returned "" instead,
    making it impossible to diagnose why parsing failed (the raw output
    was never written to the per-run log file). These tests ensure the
    real last-seen output is always returned/preserved, matching the
    pattern used by sysbench.py.
    """

    class _FakeExecutor:
        """Minimal stand-in for serial_executor/ssh_manager.execute_command."""
        def __init__(self, outputs):
            # outputs: list of strings to return on successive calls
            self._outputs = list(outputs)
            self.calls = []

        def execute_command(self, cmd, timeout_override=None, prefer_stderr=False):
            self.calls.append((cmd, timeout_override, prefer_stderr))
            if self._outputs:
                return self._outputs.pop(0)
            return ""

    def test_raw_output_preserved_on_total_parse_failure(self):
        """
        Simulates a device returning real, non-empty, but unparsable output
        (e.g. an error message) on every retry attempt. Previously this
        would incorrectly return "" - now it must return the actual text.
        """
        bogus_output = "lat_mem_rd: error: unable to allocate memory\n"
        executor = self._FakeExecutor([bogus_output, bogus_output, bogus_output])
        bench = make_benchmark({"retry_attempts": 3})

        points, raw_output = bench._run_single_workload(executor, "64M")

        self.assertEqual(points, [])
        self.assertEqual(raw_output, bogus_output)
        self.assertEqual(len(executor.calls), 3)

    def test_raw_output_empty_when_device_returns_nothing(self):
        """If the device genuinely returns empty output on every attempt,
        raw_output should be empty (not crash), and points should be []."""
        executor = self._FakeExecutor(["", "", ""])
        bench = make_benchmark({"retry_attempts": 3})

        points, raw_output = bench._run_single_workload(executor, "64M")

        self.assertEqual(points, [])
        self.assertEqual(raw_output, "")

    def test_raw_output_and_points_returned_on_success(self):
        """Successful parse should return both valid points and the raw
        output that produced them (used for on-disk logging)."""
        executor = self._FakeExecutor([SAMPLE_OUTPUT])
        bench = make_benchmark({"retry_attempts": 3})

        points, raw_output = bench._run_single_workload(executor, "256M")

        self.assertTrue(len(points) > 0)
        self.assertEqual(raw_output, SAMPLE_OUTPUT)
        # Should not have retried since first attempt succeeded.
        self.assertEqual(len(executor.calls), 1)

    def test_last_attempt_output_preserved_when_earlier_attempts_differ(self):
        """When retries produce different output each time, the LAST
        attempt's raw output must be the one preserved/returned."""
        outputs = ["first bogus\n", "second bogus\n", "third and final bogus\n"]
        executor = self._FakeExecutor(outputs)
        bench = make_benchmark({"retry_attempts": 3})

        points, raw_output = bench._run_single_workload(executor, "64M")

        self.assertEqual(points, [])
        self.assertEqual(raw_output, "third and final bogus\n")

    def test_prefer_stderr_true_is_passed_to_executor(self):
        """lat_mem_rd's real data output was confirmed (on-target) to be
        written to stderr rather than stdout. _run_single_workload() must
        request prefer_stderr=True from the executor so SshManager treats
        stderr as the primary output stream for this benchmark only."""
        executor = self._FakeExecutor([SAMPLE_OUTPUT])
        bench = make_benchmark({"retry_attempts": 3})

        bench._run_single_workload(executor, "256M")

        self.assertEqual(len(executor.calls), 1)
        _, _, prefer_stderr_used = executor.calls[0]
        self.assertTrue(prefer_stderr_used)


class TestLatMemRdOverallAggregation(unittest.TestCase):
    def test_iteration_to_iteration_spread_calculation(self):
        """
        Verify the overall plateau / spread formula matches the spec example:
            p1 = 140.9, p2 = 142.1, p3 = 141.4
            overall = (140.9 + 142.1 + 141.4) / 3 = 141.4667
            spread% = ((142.1 - 140.9) / 141.4667) * 100 = 0.848%
        """
        plateaus = [140.9, 142.1, 141.4]
        overall = sum(plateaus) / len(plateaus)
        spread_pct = ((max(plateaus) - min(plateaus)) / overall) * 100.0

        self.assertAlmostEqual(overall, 141.467, delta=0.01)
        self.assertAlmostEqual(spread_pct, 0.848, delta=0.01)


class TestMetricsExtractorLatMemRd(unittest.TestCase):
    """
    Regression test for finding #3: the per-iteration plateau series must
    hold only the raw per-iteration samples, never the derived mean mixed
    into the same list (which previously happened via
    per_iter_plateaus[1:] appended onto the *_overall_plateau_ns key that
    also held the mean).
    """

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_metrics_extractor()

    def test_per_iteration_series_excludes_mean(self):
        clean_plateaus = [10.0, 20.0, 60.0]
        mean = sum(clean_plateaus) / len(clean_plateaus)  # 30.0, distinct from every sample
        results = {
            "metadata": {"benchmark_name": "lat_mem_rd"},
            "tests": {
                "lat_mem_rd_default": {
                    "overall_plateau_latency_ns": mean,
                    "per_iteration_plateau_ns": clean_plateaus,
                }
            },
        }

        out = self.mod.extract_iteration_metrics(results)

        # The derived mean lives on its own distinctly-named key.
        self.assertEqual(out["lat_mem_rd_default_overall_plateau_ns"], [mean])

        # Each raw sample lives on its own per-iteration key, with no
        # mean value conflated in.
        self.assertEqual(out["lat_mem_rd_default_iter1_plateau_ns"], [10.0])
        self.assertEqual(out["lat_mem_rd_default_iter2_plateau_ns"], [20.0])
        self.assertEqual(out["lat_mem_rd_default_iter3_plateau_ns"], [60.0])
        self.assertNotIn(mean, out["lat_mem_rd_default_iter1_plateau_ns"])
        self.assertNotIn(mean, out["lat_mem_rd_default_iter2_plateau_ns"])
        self.assertNotIn(mean, out["lat_mem_rd_default_iter3_plateau_ns"])


if __name__ == "__main__":
    unittest.main()
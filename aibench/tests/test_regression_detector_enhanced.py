"""
test_regression_detector_enhanced.py - Tests for the multi-method robust regression detector
(Replacement for Z-Score based system)
"""

import sys
from pathlib import Path
import statistics
import unittest
from unittest.mock import patch

# Allow importing from src
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.reporting.regression_detector import RegressionDetector

class TestEnhancedRegressionDetector(unittest.TestCase):
    def setUp(self):
        # Configure robust multi-method detector suitable for IIOT testing
        self.detector = RegressionDetector(
            throughput_threshold=-0.05, 
            latency_threshold=0.10,
            use_median=True,
            use_mann_whitney=True,
            use_cohens_d=True,
            use_quantile=True,
            consensus_threshold=2
        )

    def test_no_regression_stable_metrics(self):
        baseline = {"throughput": [100.0, 102.0, 98.0]}
        current = {"throughput": [101.0, 99.0, 100.5]}
        res = self.detector.detect_regressions(baseline, current, "test_stable")
        
        self.assertFalse(res["throughput_regression"])
        self.assertEqual(len(res["methods_triggered"]), 0)
        self.assertEqual(res["confidence_score"], 0.0)

    def test_obvious_regression_consensus(self):
        # Throughput dropped significantly (100 -> 85, i.e., -15%)
        # All robust methods should fire for this clear drop
        baseline = {"throughput": [100.0, 99.0, 101.0, 100.0, 99.5]}
        current = {"throughput": [85.0, 84.0, 86.0, 85.5, 84.5]}
        res = self.detector.detect_regressions(baseline, current, "test_obvious")
        
        self.assertTrue(res["throughput_regression"])
        # Both median and mann-whitney (primary methods) should trigger -> 95% confidence
        self.assertIn("median_delta", res["methods_triggered"])
        self.assertIn("mann_whitney", res["methods_triggered"])
        self.assertGreaterEqual(res["confidence_score"], 95.0)

    def test_noise_filtering_via_consensus_no_regression(self):
        # Baseline has very high variance.
        # Mean drop is technically -6%, but the distributions completely overlap.
        # Mann-Whitney U test should determine they are not statistically different.
        baseline = {"throughput": [100.0, 80.0, 120.0, 90.0, 110.0]}  # mean = 100
        current = {"throughput": [94.0, 93.0, 95.0, 91.0, 97.0]}     # mean = 94, delta = -6%
        res = self.detector.detect_regressions(baseline, current, "test_noise")
        
        # Consensus should prevent a false positive here because Mann-Whitney and Cohen's d won't trigger strongly
        # (Though simple median might hit -6%, it won't have consensus)
        self.assertFalse(res["throughput_regression"])
        
    def test_small_sample_fallback(self):
        # With < 2 samples, robust stats (Mann-Whitney, Cohen's d) cannot run.
        # System should fallback to "small_sample_delta" correctly.
        baseline = {"throughput": [100.0]}
        current = {"throughput": [90.0]}
        res = self.detector.detect_regressions(baseline, current, "test_small")
        
        self.assertTrue(res["throughput_regression"])
        self.assertIn("small_sample_delta", res["methods_triggered"])
        self.assertEqual(res["confidence_score"], 50.0)

    def test_thermal_throttling_bimodal(self):
        # Baseline: Consistent performance
        baseline = {"throughput": [100.0, 101.0, 99.0, 100.0, 102.0]}
        
        # Current: Starts strong, but thermals throttle it halfway through (bimodal)
        current = {"throughput": [100.0, 99.0, 80.0, 75.0, 72.0]}
        
        res = self.detector.detect_regressions(baseline, current, "test_thermal")
        
        self.assertTrue(res["throughput_regression"])
        
        # Median (50th percentile) will be 80.0 vs 100.0 -> -20% drop -> True
        self.assertIn("median_delta", res["methods_triggered"])
        
        # Lower quartile (25th percentile) will catch the throttled tail easily
        self.assertIn("quantile_delta", res["methods_triggered"])

    def test_outlier_filtering(self):
        # Baseline is stable
        baseline = {"throughput": [100.0, 101.0, 99.0, 100.0, 101.0]}
        
        # Current is generally stable around 98 (a 2% drop, which is acceptable),
        # but has ONE extreme anomalous outlier (e.g. system stutter) down to 10
        current = {"throughput": [99.0, 98.0, 10.0, 98.0, 97.0, 99.0]}
        
        res = self.detector.detect_regressions(baseline, current, "test_outlier")
        
        # MAD outlier filter should catch the 10.0 and discard it, meaning the effective
        # current mean/median is ~98.2. Since 98.2 is > 95 (-5% threshold), NO regression is flagged.
        self.assertFalse(res["throughput_regression"])
        self.assertEqual(res["outliers_detected"], 1)

    def test_precalculated_stats_fallback(self):
        # Test aggregator fallback path where only mean/stdev are provided
        baseline = {"mean": 100.0, "stddev": 1.0}
        current = {"mean": 90.0, "stddev": 1.0}
        
        res = self.detector.detect_regressions(baseline, current, "test_precalc")
        
        self.assertTrue(res["throughput_regression"])
        self.assertIn("delta_threshold", res["methods_triggered"])
        self.assertEqual(res["confidence_score"], 50.0)

    def test_latency_regression(self):
        # Latency threshold is > +10%
        baseline = {"throughput": [100.0], "latency_95": [10.0, 11.0, 10.5]}
        current = {"throughput": [100.0], "latency_95": [15.0, 14.5, 15.5]}
        
        res = self.detector.detect_regressions(baseline, current, "test_lat")
        
        self.assertFalse(res["throughput_regression"])
        self.assertTrue(res["latency_regression"])


def _mock_pvalue_by_current_tuple(pvalue_map, default_p=0.8):
    """Build a replacement for RegressionDetector._mann_whitney_pvalue that
    returns a controlled p-value keyed by the (rounded) current-side sample
    tuple, independent of whether scipy is actually installed."""
    def _fake(self, baseline_data, current_data):
        baseline_mean = statistics.mean(baseline_data)
        current_mean = statistics.mean(current_data)
        delta_percent = (
            (current_mean - baseline_mean) / baseline_mean * 100
            if baseline_mean else 0.0
        )
        key = tuple(current_data)
        p_value = pvalue_map.get(key, default_p)
        return p_value, False, delta_percent
    return _fake


class TestOutlierMaskingSafeguards(unittest.TestCase):
    def setUp(self):
        self.detector = RegressionDetector(
            throughput_threshold=-0.05,
            latency_threshold=0.10,
            use_median=True,
            use_mann_whitney=True,
            use_cohens_d=True,
            use_quantile=True,
            consensus_threshold=2,
        )

    def test_outlier_filtering_still_passes_with_no_masking_caveat(self):
        # Sanity check: existing single-blip-noise behavior is unchanged by
        # the Fix #1 additions, and no masking caveat is raised here because
        # the median is inherently robust to this single extreme point.
        baseline = {"throughput": [100.0, 101.0, 99.0, 100.0, 101.0]}
        current = {"throughput": [99.0, 98.0, 10.0, 98.0, 97.0, 99.0]}

        res = self.detector.detect_regressions(baseline, current, "test_outlier")

        self.assertFalse(res["throughput_regression"])
        self.assertEqual(res["outliers_detected"], 1)
        self.assertFalse(res["outlier_masking_risk"])

    def test_outlier_removal_flags_masking_risk_when_raw_data_shows_regression(self):
        baseline_tp = [100.0, 99.0, 101.0, 100.0, 99.5]
        raw_current_tp = [99.0, 98.0, 100.0, 99.0, 101.0, 20.0]
        cleaned_current_tp = (99.0, 98.0, 100.0, 99.0, 101.0)

        pvalue_map = {
            tuple(raw_current_tp): 0.01,
            cleaned_current_tp: 0.5,
        }

        with patch.object(
            RegressionDetector,
            "_mann_whitney_pvalue",
            _mock_pvalue_by_current_tuple(pvalue_map),
        ):
            baseline = {"throughput": baseline_tp}
            current = {"throughput": raw_current_tp}
            res = self.detector.detect_regressions(baseline, current, "test_mask")

        # Official verdict (post-cleaning) must remain "no regression" -
        # the fix is additive, it never flips the verdict.
        self.assertFalse(res["throughput_regression"])
        self.assertEqual(res["outliers_detected"], 1)

        # But the caveat must surface that raw (pre-filter) data would have
        # flagged a regression, with confidence demoted.
        self.assertTrue(res["outlier_masking_risk"])
        self.assertLessEqual(res["confidence_score"], 50.0)
        caveats = [e for e in res["evidence"] if e.get("type") == "CAVEAT"]
        self.assertEqual(len(caveats), 1)
        self.assertIn("20.0", caveats[0]["value"])

    def test_outlier_cap_prevents_discarding_majority_as_outliers(self):
        baseline_tp = [100.0, 99.0, 101.0, 100.0, 99.5]
        # Bimodal/sustained-shift: 3 of 7 iterations genuinely low (thermal
        # throttling for part of the run), not isolated noise. Naive 3xMAD
        # would flag these 3 (>1/3 of samples) as "outliers" and erase the
        # real regression; the cap must decline to filter at all.
        current_tp = [100.0, 99.0, 101.0, 100.0, 70.0, 69.0, 71.0]

        pvalue_map = {tuple(current_tp): 0.01}

        with patch.object(
            RegressionDetector,
            "_mann_whitney_pvalue",
            _mock_pvalue_by_current_tuple(pvalue_map),
        ):
            baseline = {"throughput": baseline_tp}
            current = {"throughput": current_tp}
            res = self.detector.detect_regressions(baseline, current, "test_cap")

        self.assertEqual(res["outliers_detected"], 0)
        self.assertTrue(res["throughput_regression"])


class TestBatchFDRCorrection(unittest.TestCase):
    def setUp(self):
        # Isolate to median + Mann-Whitney (the two "primary" methods) so the
        # effect of suppressing a corrected-away Mann-Whitney hit on the
        # final verdict is directly observable, without cohens_d/quantile
        # (secondary methods) muddying which signal drove the result.
        self.detector = RegressionDetector(
            throughput_threshold=-0.05,
            latency_threshold=0.10,
            use_median=True,
            use_mann_whitney=True,
            use_cohens_d=False,
            use_quantile=False,
            consensus_threshold=2,
        )

    def test_mann_whitney_pvalue_helper(self):
        # Direct unit test, independent of scipy availability.
        p, used_fallback, delta = self.detector._mann_whitney_pvalue([1.0], [2.0])
        self.assertIsNone(p)
        self.assertFalse(used_fallback)

        p, used_fallback, delta = self.detector._mann_whitney_pvalue(
            [100.0, 99.0, 101.0], [99.0, 98.0, 100.0]
        )
        # scipy is not installed in this environment, so this takes the
        # ImportError fallback path - still deterministic to assert on.
        self.assertIsNone(p)
        self.assertTrue(used_fallback)

    def test_batch_single_metric_matches_single_call(self):
        baseline = {"m1": {"throughput": [100.0, 99.0, 101.0, 100.0, 99.5]}}
        current = {"m1": {"throughput": [85.0, 84.0, 86.0, 85.5, 84.5]}}

        single = self.detector.detect_regressions(baseline["m1"], current["m1"], test_name="m1")
        batch = self.detector.detect_regressions_batch(baseline, current, {"m1": "higher"})

        self.assertEqual(batch["m1"]["throughput_regression"], single["throughput_regression"])
        self.assertEqual(batch["m1"]["confidence_score"], single["confidence_score"])
        self.assertEqual(set(batch["m1"]["methods_triggered"]), set(single["methods_triggered"]))

    def test_batch_corrects_marginal_false_positive_among_many_stable_metrics(self):
        stable_baseline = [100.0, 99.5, 100.5, 100.0, 99.8]
        stable_current = [99.0, 98.5, 99.5, 99.0, 98.8]
        borderline_baseline = [100.0, 99.5, 100.5, 100.0, 99.8]
        borderline_current = [94.5, 94.0, 95.0, 94.5, 94.3]

        baseline_stats = {f"stable_{i}": {"throughput": list(stable_baseline)} for i in range(19)}
        current_stats = {f"stable_{i}": {"throughput": list(stable_current)} for i in range(19)}
        baseline_stats["borderline"] = {"throughput": list(borderline_baseline)}
        current_stats["borderline"] = {"throughput": list(borderline_current)}

        pvalue_map = {
            tuple(stable_current): 0.8,
            tuple(borderline_current): 0.03,
        }

        with patch.object(
            RegressionDetector,
            "_mann_whitney_pvalue",
            _mock_pvalue_by_current_tuple(pvalue_map),
        ):
            # Confirm the raw, uncorrected per-metric call would have fired.
            raw = self.detector.detect_regressions(
                baseline_stats["borderline"], current_stats["borderline"], test_name="borderline"
            )
            self.assertTrue(raw["throughput_regression"])
            self.assertIn("mann_whitney", raw["methods_triggered"])

            batched = self.detector.detect_regressions_batch(baseline_stats, current_stats)

        corrected = batched["borderline"]
        self.assertNotIn("mann_whitney", corrected["methods_triggered"])
        self.assertFalse(corrected["throughput_regression"])
        self.assertIn("mann_whitney_p_adjusted", corrected["metrics"])
        self.assertGreaterEqual(corrected["metrics"]["mann_whitney_p_adjusted"], self.detector.fdr_alpha)

    def test_batch_preserves_strong_genuine_regression_despite_correction(self):
        stable_baseline = [100.0, 99.5, 100.5, 100.0, 99.8]
        stable_current = [99.0, 98.5, 99.5, 99.0, 98.8]
        strong_baseline = [100.0, 99.5, 100.5, 100.0, 99.8]
        # Flat (zero-variance) so the MAD outlier filter is a no-op here -
        # keeps the mocked p-value lookup aligned with whatever data the
        # consensus step actually sees.
        strong_current = [80.0, 80.0, 80.0, 80.0, 80.0]

        baseline_stats = {f"stable_{i}": {"throughput": list(stable_baseline)} for i in range(19)}
        current_stats = {f"stable_{i}": {"throughput": list(stable_current)} for i in range(19)}
        baseline_stats["strong"] = {"throughput": list(strong_baseline)}
        current_stats["strong"] = {"throughput": list(strong_current)}

        pvalue_map = {
            tuple(stable_current): 0.8,
            tuple(strong_current): 1e-6,
        }

        with patch.object(
            RegressionDetector,
            "_mann_whitney_pvalue",
            _mock_pvalue_by_current_tuple(pvalue_map),
        ):
            batched = self.detector.detect_regressions_batch(baseline_stats, current_stats)

        corrected = batched["strong"]
        self.assertIn("mann_whitney", corrected["methods_triggered"])
        self.assertTrue(corrected["throughput_regression"])
        self.assertLess(corrected["metrics"]["mann_whitney_p_adjusted"], self.detector.fdr_alpha)


if __name__ == "__main__":
    unittest.main()
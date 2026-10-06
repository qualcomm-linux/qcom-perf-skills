#!/usr/bin/env python3
"""
outlier_detector.py - Sysbench CPU benchmark outlier detection module.

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>

Purpose
-------
Analyzes a series of parsed sysbench CPU iteration results (one dict per
iteration) and determines whether the series is statistically clean enough
to use for regression analysis. Detects and discards a single-iteration
outlier automatically; flags the series as UNSTABLE (requiring the calling
benchmark harness to discard the whole series and re-collect fresh data)
when 2 or more iterations are flagged as outliers.

Design Notes
------------
- This module is a PURE, stateless analysis function. It does not itself
  invoke sysbench or collect new iterations - that responsibility belongs
  to the calling benchmark harness (e.g. run_sysbench.py), which is the
  only component capable of triggering a fresh on-device collection.
- To support the "retry" policy (max 2 retries before aborting) without
  giving this module any hidden state, `run_outlier_detection()` accepts
  two additional keyword-only parameters beyond the originally specified
  signature: `retry_count` (how many retries the CALLER has already
  performed for this benchmark variant) and `max_retries` (the ceiling,
  default 2). The harness is expected to track `retry_count` across its
  own retry loop and pass it back in on each subsequent call to this
  function. This keeps the module pure/stateless and fully unit-testable
  in isolation while still satisfying the described retry semantics: on
  BenchmarkUnstableError the harness re-collects a fresh series and calls
  this function again with retry_count + 1; once retry_count reaches
  max_retries and the series is still unstable, BenchmarkAbortedError is
  raised instead.
- Python stdlib only: statistics, math, logging, json, copy, collections,
  typing. No pandas / numpy / scipy.

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import copy
import logging
import statistics
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

__all__ = [
    "run_outlier_detection",
    "InsufficientDataError",
    "BenchmarkUnstableError",
    "BenchmarkAbortedError",
]

_LOG_PREFIX = "[outlier_detector]"

# --------------------------------------------------------------------------
# Metric configuration
# --------------------------------------------------------------------------

# Per-metric thresholds for each of the three detection methods.
#   "pct"      -> max allowed % deviation from median (median_pct method)
#   "iqr_mult" -> Tukey fence multiplier (IQR method)
#   "mad_z"    -> modified Z-score threshold (MAD method)
#
# NOTE: `total_events` is specified in the metric schema as "Tier 1 -
# always present; INCLUDE in detection" but is not explicitly listed in the
# thresholds table. Since it is directly proportional to
# `cpu_events_per_sec` for a fixed test duration (both derived from the
# same underlying measurement), it is assigned the same thresholds as
# `cpu_events_per_sec` here.
METRIC_THRESHOLDS: Dict[str, Dict[str, float]] = {
    "cpu_events_per_sec":     {"pct": 0.05, "iqr_mult": 1.5, "mad_z": 2.5},
    "total_events":           {"pct": 0.05, "iqr_mult": 1.5, "mad_z": 2.5},
    "latency_min_ms":         {"pct": 0.05, "iqr_mult": 1.5, "mad_z": 2.5},
    "latency_avg_ms":         {"pct": 0.10, "iqr_mult": 1.5, "mad_z": 2.5},
    "latency_p95_ms":         {"pct": 0.10, "iqr_mult": 1.5, "mad_z": 2.5},
    "latency_max_ms":         {"pct": 0.25, "iqr_mult": 2.0, "mad_z": 3.0},
    "fairness_events_stddev": {"pct": 0.15, "iqr_mult": 1.5, "mad_z": 2.5},
    "fairness_time_stddev":   {"pct": 0.15, "iqr_mult": 1.5, "mad_z": 2.5},
    "scaling_efficiency":     {"pct": 0.05, "iqr_mult": 1.5, "mad_z": 2.5},
}

# Fields explicitly excluded from outlier detection per the metric schema
# (metadata / near-constant-by-design / not a meaningful signal).
_EXCLUDED_FIELDS = {
    "num_threads",
    "cpu_max_prime",
    "total_time_sec",
    "latency_sum_ms",
    "fairness_events_avg",
    "fairness_time_avg",
}

# Metrics that may legitimately be None on single-threaded runs; skipped
# entirely (for all iterations) if None across the whole series.
_OPTIONAL_METRICS = {
    "fairness_events_stddev",
    "fairness_time_stddev",
    "scaling_efficiency",
}

_DETECTION_METRICS = tuple(METRIC_THRESHOLDS.keys())


# --------------------------------------------------------------------------
# Exceptions
# --------------------------------------------------------------------------

class InsufficientDataError(Exception):
    """resolved_n < min_iterations - block analysis."""


class BenchmarkUnstableError(Exception):
    """2+ iterations flagged as outliers - discard series and recollect."""


class BenchmarkAbortedError(Exception):
    """Still UNSTABLE after max retries - abort benchmark entirely."""


def _exception_payload(
    run_id: str,
    benchmark_variant: str,
    reason: str,
    retry_count: int,
    flagged_iterations: List[int],
    flagged_metrics: Dict[int, List[str]],
    action: str,
) -> Dict[str, Any]:
    """Build the standardized exception payload dict used by all three
    exception classes raised from this module."""
    return {
        "run_id": run_id,
        "benchmark_variant": benchmark_variant,
        "reason": reason,
        "retry_count": retry_count,
        "flagged_iterations": list(flagged_iterations),
        "flagged_metrics": {str(k): v for k, v in flagged_metrics.items()},
        "action": action,
    }


# --------------------------------------------------------------------------
# Step 1: Resolve n_iterations
# --------------------------------------------------------------------------

def resolve_n_iterations(
    n_iterations: Optional[int],
    iterations: List[Dict[str, Any]],
    min_iterations: int = 3,
) -> int:
    """
    Resolve the effective number of iterations to operate on.

    Priority order:
      1. Use `n_iterations` if it is a valid int AND matches len(iterations).
      2. If None / 0 / negative / non-int -> fallback to len(iterations).
      3. If valid int but != len(iterations) -> fallback to len(iterations).
      4. If the resolved count < min_iterations -> raise InsufficientDataError.

    Always emits a structured log entry describing the resolution outcome.

    Parameters
    ----------
    n_iterations:
        Caller-supplied iteration count (may be None, wrong type, or
        mismatched with the actual list length).
    iterations:
        The raw list of iteration dicts collected by the harness.
    min_iterations:
        The minimum number of iterations required to proceed with analysis.

    Returns
    -------
    int
        The resolved, trustworthy iteration count (== len(iterations)
        whenever a fallback is triggered).

    Raises
    ------
    InsufficientDataError
        If the resolved count is below `min_iterations`.
    """
    actual_len = len(iterations)
    fallback_triggered = False
    reason = "supplied value matched len(iterations); used as-is"

    if not isinstance(n_iterations, int) or isinstance(n_iterations, bool):
        fallback_triggered = True
        reason = (
            f"n_iterations={n_iterations!r} is None/non-int; "
            f"fallback to len(iterations)={actual_len}"
        )
        resolved = actual_len
    elif n_iterations <= 0:
        fallback_triggered = True
        reason = (
            f"n_iterations={n_iterations} is zero/negative; "
            f"fallback to len(iterations)={actual_len}"
        )
        resolved = actual_len
    elif n_iterations != actual_len:
        fallback_triggered = True
        reason = (
            f"n_iterations={n_iterations} != len(iterations)={actual_len}; "
            f"fallback to len(iterations)"
        )
        resolved = actual_len
    else:
        resolved = n_iterations

    log_payload = {
        "event": "n_iterations_resolved",
        "supplied": n_iterations,
        "resolved": resolved,
        "fallback_triggered": fallback_triggered,
        "reason": reason,
    }
    if fallback_triggered:
        logger.warning("%s %s", _LOG_PREFIX, log_payload)
    else:
        logger.info("%s %s", _LOG_PREFIX, log_payload)

    if resolved < min_iterations:
        raise InsufficientDataError(
            f"{_LOG_PREFIX} resolved_n={resolved} < min_iterations="
            f"{min_iterations}: {log_payload}"
        )

    return resolved


# --------------------------------------------------------------------------
# Step 2: Warm-up discard
# --------------------------------------------------------------------------

def apply_warmup_discard(
    iterations: List[Dict[str, Any]],
    discard_warmup: bool,
    min_iterations: int,
) -> List[Dict[str, Any]]:
    """
    Optionally discard iteration[0] as a warm-up run.

    Works on and returns a NEW list (copy) - the input `iterations` list
    and its dict elements are never mutated in place.

    Parameters
    ----------
    iterations:
        The (already n_iterations-resolved-length) list of iteration dicts.
    discard_warmup:
        If True, drop the first iteration before outlier detection.
    min_iterations:
        Used only to decide whether to log a WARNING if the resulting
        count underflows - per spec this never raises, only warns and
        proceeds.

    Returns
    -------
    list[dict]
        A new list, with iteration[0] removed if `discard_warmup` is True,
        otherwise an unmodified (but copied) list.
    """
    working = copy.deepcopy(iterations)

    if not discard_warmup:
        return working

    if working:
        working = working[1:]

    logger.info(
        "%s %s",
        _LOG_PREFIX,
        {"event": "warmup_discarded", "index": 0, "reason": "discard_warmup=True"},
    )

    if len(working) < min_iterations:
        logger.warning(
            "%s %s",
            _LOG_PREFIX,
            {
                "event": "post_warmup_underflow",
                "remaining": len(working),
                "min_iterations": min_iterations,
                "reason": "count fell below min_iterations after warm-up discard; "
                          "proceeding per policy (warn, do not raise)",
            },
        )

    return working


# --------------------------------------------------------------------------
# Detection method selection
# --------------------------------------------------------------------------

def select_detection_method(resolved_n: int) -> str:
    """
    Select the outlier-detection method based on the resolved sample size.

    | resolved_n | Method                        |
    |------------|-------------------------------|
    | 3 - 6      | "median_pct"                  |
    | 7 - 29     | "iqr"                         |
    | 30+        | "mad_zscore"                  |

    Parameters
    ----------
    resolved_n:
        The number of iterations remaining AFTER warm-up discard.

    Returns
    -------
    str
        One of "median_pct", "iqr", "mad_zscore".
    """
    if resolved_n <= 6:
        method = "median_pct"
    elif resolved_n <= 29:
        method = "iqr"
    else:
        method = "mad_zscore"

    logger.info(
        "%s %s",
        _LOG_PREFIX,
        {"event": "detection_method_selected", "resolved_n": resolved_n, "method": method},
    )
    return method


# --------------------------------------------------------------------------
# Helpers shared by all three detection methods
# --------------------------------------------------------------------------

def _active_metrics(iterations: List[Dict[str, Any]]) -> List[str]:
    """
    Determine which metrics should participate in outlier detection for
    this particular series: all metrics in METRIC_THRESHOLDS that are
    present, and - for optional (multi-threaded-only) metrics - not None
    across every iteration.
    """
    active = []
    for metric in _DETECTION_METRICS:
        if metric in _OPTIONAL_METRICS:
            values = [it.get(metric) for it in iterations]
            if all(v is None for v in values):
                # Not applicable for this run (e.g. single-threaded).
                continue
        active.append(metric)
    return active


def _metric_values(
    iterations: List[Dict[str, Any]], metric: str
) -> List[Tuple[int, float]]:
    """
    Return [(iteration_index, value), ...] for a metric, skipping any
    iteration where the value is None (defensive - should not normally
    happen for an "active" metric, but guards against partial data).
    """
    result = []
    for idx, it in enumerate(iterations):
        value = it.get(metric)
        if value is not None:
            result.append((idx, float(value)))
    return result


def _values_all_identical(values: List[float]) -> bool:
    """Edge case: if all values for a metric are identical, it can never
    be an outlier by definition - skip the check entirely."""
    return len(set(values)) <= 1


# --------------------------------------------------------------------------
# Method 1: % deviation from median (small samples, n = 3-6)
# --------------------------------------------------------------------------

def detect_outliers_median_pct(
    iterations: List[Dict[str, Any]],
    thresholds: Dict[str, Dict[str, float]],
) -> Tuple[List[int], Dict[int, List[str]]]:
    """
    Flag iterations whose value for any active metric deviates from that
    metric's median by more than the configured `pct` threshold.

    Returns
    -------
    (flagged_indices, flagged_metrics)
        flagged_indices: sorted list of iteration indices flagged by
                         at least one metric.
        flagged_metrics: {iteration_index: [metric_name, ...]} - which
                         metric(s) triggered the flag for each index.
    """
    flagged_metrics: Dict[int, List[str]] = {}

    for metric in _active_metrics(iterations):
        pairs = _metric_values(iterations, metric)
        if len(pairs) < 2:
            continue
        values = [v for _, v in pairs]
        if _values_all_identical(values):
            continue

        median = statistics.median(values)
        pct_threshold = thresholds[metric]["pct"]

        for idx, value in pairs:
            if median == 0:
                # Avoid division by zero; treat any non-zero deviation as
                # a full (100%+) deviation, i.e. flag it.
                deviates = value != 0
            else:
                deviation = abs(value - median) / abs(median)
                deviates = deviation > pct_threshold

            if deviates:
                flagged_metrics.setdefault(idx, []).append(metric)
                logger.debug(
                    "%s %s",
                    _LOG_PREFIX,
                    {
                        "event": "threshold_breach",
                        "method": "median_pct",
                        "metric": metric,
                        "iteration_index": idx,
                        "value": value,
                        "median": median,
                        "pct_threshold": pct_threshold,
                    },
                )

    flagged_indices = sorted(flagged_metrics.keys())
    return flagged_indices, flagged_metrics


# --------------------------------------------------------------------------
# Method 2: IQR with Tukey fences (mid samples, n = 7-29)
# --------------------------------------------------------------------------

def _quantile(sorted_values: List[float], q: float) -> float:
    """
    Simple linear-interpolation quantile (stdlib-only), used for Q1/Q3.
    `sorted_values` must already be sorted ascending.
    """
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]

    pos = q * (len(sorted_values) - 1)
    lower_idx = int(pos)
    upper_idx = min(lower_idx + 1, len(sorted_values) - 1)
    frac = pos - lower_idx
    return sorted_values[lower_idx] + (sorted_values[upper_idx] - sorted_values[lower_idx]) * frac


def detect_outliers_iqr(
    iterations: List[Dict[str, Any]],
    thresholds: Dict[str, Dict[str, float]],
) -> Tuple[List[int], Dict[int, List[str]]]:
    """
    Flag iterations whose value for any active metric falls outside the
    Tukey fence [Q1 - k*IQR, Q3 + k*IQR], where k is the metric's
    `iqr_mult` threshold.

    Returns
    -------
    (flagged_indices, flagged_metrics) - see detect_outliers_median_pct().
    """
    flagged_metrics: Dict[int, List[str]] = {}

    for metric in _active_metrics(iterations):
        pairs = _metric_values(iterations, metric)
        if len(pairs) < 4:
            # IQR is unreliable with too few points even within the
            # "7-29" band if metric-specific data is sparse; fall back to
            # median_pct behavior for this single metric.
            values = [v for _, v in pairs]
            if len(pairs) >= 2 and not _values_all_identical(values):
                median = statistics.median(values)
                pct_threshold = thresholds[metric]["pct"]
                for idx, value in pairs:
                    deviation = abs(value - median) / abs(median) if median != 0 else (1.0 if value != 0 else 0.0)
                    if deviation > pct_threshold:
                        flagged_metrics.setdefault(idx, []).append(metric)
            continue

        values = [v for _, v in pairs]
        if _values_all_identical(values):
            continue

        sorted_values = sorted(values)
        q1 = _quantile(sorted_values, 0.25)
        q3 = _quantile(sorted_values, 0.75)
        iqr = q3 - q1
        mult = thresholds[metric]["iqr_mult"]

        if iqr == 0:
            # Degenerate distribution (all but a couple of ties); fall
            # back to flagging any value that differs from the mode.
            logger.debug(
                "%s %s",
                _LOG_PREFIX,
                {
                    "event": "metric_skipped",
                    "method": "iqr",
                    "metric": metric,
                    "reason": "iqr_is_zero",
                    "q1": q1,
                    "q3": q3,
                },
            )
            continue

        lower_fence = q1 - mult * iqr
        upper_fence = q3 + mult * iqr

        for idx, value in pairs:
            if value < lower_fence or value > upper_fence:
                flagged_metrics.setdefault(idx, []).append(metric)
                logger.debug(
                    "%s %s",
                    _LOG_PREFIX,
                    {
                        "event": "threshold_breach",
                        "method": "iqr",
                        "metric": metric,
                        "iteration_index": idx,
                        "value": value,
                        "q1": q1,
                        "q3": q3,
                        "iqr": iqr,
                        "lower_fence": lower_fence,
                        "upper_fence": upper_fence,
                    },
                )

    flagged_indices = sorted(flagged_metrics.keys())
    return flagged_indices, flagged_metrics


# --------------------------------------------------------------------------
# Method 3: Modified Z-score (MAD-based), large samples n = 30+
# --------------------------------------------------------------------------

def detect_outliers_mad_zscore(
    iterations: List[Dict[str, Any]],
    thresholds: Dict[str, Dict[str, float]],
) -> Tuple[List[int], Dict[int, List[str]]]:
    """
    Flag iterations whose modified Z-score (based on Median Absolute
    Deviation) for any active metric exceeds that metric's `mad_z`
    threshold.

    Modified Z-score formula (Iglewicz & Hoaglin):
        MZS_i = 0.6745 * (x_i - median) / MAD
    where MAD = median(|x_i - median|).

    Returns
    -------
    (flagged_indices, flagged_metrics) - see detect_outliers_median_pct().
    """
    flagged_metrics: Dict[int, List[str]] = {}

    for metric in _active_metrics(iterations):
        pairs = _metric_values(iterations, metric)
        if len(pairs) < 2:
            continue
        values = [v for _, v in pairs]
        if _values_all_identical(values):
            continue

        median = statistics.median(values)
        abs_devs = [abs(v - median) for v in values]
        mad = statistics.median(abs_devs)
        z_threshold = thresholds[metric]["mad_z"]

        if mad == 0:
            # All values equal the median except a few ties; any nonzero
            # deviation is effectively infinite Z - flag those directly.
            for idx, value in pairs:
                if value != median:
                    flagged_metrics.setdefault(idx, []).append(metric)
            continue

        for idx, value in pairs:
            modified_z = 0.6745 * (value - median) / mad
            if abs(modified_z) > z_threshold:
                flagged_metrics.setdefault(idx, []).append(metric)
                logger.debug(
                    "%s %s",
                    _LOG_PREFIX,
                    {
                        "event": "threshold_breach",
                        "method": "mad_zscore",
                        "metric": metric,
                        "iteration_index": idx,
                        "value": value,
                        "median": median,
                        "mad": mad,
                        "modified_z": modified_z,
                        "z_threshold": z_threshold,
                    },
                )

    flagged_indices = sorted(flagged_metrics.keys())
    return flagged_indices, flagged_metrics


_METHOD_DISPATCH = {
    "median_pct": detect_outliers_median_pct,
    "iqr": detect_outliers_iqr,
    "mad_zscore": detect_outliers_mad_zscore,
}


# --------------------------------------------------------------------------
# Summary statistics
# --------------------------------------------------------------------------

def compute_summary_stats(clean_iterations: List[Dict[str, Any]]) -> Dict[str, Dict[str, float]]:
    """
    Compute median/mean/min/max/stddev for every metric present in the
    clean (post-discard) iteration series. Optional metrics that are None
    across the whole series are omitted from the summary.

    Parameters
    ----------
    clean_iterations:
        The final list of iteration dicts surviving outlier discard.

    Returns
    -------
    dict
        {metric_name: {"median": ..., "mean": ..., "min": ..., "max": ...,
                        "stddev": ...}, ...}
    """
    summary: Dict[str, Dict[str, float]] = {}

    for metric in _active_metrics(clean_iterations):
        pairs = _metric_values(clean_iterations, metric)
        values = [v for _, v in pairs]
        if not values:
            continue

        stddev = statistics.stdev(values) if len(values) > 1 else 0.0
        summary[metric] = {
            "median": statistics.median(values),
            "mean": statistics.mean(values),
            "min": min(values),
            "max": max(values),
            "stddev": stddev,
        }

    return summary


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------

def run_outlier_detection(
    iterations: List[Dict[str, Any]],
    n_iterations: Optional[int] = None,
    min_iterations: int = 3,
    benchmark_variant: str = "cpu_1t",
    run_id: str = "",
    retry_count: int = 0,
    max_retries: int = 2,
) -> Dict[str, Any]:
    """
    Analyze a series of sysbench CPU iteration dicts for outliers and
    return a structured verdict.

    This is a PURE function: it never triggers new sysbench collection
    itself. When it raises `BenchmarkUnstableError`, the CALLING harness
    is responsible for discarding the whole series, collecting a fresh
    one, and invoking this function again with `retry_count` incremented
    by 1. If the harness's own retry loop reaches `max_retries` and the
    series is still unstable, this function raises
    `BenchmarkAbortedError` instead of `BenchmarkUnstableError` so the
    harness knows to stop retrying.

    Parameters
    ----------
    iterations:
        list[dict] - one dict per collected sysbench CPU iteration (see
        module docstring for the expected metric schema). Never mutated.
    n_iterations:
        Caller-supplied iteration count; validated/resolved via
        `resolve_n_iterations()` (falls back to len(iterations) on any
        mismatch/invalid value).
    min_iterations:
        Minimum number of valid iterations required to proceed (default 3).
    benchmark_variant:
        Free-form label identifying which sysbench CPU variant this series
        belongs to (e.g. "cpu_1t", "cpu_4t") - included in exception
        payloads and logs for traceability only.
    run_id:
        Free-form identifier for this benchmark run/campaign - included in
        exception payloads and logs for traceability only.
    retry_count:
        How many retries the CALLER has already performed for this
        specific benchmark_variant/run_id (0 on the first attempt). Not
        part of the originally specified public signature, but added as
        a keyword-only-by-convention parameter so this stateless module
        can still enforce the "max 2 retries then abort" policy without
        holding any internal state itself.
    max_retries:
        Ceiling on retries (default 2), matching the specification's
        "Maximum retries = 2".

    Returns
    -------
    dict
        On a CLEAN or VALID outcome, matches the schema specified in the
        module-level "Return Schema" section:
        {
          "status", "benchmark_variant", "resolved_n", "effective_n",
          "detection_method", "warmup_discarded", "discarded_indices",
          "discarded_metrics", "retry_count", "clean_iterations",
          "summary_stats", "resolution_log"
        }

    Raises
    ------
    InsufficientDataError
        If resolved_n < min_iterations (raised by resolve_n_iterations()).
    BenchmarkUnstableError
        If 2+ iterations are flagged as outliers and `retry_count` is
        still below `max_retries`. The caller should discard the whole
        series, collect a fresh one, and call again with
        retry_count + 1.
    BenchmarkAbortedError
        If 2+ iterations are still flagged as outliers AND
        `retry_count >= max_retries` - the caller must stop retrying and
        surface this as a hard failure for the benchmark variant.
    """
    # ---- Step 1: resolve n_iterations -----------------------------------
    resolution_log: Dict[str, Any] = {}

    def _capture_resolution_log():
        # resolve_n_iterations() already logs; we recompute the same
        # values here (cheaply) purely to embed them in the return payload
        # without changing that function's signature/contract.
        actual_len = len(iterations)
        if not isinstance(n_iterations, int) or isinstance(n_iterations, bool):
            return {
                "supplied": n_iterations, "resolved": actual_len,
                "fallback_triggered": True,
                "reason": "non-int/None supplied; fallback to len(iterations)",
            }
        if n_iterations <= 0:
            return {
                "supplied": n_iterations, "resolved": actual_len,
                "fallback_triggered": True,
                "reason": "zero/negative supplied; fallback to len(iterations)",
            }
        if n_iterations != actual_len:
            return {
                "supplied": n_iterations, "resolved": actual_len,
                "fallback_triggered": True,
                "reason": "supplied != len(iterations); fallback to len(iterations)",
            }
        return {
            "supplied": n_iterations, "resolved": n_iterations,
            "fallback_triggered": False,
            "reason": "supplied value matched len(iterations); used as-is",
        }

    resolution_log = _capture_resolution_log()
    resolved_n = resolve_n_iterations(n_iterations, iterations, min_iterations)

    # ---- Step 2: Set working list -----------------------------------------
    # Warm-up discard is now handled entirely by the calling benchmarks 
    # before passing iterations to this function.
    working = copy.deepcopy(iterations)
    effective_n_before_outliers = len(working)

    # ---- Step 3: select detection method ----------------------------------
    method = select_detection_method(effective_n_before_outliers)

    # ---- Step 4: run outlier detection -------------------------------------
    detect_fn = _METHOD_DISPATCH[method]
    flagged_indices, flagged_metrics = detect_fn(working, METRIC_THRESHOLDS)
    num_flagged = len(flagged_indices)

    # ---- Step 5: apply run-level verdict rules -----------------------------
    if num_flagged == 0:
        status = "CLEAN"
        clean_iterations = working
        discarded_indices: List[int] = []
        discarded_metrics: Dict[int, List[str]] = {}

        logger.info(
            "%s %s",
            _LOG_PREFIX,
            {
                "event": "run_status",
                "status": status,
                "benchmark_variant": benchmark_variant,
                "run_id": run_id,
                "retry_count": retry_count,
            },
        )

    elif num_flagged == 1:
        status = "VALID"
        bad_idx = flagged_indices[0]
        clean_iterations = [it for i, it in enumerate(working) if i != bad_idx]
        discarded_indices = [bad_idx]
        discarded_metrics = {bad_idx: flagged_metrics[bad_idx]}

        logger.warning(
            "%s %s",
            _LOG_PREFIX,
            {
                "event": "outlier_discarded",
                "status": status,
                "benchmark_variant": benchmark_variant,
                "run_id": run_id,
                "discarded_index": bad_idx,
                "discarded_metrics": flagged_metrics[bad_idx],
                "retry_count": retry_count,
            },
        )

        if len(clean_iterations) < min_iterations:
            logger.warning(
                "%s %s",
                _LOG_PREFIX,
                {
                    "event": "post_discard_underflow",
                    "remaining": len(clean_iterations),
                    "min_iterations": min_iterations,
                    "reason": "count fell below min_iterations after single-outlier "
                              "discard; proceeding per policy (warn, do not raise)",
                },
            )

    else:
        # 2+ flagged -> UNSTABLE. Decide between "retry" (BenchmarkUnstableError)
        # and "abort" (BenchmarkAbortedError) based on retry_count vs max_retries.
        if retry_count >= max_retries:
            action = "ABORTED"
            payload = _exception_payload(
                run_id=run_id,
                benchmark_variant=benchmark_variant,
                reason="max_retries_exceeded",
                retry_count=retry_count,
                flagged_iterations=flagged_indices,
                flagged_metrics=flagged_metrics,
                action=action,
            )
            logger.warning("%s %s", _LOG_PREFIX, {"event": "benchmark_aborted", **payload})
            raise BenchmarkAbortedError(payload)
        else:
            action = "DISCARD_AND_RECOLLECT"
            payload = _exception_payload(
                run_id=run_id,
                benchmark_variant=benchmark_variant,
                reason=f"{num_flagged} iterations flagged as outliers (>=2)",
                retry_count=retry_count,
                flagged_iterations=flagged_indices,
                flagged_metrics=flagged_metrics,
                action=action,
            )
            logger.warning("%s %s", _LOG_PREFIX, {"event": "benchmark_unstable", **payload})
            raise BenchmarkUnstableError(payload)

    # ---- Step 6: build return schema --------------------------------------
    summary_stats = compute_summary_stats(clean_iterations)

    result = {
        "status": status,
        "benchmark_variant": benchmark_variant,
        "resolved_n": resolved_n,
        "effective_n": len(clean_iterations),
        "detection_method": method,
        "discarded_indices": discarded_indices,
        "discarded_metrics": {str(k): v for k, v in discarded_metrics.items()},
        "retry_count": retry_count,
        "clean_iterations": clean_iterations,
        "summary_stats": summary_stats,
        "resolution_log": resolution_log,
    }

    logger.info(
        "%s %s",
        _LOG_PREFIX,
        {
            "event": "run_outlier_detection_complete",
            "status": status,
            "benchmark_variant": benchmark_variant,
            "run_id": run_id,
            "effective_n": result["effective_n"],
            "detection_method": method,
        },
    )

    return result


# --------------------------------------------------------------------------
# Self-test (manual sanity check; not a substitute for a real test suite)
# --------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(message)s")

    # Simulate the example from the requirement: iteration #2 (index 1) is
    # an outlier; single outlier -> VALID with 1 discard.
    sample_iterations = [
        {"num_threads": 1, "cpu_max_prime": 20000, "total_time_sec": 30.0,
         "cpu_events_per_sec": 1009.68, "latency_min_ms": 0.99, "latency_avg_ms": 0.99,
         "latency_p95_ms": 0.99, "latency_max_ms": 1.53, "total_events": 30294,
         "fairness_events_stddev": None, "fairness_time_stddev": None, "scaling_efficiency": None},
        {"num_threads": 1, "cpu_max_prime": 20000, "total_time_sec": 30.0,
         "cpu_events_per_sec": 1300.00, "latency_min_ms": 0.75, "latency_avg_ms": 0.75,
         "latency_p95_ms": 0.75, "latency_max_ms": 1.10, "total_events": 39000,
         "fairness_events_stddev": None, "fairness_time_stddev": None, "scaling_efficiency": None},
        {"num_threads": 1, "cpu_max_prime": 20000, "total_time_sec": 30.0,
         "cpu_events_per_sec": 1009.70, "latency_min_ms": 0.99, "latency_avg_ms": 0.99,
         "latency_p95_ms": 0.99, "latency_max_ms": 1.54, "total_events": 30294,
         "fairness_events_stddev": None, "fairness_time_stddev": None, "scaling_efficiency": None},
        {"num_threads": 1, "cpu_max_prime": 20000, "total_time_sec": 30.0,
         "cpu_events_per_sec": 1009.07, "latency_min_ms": 0.99, "latency_avg_ms": 0.99,
         "latency_p95_ms": 0.99, "latency_max_ms": 1.65, "total_events": 30276,
         "fairness_events_stddev": None, "fairness_time_stddev": None, "scaling_efficiency": None},
    ]

    import json as _json
    out = run_outlier_detection(
        sample_iterations,
        n_iterations=4,
        min_iterations=3,
        benchmark_variant="cpu_1t",
        run_id="self_test",
    )
    # clean_iterations contains dicts; print a trimmed view for readability.
    printable = dict(out)
    printable["clean_iterations"] = [
        {"cpu_events_per_sec": it["cpu_events_per_sec"]} for it in out["clean_iterations"]
    ]
    print(_json.dumps(printable, indent=2))
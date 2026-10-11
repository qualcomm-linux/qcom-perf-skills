# COT: Regression Detection Consensus Engine

## Goal
Determine if a performance delta between a baseline run and a current run represents a statistically significant regression. The engine uses a multi-method consensus approach to filter out noise, avoiding the fragility of simple percentage-drop thresholds in non-Gaussian IIOT environments.

## Inputs Needed
- `baseline_metrics`: Raw metric array (or precalculated mean/stddev) from the baseline run
- `current_metrics`: Raw metric array from the current run
- `test_name`: The name of the benchmark metric being evaluated
- `metric_directions`: Already-resolved higher/lower-is-better per metric (authoritative; see Phase 1)
- `thresholds`: Device-specific thresholds (from `benchmark_knowledge.md` or `benchmarks.yaml`)

## Phase 1: Metric Direction & Data Preparation

1. **Determine Metric Direction**
   The orchestrator always supplies the already-resolved direction for every metric in the input's `metric_directions` map (sourced authoritatively from `config/benchmarks.yaml`'s per-metric/per-benchmark `metric_config`/`metric_direction`) -- use that value directly; do not re-derive it. Only if a metric is absent from `metric_directions` entirely, fall back to looking it up in `benchmark_knowledge.md`, defaulting to "higher is better" if not found there either.
   ```python
   is_lower_better = metric_directions.get(test_name) == "lower"

   # If lower is better, a POSITIVE delta is a regression. 
   # If higher is better, a NEGATIVE delta is a regression.
   # Normalization rule: We always calculate delta such that a regression is a value < threshold
   ```

2. **Calculate Raw Deltas**
   ```python
   # For throughput (higher is better):
   tp_delta = (current_median - baseline_median) / baseline_median
   # Regression occurs when tp_delta < threshold (e.g., tp_delta < -0.05)
   
   # For latency (lower is better):
   lat_delta = (current_mean - baseline_mean) / baseline_mean
   # Regression occurs when lat_delta > threshold (e.g., lat_delta > 0.10)
   ```

## Phase 2: Stability Gate (Throughput Only)

```python
IF NOT latency_metric:
    Calculate Robust CV of current run (using Median Absolute Deviation)
    robust_cv = (1.4826 * MAD(current)) / median(current)
    
    IF robust_cv > STABILITY_GATE (e.g., 0.10) AND tp_delta >= threshold:
        # Run is too noisy and hasn't obviously crashed
        return {
            "stability_valid": False, 
            "stability_reason": "Unstable: Robust CV > STABILITY_GATE",
            "regression_detected": False
        }
```

## Phase 3: Multi-Method Consensus Evaluation

Apply these four statistical tests to the raw data arrays.

### Primary Methods
1. **Median Delta:** `median(current) - median(baseline) / median(baseline) < threshold`
2. **Mann-Whitney U Test:** `p_value < 0.05` AND median shift matches regression direction.
   *(Fallback if scipy unavailable: >60% of current samples are worse than baseline median by the threshold amount).*

### Secondary Methods
3. **Cohen's d Effect Size:** `d < -0.5` (large practical effect) AND mean delta is regression.
4. **Quantile (25th Percentile) Delta:** `delta(Q25) < threshold` (the performance "floor" has dropped).

### Consensus Logic

```python
primary_hits = sum([Median_Delta_Hit, Mann_Whitney_Hit])
secondary_hits = sum([Cohens_d_Hit, Quantile_Hit])
used_mw_fallback = (Mann-Whitney used the 60% fallback heuristic)

IF primary_hits >= 2:
    IF used_mw_fallback AND secondary_hits < 2:
        return NO_REGRESSION ("No consensus: Used fallback MW, secondary disagreed")
    ELSE:
        return REGRESSION (Confidence: 95%, "High confidence consensus")

ELIF primary_hits >= 1 AND secondary_hits >= 1:
    IF used_mw_fallback AND primary_hits == 1 AND delta >= threshold*2 AND secondary_hits < 2:
        return NO_REGRESSION ("No consensus: Used fallback MW, but effect size/quantile disagreed")
    ELSE:
        return REGRESSION (Confidence: 75%, "Medium confidence consensus")

ELIF raw_samples < 3 AND tp_delta < threshold:
    # Too little data for robust statistics
    return REGRESSION (Confidence: 50%, "Small sample delta fallback")

ELSE:
    return NO_REGRESSION ("No consensus reached")
```

## Phase 4: Absolute Latency Failure (Latency Only)

```python
IF is_latency_metric:
    IF current_mean > LATENCY_ABSOLUTE_FAIL (e.g., 2000ms):
        return REGRESSION (Critical Fail: Latency > absolute fail threshold)
    ELIF current_mean > LATENCY_ABSOLUTE_WARN (e.g., 500ms):
        return REGRESSION (Warning: Latency > absolute warn threshold)
    ELIF lat_delta > latency_threshold (e.g., 10%):
        return REGRESSION (Relative Fail: Latency spiked > percentage threshold)
    ELSE:
        return NO_REGRESSION

## Phase 5: Trend Detection (Multi-Run History)

This phase is only applicable when `rca_all_runs=True` and ≥4 historical run values are available for the metric. It detects **gradual, sustained performance drift** that individual run-to-run comparisons may miss.

### Method 1: CUSUM (Cumulative Sum Control Chart)

Detects sustained shifts in the mean. Accumulates deviations from the historical mean; a sustained drift causes the CUSUM statistic to exceed a decision threshold.

```python
# Parameters
k = 0.5 * historical_stddev   # Allowable slack (half a standard deviation)
h = 5.0 * historical_stddev   # Decision threshold (5 standard deviations)

cusum_pos = 0  # Detects upward drift (regression for lower-is-better metrics)
cusum_neg = 0  # Detects downward drift (regression for higher-is-better metrics)

FOR each value in [historical_values..., current_value]:
    cusum_pos = max(0, cusum_pos + (value - historical_mean - k))
    cusum_neg = max(0, cusum_neg + (historical_mean - value - k))

IF cusum_neg > h AND NOT is_lower_better:
    return TREND_REGRESSION (type: "Sustained Downward Drift", cusum=cusum_neg)
ELIF cusum_pos > h AND is_lower_better:
    return TREND_REGRESSION (type: "Sustained Upward Drift (Latency)", cusum=cusum_pos)
```

### Method 2: Mann-Kendall Trend Test

Non-parametric test for monotonic trends. Counts concordant vs. discordant pairs across the time series.

```python
n = len(all_values)  # historical + current
s = 0
FOR i in range(n-1):
    FOR j in range(i+1, n):
        IF all_values[j] > all_values[i]: s += 1
        ELIF all_values[j] < all_values[i]: s -= 1

var_s = n * (n-1) * (2*n+5) / 18
z = (s - sign(s)) / sqrt(var_s)
p_value = 2 * (1 - norm_cdf(abs(z)))

IF p_value < 0.05 AND s < 0 AND NOT is_lower_better:
    return TREND_REGRESSION (type: "Monotonic Downward Trend", p_value=p_value)
ELIF p_value < 0.05 AND s > 0 AND is_lower_better:
    return TREND_REGRESSION (type: "Monotonic Upward Trend (Latency)", p_value=p_value)
```

### Trend Verdict Output

```python
{
  "trend_detected": True,
  "trend_type": "Sustained Downward Drift",  # or "Monotonic Downward Trend"
  "delta_percent": (current_value - historical_mean) / historical_mean * 100,
  "cusum_statistic": 12.5,   # CUSUM value (if CUSUM triggered)
  "mk_p_value": 0.012,       # Mann-Kendall p-value (if MK triggered)
  "runs_analyzed": 8,
  "confidence": "75%"        # Trend regressions use 75% confidence (multi-run evidence)
}
```

**Note:** Trend detection results are reported as a separate comparison entry in `rca_report.json` (label: `"trend-level: across N runs"`), not merged with run-level or build-level comparisons.

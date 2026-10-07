# COT: Statistical Methods Reference

This document provides the explicit algorithms and pseudocode for the statistical methods used in the regression detection consensus engine.

## 1. Median Absolute Deviation (MAD) Outlier Removal

MAD is more robust than Standard Deviation for IIOT benchmarks because it is not skewed by massive outliers (e.g., a single severe thermal throttle spike).

**Algorithm:**
```python
def remove_outliers_mad(samples):
    if len(samples) < 3:
        return samples
        
    median = calculate_median(samples)
    
    # Calculate absolute deviations from median
    deviations = [abs(x - median) for x in samples]
    
    # MAD is the median of the absolute deviations
    mad = calculate_median(deviations)
    
    if mad == 0:
        return samples  # No variance
        
    # Remove points > 3 MADs away from median
    cleaned = []
    for x in samples:
        if abs(x - median) <= 3 * mad:
            cleaned.append(x)
            
    # Always return at least some data
    return cleaned if len(cleaned) > 0 else samples
```

## 2. Mann-Whitney U Test (Fallback Implementation)

Since embedded environments often lack Python's `scipy` library, we use a robust heuristic fallback if the exact U-test cannot be calculated.

**Scipy Implementation (if available):**
```python
from scipy import stats
_, p_value = stats.mannwhitneyu(baseline, current, alternative='two-sided')
is_significant = (p_value < 0.05)
```

**Fallback Heuristic (if scipy unavailable):**
```python
# A simple non-parametric approach: count how many current samples are worse 
# than the baseline median by at least the threshold amount.
baseline_median = calculate_median(baseline)
threshold_val = baseline_median * (1 + throughput_threshold) # e.g., baseline * 0.95

worse_count = 0
for sample in current:
    if sample < threshold_val:
        worse_count += 1
        
# If >= 60% of current samples are worse than the baseline median by the threshold
is_significant = (worse_count / len(current)) >= 0.60
```

## 3. Cohen's d Effect Size

Evaluates if a difference is practically significant (not just statistically significant).

**Algorithm:**
```python
def calculate_cohens_d(baseline, current):
    mean1 = calculate_mean(baseline)
    mean2 = calculate_mean(current)
    std1 = calculate_stddev(baseline)
    std2 = calculate_stddev(current)
    n1, n2 = len(baseline), len(current)
    
    # Pooled standard deviation
    if n1 + n2 - 2 <= 0:
        return 0.0
        
    pooled_variance = ((n1-1)*(std1**2) + (n2-1)*(std2**2)) / (n1+n2-2)
    pooled_std = math.sqrt(pooled_variance)
    
    if pooled_std == 0:
        return 0.0
        
    # d = (mean2 - mean1) / pooled_std
    return (mean2 - mean1) / pooled_std
    
# Effect size interpretation:
# |d| > 0.2: Small effect
# |d| > 0.5: Medium effect (our threshold for secondary consensus hit)
# |d| > 0.8: Large effect
```

## 4. Quantile (25th Percentile) Comparison

Ensures that the performance "floor" has genuinely dropped, guarding against cases where only the top-end performance fluctuated.

**Algorithm:**
```python
def calculate_percentile(data, p):
    # Basic percentile without numpy
    s = sorted(data)
    k = (len(s) - 1) * (p / 100.0)
    f = int(k)
    c = int(k + 0.5) if k % 1 != 0 else f
    
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)

baseline_q25 = calculate_percentile(baseline, 25)
current_q25 = calculate_percentile(current, 25)

delta_q25 = (current_q25 - baseline_q25) / baseline_q25
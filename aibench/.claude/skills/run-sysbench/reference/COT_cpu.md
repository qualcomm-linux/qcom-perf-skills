# COT: CPU Regression Diagnosis

## Goal
Determine the root cause of a throughput drop or latency spike during sysbench CPU tests (`cpu_prime_single` or `cpu_prime_multi`).

## Inputs Needed
- `aibench/common/scripts/output/analysis_results.json` (contains throughput delta, latency delta, stability valid flag, frequency drops, thermal throttles, oom kills)

## Workflow

### Step 1: Stability Gate
```
if stability_valid == False:
    → The test results are too noisy (StdDev > 10%).
    → Do NOT proceed with regression analysis.
    → Recommendation: Rerun the test to get stable results (ensure background tasks are minimized).
```

### Step 2: Throughput Drop Diagnosis
```
if throughput_delta_percent < -5.0:
    → Throughput has regressed. Check `anomaly_summary.json` for frequency drops.
    
    if cpu_frequency_drops.count > 0:
        → DIAGNOSIS: DVFS / Thermal Throttling. The CPU frequency was lowered during the test, directly impacting throughput.
        → Check thermal_throttles list to confirm if temperature was the trigger.
        → RECOMMENDATION: Investigate thermal design, cooling, or background workloads heating the SoC.

    elif oom_kills.count > 0:
        → DIAGNOSIS: Severe Memory Pressure. System killed processes, disrupting test execution.
        → RECOMMENDATION: Check memory usage (top/vmstat) during test.

    else:
        → DIAGNOSIS: AMBIGUOUS CPU Bottleneck. Throughput dropped without obvious frequency scaling or memory issues.
        → RECOMMENDATION: Trigger a targeted rerun of the failing test using `perf record --call-graph dwarf`. Analyze the perf output for scheduler misbalance, increased cache misses, or lock contention in the kernel.
```

### Step 3: Latency Spike Diagnosis
```
if latency_95_delta_percent > 10.0:
    → 95th percentile latency spiked. Check `anomaly_summary.json` for context switches.
    
    if context_switch_spike.count > 0:
        → DIAGNOSIS: Scheduler Contention / Preemption. The CPU test threads are being interrupted frequently.
        → RECOMMENDATION: Check thread counts and CPU affinity. Ensure background tasks aren't preempting the benchmark.

    else:
        → DIAGNOSIS: AMBIGUOUS Latency Issue.
        → RECOMMENDATION: Trigger a targeted rerun using `perf sched record` to analyze wake-up latencies and scheduling delays.
```

### Step 4: Absolute Latency Failure
```
if current_latency_95_mean > 2000:
    → CRITICAL FAIL: Latency exceeds 2 seconds.
    → Look for complete system hangs, CPU offline events, or thermal shutdown warnings in `dmesg`.
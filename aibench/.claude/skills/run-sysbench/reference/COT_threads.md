# COT: Threads Regression Diagnosis

## Goal
Determine the root cause of a throughput drop or latency spike during sysbench thread tests (`threads_single` or `threads_multi`).

## Inputs Needed
- `aibench/common/scripts/output/analysis_results.json`

## Workflow

### Step 1: Stability Gate
```
if stability_valid == False:
    → Mark as INVALID. StdDev > 10%. Rerun required.
```

### Step 2: Thread Scalability Collapse?
```
Compare single-thread throughput vs multi-thread throughput.
if throughput_multi < throughput_single * (num_cores / 2):
    → Severe scalability issue.
    → Check `anomaly_summary.json` for context_switch_spike.
    
    if context_switch_spike.count > 0:
        → DIAGNOSIS: Load Imbalance / Thread Migration. Threads are bouncing between cores excessively.
        → RECOMMENDATION: Targeted rerun with `perf sched record` to visualize migration patterns. Consider pinning threads using `taskset`.
        
    else:
        → Check if CPU frequencies dropped significantly (DVFS).
        → DIAGNOSIS: Potential NUMA serialization, cache coherency overhead, or frequency capping.
```

### Step 3: Context Switch Spikes vs Baseline
```
If context switches (CS) are significantly higher than the baseline build:
    if frequency_drops.count > 0 or thermal_throttles.count > 0:
        → DIAGNOSIS: Thermal-induced contention. CPU throttling increases execution time, leading to more overlapping thread executions and preemptions.
        
    else:
        → DIAGNOSIS: Pure Scheduler Contention. A kernel change may have altered scheduling latency or fairness.
        → RECOMMENDATION: `perf lock contention` or `perf sched` analysis.
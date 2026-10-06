# COT: Mutex Regression Diagnosis

## Goal
Diagnose throughput collapse or latency spikes in the sysbench mutex benchmark (`mutex_single`, `mutex_multi`).

## Inputs Needed
- `aibench/common/scripts/output/analysis_results.json`

## Workflow

### Step 1: Stability Gate
```
if stability_valid == False:
    → Mark as INVALID. StdDev > 10%. Rerun required.
```

### Step 2: Throughput Collapse Analysis
```
if throughput_delta_percent < -5.0:
    → Check system_time ratio (from top_metrics parsing, if available).
    
    if system_time >> user_time:
        → DIAGNOSIS: Kernel Lock Contention. Threads are spinning in the kernel trying to acquire locks.
        → RECOMMENDATION: Run `perf record --call-graph dwarf` targeting the kernel to identify lock hotspots (e.g., `_raw_spin_lock`).
        
    else:
        → Check `anomaly_summary.json` for frequency_drops or thermal_throttles.
        if frequency_drops.count > 0:
            → DIAGNOSIS: DVFS / Thermal bottleneck causing slower lock acquisition/release times.
            
        else:
            → DIAGNOSIS: AMBIGUOUS. User-space contention or standard CPU bottleneck.
```

### Step 3: Futex/Dmesg Events
```
Check `dmesg_metrics.log` anomalies:
if "softlockup" in dmesg:
    → DIAGNOSIS: CRITICAL Lockup. A kernel thread is stuck holding a lock.
    → RECOMMENDATION: Extract the softlockup stack trace from dmesg immediately.
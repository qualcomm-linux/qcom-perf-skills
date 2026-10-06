# COT: Memory Bandwidth Regression Diagnosis

## Goal
Diagnose throughput drop or latency issues in memory benchmarks (`memory_seq_read`, `memory_seq_write`, `memory_rnd_read`, `memory_rnd_write`).

## Inputs Needed
- `aibench/common/scripts/output/analysis_results.json`

## Workflow

### Step 1: Stability Gate
```
if stability_valid == False:
    → Mark as INVALID. StdDev > 10%. Rerun required.
```

### Step 2: Bandwidth (Throughput) Drop Analysis
```
if throughput_delta_percent < -5.0:
    
    Check `anomaly_summary.json` for swap_activity_spike:
    if swap_activity_spike.count > 0:
        → DIAGNOSIS: Cache Misses / Memory Reclaim Pressure. The system is struggling to map pages or is actively reclaiming them.
        → RECOMMENDATION: Check dmesg for compaction or direct reclaim events. 
        
    Check `anomaly_summary.json` for frequency_drops:
    if frequency_drops.count > 0:
        → DIAGNOSIS: DVFS / Thermal Limiting. Lower CPU frequency directly impacts the memory controller and bandwidth.
        
    If no faults and no frequency drops:
        → DIAGNOSIS: Hardware Bandwidth Throttling or QoS limits. Memory controller may be limiting bandwidth due to thermal or power constraints not visible in CPU freq.
```

### Step 3: Access Pattern Profiling (Sequential vs Random)
```
Compare `memory_seq_read` vs `memory_rnd_read` latency:
if seq_read_latency > rnd_read_latency:
    → DIAGNOSIS: Prefetching Issue. Sequential reads should heavily benefit from hardware prefetchers. If random is faster, the prefetcher is likely misconfigured or disabled.
    → RECOMMENDATION: Verify hardware prefetch settings. Check NUMA locality.
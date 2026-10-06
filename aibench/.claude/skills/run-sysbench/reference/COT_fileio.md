# COT: File I/O Regression Diagnosis

## Goal
Diagnose throughput collapse or latency spikes in sysbench storage tests (`fileio_seq_read`, `fileio_rnd_write`, etc.).

## Inputs Needed
- `aibench/common/scripts/output/analysis_results.json`

## Workflow

### Step 1: Stability Gate
```
if stability_valid == False:
    → Mark as INVALID. StdDev > 10%. Rerun required.
    → Note: Storage can be naturally noisy due to garbage collection or write-amplification. If consistently noisy, consider wiping the device or running `fstrim`.
```

### Step 2: I/O Wait Spike Analysis
```
if throughput_delta_percent < -5.0:
    
    Check `anomaly_summary.json` for io_wait_spike:
    if io_wait_spike.count > 0:
        → CPU is spending time waiting for storage controller.
        
        Check dmesg for driver errors:
        if storage driver timeouts or UFS errors present:
            → DIAGNOSIS: Storage Hardware/Driver Failure.
            → RECOMMENDATION: Extract dmesg errors, escalate to storage/BSP team.
            
        else:
            → DIAGNOSIS: I/O Scheduler or Queue Congestion.
            → RECOMMENDATION: Verify I/O scheduler (e.g., mq-deadline, kyber) and queue depth.
            
    else:
        → No I/O wait spike, but throughput dropped.
        Check `anomaly_summary.json` for frequency_drops:
        if frequency_drops.count > 0:
            → DIAGNOSIS: DVFS Capping. The CPU running the I/O threads is being throttled, limiting how fast it can dispatch I/O requests to the storage controller.
            
        else:
            → DIAGNOSIS: AMBIGUOUS CPU-side Contention.
            → RECOMMENDATION: Run `perf record` targeting both CPU and I/O interactions.
```

### Step 3: Write vs Read Penalty
```
If `fileio_rnd_write` regressed severely but `fileio_rnd_read` remained stable:
    → DIAGNOSIS: Storage Write Amplification / Garbage Collection. The flash storage controller may be saturated handling background block erasure.
    → RECOMMENDATION: Run `fstrim /opt/sysbench-data` and repeat the test.
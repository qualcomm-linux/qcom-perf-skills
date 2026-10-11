# COT: Memory Benchmarks RCA Guide

This document provides benchmark-specific guidance for interpreting regressions across memory-specific benchmarks (`bw_mem`, `lat_mem_rd`, and `ramspeed`).

## 1. Bandwidth Memory (`bw_mem`)

**Primary Metric:** `bw_mem_*_plateau` (GB/s - Higher is better)
*(Operations: rd, wr, cp, fwr, frd, fcp)*

### Expected Anomaly Signatures
- **DDR Thermal Throttling:** Check `thermal_throttles` for `ddrss-*-thermal` zones specifically. Sustained memory bandwidth tests can overheat the memory controller without necessarily maxing out CPU thermals.
- **Cache Eviction / Task Migration:** High `ftrace.migration_count` (>500) destroys L1/L2 cache locality, artificially lowering bandwidth scores as data must be fetched from slower L3 or main memory.

## 2. Latency Memory Read (`lat_mem_rd`)

**Primary Metrics:** 
- `lat_mem_rd_plateau` (ns - Lower is better)
- `lat_mem_rd_spread` (% - Lower is better)

### Expected Anomaly Signatures
- **Preemption & Interrupts:** This test measures nanosecond-level access times. Spikes in latency are almost always caused by the OS interrupting the test thread.
  - **Signature:** `vmstat.context_switches` is high, or `ftrace.sched_wakeup_latency_us` spikes.
- **DVFS Impact:** If CPU frequency drops (`cpu_frequency_drops`), memory access latency increases because the core executing the load instructions is running slower.

## 3. RAMSpeed (`ramspeed`)

**Primary Metrics:**
- `ramspeed_multi_int_avg` (MB/s - Higher is better)
- `ramspeed_multi_float_avg` (MB/s - Higher is better)

### Expected Anomaly Signatures
- **OOM Kills:** RAMSpeed allocates massive chunks of memory. If configured incorrectly (or if background apps leak memory), it will trigger the Linux OOM killer.
  - **Signature:** `dmesg_anomalies.oom_kills` contains the benchmark process name.
- **CPU Scaling:** Unlike raw bandwidth tests, RAMSpeed is heavily reliant on ALU performance (Integer/Float ops). A drop in CPU frequency (`cpu_frequency_drops`) will directly lower the MB/s score, even if memory bandwidth itself is fine.
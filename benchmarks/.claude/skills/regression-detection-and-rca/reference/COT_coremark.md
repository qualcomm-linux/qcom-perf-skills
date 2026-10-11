# COT: CoreMark & CoreMark-Pro RCA Guide

This document provides benchmark-specific guidance for interpreting regressions in CPU-bound CoreMark tests.

## Primary Metrics
- `iterations_sec` (Higher is better)
- `coremark_pro_single_core` (Higher is better)
- `coremark_pro_multi_core` (Higher is better)

## Expected Anomaly Signatures

### 1. Thermal Throttling & DVFS (Most Common)
CoreMark is heavily CPU-bound. If scores drop, immediately check `telemetry_data.thermal_throttles` and `telemetry_data.cpu_frequency_drops`.
- **Signature:** `thermal_throttles.count > 0` AND `cpu_frequency_drops.count > 0`
- **Cause:** Sustained 100% CPU utilization caused the SoC to heat up, triggering the kernel's thermal mitigation which downclocks the CPU.

### 2. Multi-Core Scaling Failures
If `coremark_pro_multi_core` drops significantly but `coremark_pro_single_core` remains stable:
- Check `dmesg_anomalies.cpu_offline_events`. The OS may have taken secondary cores offline.
- Check `ftrace_anomalies.migration_count`. High task migration ruins the L1/L2 cache locality that CoreMark relies on for high scores.

### 3. Background Noise
If frequency drops are NOT present, but context switches (`vmstat.context_switches`) are high (>50k/s):
- **Cause:** CoreMark threads are being preempted by other processes running on the OS. CoreMark expects uninterrupted CPU time; preemption directly reduces `iterations_sec`.
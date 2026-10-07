# COT: TIOBench RCA Guide

This document provides benchmark-specific guidance for interpreting regressions in storage-bound TIOBench tests.

## Primary Metrics
- `sequential_read_rate` (MB/s - Higher is better)
- `sequential_write_rate` (MB/s - Higher is better)
- `random_read_rate` (MB/s - Higher is better)
- `random_write_rate` (MB/s - Higher is better)

## Expected Anomaly Signatures

### 1. Storage Controller / SLC Cache Saturation (Most Common)
TIOBench writes large files (256MB * 8 threads = 2GB default). On UFS or NVMe drives, this can exhaust the fast SLC pseudo-cache, causing writes to fall back to slower TLC/QLC NAND.
- **Signature:** `sequential_write_rate` regresses significantly, `vmstat.io_wait_percent` is high (>40%), but thermals and CPU frequencies are normal.
- **Cause:** Hardware limitation of the storage drive. Not an OS bug. Ensure sufficient inter-iteration cooldown time is configured to allow the cache to flush.

### 2. High I/O Contention
If random reads/writes regress:
- **Signature:** `vmstat.io_wait_percent` spikes dramatically higher than baseline.
- **Cause:** Background processes (e.g., Android `system_server`, OTA updates) might be writing to the disk simultaneously, thrashing the disk head / controller queue.

### 3. Page Cache Thrashing
TIOBench can sometimes stress the Linux page cache before hitting physical disk.
- **Signature:** `vmstat.swap_activity_spike` is extremely high (>100k/s) and `vmstat.free_memory_mb` drops near zero.
- **Cause:** The system is struggling to map file-backed memory. This indicates memory pressure interfering with I/O performance.
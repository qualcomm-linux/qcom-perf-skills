# COT: Sysbench RCA Guide

This document provides benchmark-specific guidance for interpreting regressions across all `sysbench` sub-tests.

## 1. CPU Tests (`cpu_prime_single`, `cpu_prime_multi`)

**Primary Metric:** `sysbench_cpu_prime_*_test` (Events/sec - Higher is better)
**Latency Metric:** `sysbench_cpu_prime_*_test_latency_max` (ms - Lower is better)

### Expected Anomaly Signatures
- **Throughput Drop:** Almost exclusively caused by **Thermal Throttling** (`thermal_throttles`) or **CPU Frequency Drops** (`cpu_frequency_drops`). Sysbench CPU is a pure math test (prime number calculation); it has no I/O and minimal memory overhead.
- **Latency Spikes:** Caused by **Scheduler Contention**. If the system is busy with other tasks, the test threads get preempted, causing maximum latency to spike. Check `vmstat.context_switches` and `ftrace.sched_wakeup_latency_us`.

### Edge Cases
- If `cpu_prime_multi` drops but `cpu_prime_single` does not, check for **CPU Offline Events** (`dmesg.cpu_offline_events`). A disabled core directly reduces multi-thread throughput.

## 2. Memory Tests (`memory_seq_*`, `memory_random_*`)

**Primary Metric:** `sysbench_memory_*` (MB/s - Higher is better)
**Latency Metric:** `*_latency_max` (ms - Lower is better)

### Expected Anomaly Signatures
- **Throughput Drop:** Can be caused by **Thermal Throttling** (specifically `ddrss-*-thermal` zones), or L1/L2 cache thrashing. 
- **Cache Locality Loss:** If `ftrace.migration_count` is high, the OS is moving the sysbench threads between cores. Because memory benchmarks rely heavily on the CPU cache, migrating a thread flushes its cache, severely degrading performance.

## 3. File I/O Tests (`fileio_seq_*`, `fileio_random_*`, `fileio_random_mixed_*`)

**Primary Metric:** `sysbench_fileio_*` (MB/s - Higher is better)
**Latency Metric:** `*_latency_max` (ms - Lower is better)

### Expected Anomaly Signatures
- **Write Regression:** Often caused by **SLC Cache Exhaustion** on UFS/NVMe drives. If `vmstat.io_wait_percent` is high (>40%) but there are no thermal or CPU anomalies, the storage controller has run out of fast cache and is writing directly to TLC/QLC NAND.
- **Read Regression:** If `io_wait_percent` is low but performance drops, check if the CPU frequency dropped. I/O still requires CPU cycles to process interrupts.

### Specific Guidance
- Sysbench FileIO runs with `--file-test-mode=...`. Random operations (`rndrd`, `rndwr`) stress the storage controller's IOPS limits. Sequential operations (`seqrd`, `seqwr`) stress the bus bandwidth.

## 4. Threads & Mutex Tests

**Primary Metrics:** 
- `sysbench_threads_scheduler_test` (Events/sec - Higher is better)
- `sysbench_mutex_contention_test` (Events/sec - Higher is better) *(Note: this was previously marked 'lower', but the latest `benchmarks.yaml` corrected it to 'higher' for events/sec).*

### Expected Anomaly Signatures
- **Throughput Drop:** These tests explicitly measure the Linux scheduler and kernel lock contention. Drops here strongly correlate with **High Context Switching** (`vmstat.context_switch_spike > 50k/sec`) or excessive background noise.
- **Latency Spikes:** Check `ftrace.sched_wakeup_latency_us`. These tests create thousands of threads/mutexes; any delay in the kernel scheduler waking them up directly impacts the score.
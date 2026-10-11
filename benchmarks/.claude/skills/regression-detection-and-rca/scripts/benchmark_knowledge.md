# COT: Benchmark Knowledge Base

This document defines the metrics for all active benchmarks and their directionality (whether higher or lower is better). 

**CRITICAL:** This list dictates how deltas are interpreted. If a metric is "lower is better" (e.g. latency), a positive delta is a regression. Direction is always resolved authoritatively by the orchestrator (`run_rca.py::_resolve_direction()`, driven by `config/benchmarks.yaml`'s `metric_config`/`metric_direction`) and passed explicitly as `metric_directions` to both the regression-detection and RCA skills -- this table exists purely as a human-readable reference and documents the resolved values below; it is not itself consulted by any code path at runtime.

## Metric Direction Fallback Rule
If a metric is somehow missing from both `metric_directions` and the table below, the orchestrator's resolver defaults to `"higher"` (see `_resolve_direction()`) -- there is no keyword-matching fallback anywhere in the real implementation.

## 1. CPU Benchmarks (Threshold: -3%)

### CoreMark / CoreMark-Pro
- `iterations_sec` (Higher is better)
- `coremark_pro_single_core` (Higher is better)
- `coremark_pro_multi_core` (Higher is better)

### Sysbench CPU
- `sysbench_cpu_prime_single_test` (Events/sec - Higher is better)
- `sysbench_cpu_prime_multi_test` (Events/sec - Higher is better)
- `sysbench_cpu_prime_single_test_latency_max` (Lower is better)
- `sysbench_cpu_prime_multi_test_latency_max` (Lower is better)

## 2. Memory Benchmarks (Threshold: -3%)

### bw_mem
- `bw_mem_rd_plateau` (GB/s - Higher is better)
- `bw_mem_wr_plateau` (GB/s - Higher is better)
- `bw_mem_cp_plateau` (GB/s - Higher is better)
- `bw_mem_fwr_plateau` (GB/s - Higher is better)
- `bw_mem_frd_plateau` (GB/s - Higher is better)
- `bw_mem_fcp_plateau` (GB/s - Higher is better)

### lat_mem_rd
- `lat_mem_rd_plateau` (ns - Lower is better)
- `lat_mem_rd_spread` (% - Lower is better)

### RAMSpeed
- `ramspeed_multi_int_avg` (MB/s - Higher is better)
- `ramspeed_multi_float_avg` (MB/s - Higher is better)

### Sysbench Memory
- `sysbench_memory_seq_read_test` (MB/s - Higher is better)
- `sysbench_memory_seq_write_test` (MB/s - Higher is better)
- `sysbench_memory_random_read` (MB/s - Higher is better)
- `sysbench_memory_random_write` (MB/s - Higher is better)
- `*_latency_max` (Lower is better)

## 3. Storage Benchmarks (Threshold: -7%)

### TIOBench
- `sequential_read_rate` (MB/s - Higher is better)
- `sequential_write_rate` (MB/s - Higher is better)
- `random_read_rate` (MB/s - Higher is better)
- `random_write_rate` (MB/s - Higher is better)
- `mixed_read_rate` (MB/s - Higher is better)
- `mixed_write_rate` (MB/s - Higher is better)

### Sysbench FileIO
- `sysbench_fileio_seq_read_test` (MB/s - Higher is better)
- `sysbench_fileio_seq_write_test` (MB/s - Higher is better)
- `sysbench_fileio_random_read_test` (MB/s - Higher is better)
- `sysbench_fileio_random_write_test` (MB/s - Higher is better)
- `sysbench_fileio_random_mixed_test` (MB/s - Higher is better)
- `*_latency_max` (Lower is better)

## 4. OS / Scheduler Benchmarks (Threshold: -5%)

### Hackbench
- `sched_ipc_default` (Time - Lower is better)

### OSBench
*Note: All OSBench metrics are lower is better.*
- `osbench_create_threads` (us/thread - Lower is better)
- `osbench_create_processes` (us/process - Lower is better)
- `osbench_launch_programs` (us/program - Lower is better)
- `osbench_memory_alloc` (us/alloc - Lower is better)

### UnixBench
- `unixbench_single_core` (Index Score - Higher is better)
- `unixbench_multi_core` (Index Score - Higher is better)
- `unixbench_scaling` (% - Higher is better)

### Sysbench Threads/Mutex
- `sysbench_threads_scheduler_test` (Events/sec - Higher is better)
- `sysbench_mutex_contention_test` (Events/sec - Higher is better)
- `*_latency_max` (Lower is better)

## 5. GPU Benchmarks (Threshold: -5%)

### GLMark2
- `glmark2_default` (Score - Higher is better)
- `glmark2_1920x1080` (Score - Higher is better)
- `glmark2_offscreen` (Score - Higher is better)
- `glmark2_offscreen_1920x1080` (Score - Higher is better)
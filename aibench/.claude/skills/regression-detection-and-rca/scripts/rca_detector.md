# COT: RCA Detector Decision Tree

## Goal
Determine the root cause(s) of a detected performance regression by analyzing pre-parsed telemetry data (dmesg, vmstat, thermal, cpufreq, ftrace).

## Inputs Needed
- `regression_data`: The output from `regression_detector.md` (delta %, methods triggered, metrics)
- `telemetry_data`: Pre-parsed JSON containing anomalies detected during the run
- `test_name`: The name of the benchmark metric being evaluated
- `benchmark_knowledge`: Mappings from `benchmark_knowledge.md` for context

## Phase 1: Context & Direction Parsing

1. **Verify Regression Exists:**
   If `regression_data.throughput_regression` is False AND `regression_data.latency_regression` is False:
   ```
   RETURN: { "status": "No Regression", "causes": [] }
   ```

2. **Understand Metric Direction (for wording only -- not for the degradation decision):**
   The degradation decision itself is already final, per `regression_data.throughput_regression`/`latency_regression` (Step 1) -- never re-derive it from the test name. For evidence wording, infer the direction from the sign of the already-computed delta: if `throughput_regression` is True and `metrics.throughput_delta_percent` is negative, it's a higher-is-better metric that dropped; if positive, it's a lower-is-better metric that rose. Same logic for `latency_delta_percent`/`latency_regression`.
   *Ensure language in the final report reflects this (e.g., "Latency increased by 15%" vs "Throughput dropped by 10%").*

## Phase 2: Hierarchical Anomaly Evaluation

Evaluate **ALL** categories. Do NOT stop at the first match. Compound failures (e.g., Thermal Throttling causing I/O Wait) are common.

### Category 1: Thermal & Power (Priority: High)
*Check `telemetry_data.thermal_throttles` and `telemetry_data.cpu_frequency_drops`*

```python
IF thermal_throttles.count > 0 AND max_temp >= cpu_throttle_temp_c (e.g. 95C):
    ADD CAUSE: "Severe Thermal Throttling" (Confidence: 95%)
    EVIDENCE: "Device hit {max_temp}C, causing forced thermal mitigation."
    
ELIF cpu_frequency_drops.count > 0:
    IF thermal_throttles.count > 0:
        ADD CAUSE: "Thermal-Induced DVFS" (Confidence: 85%)
        EVIDENCE: "CPU frequency dropped by {drop_pct}% coinciding with elevated temperatures ({temp}C)."
    ELSE:
        ADD CAUSE: "Non-Thermal Frequency Scaling" (Confidence: 60%)
        EVIDENCE: "CPU frequency dropped by {drop_pct}% without reaching critical thermal limits. Check power governor or battery limits."
```

### Category 2: Memory & Out-Of-Memory (OOM) (Priority: High)
*Check `telemetry_data.dmesg_oom_kills` and `telemetry_data.vmstat.free_memory_mb`*

```python
IF dmesg_oom_kills.count > 0:
    ADD CAUSE: "Out Of Memory (OOM) Kills" (Confidence: 98%)
    EVIDENCE: "System ran out of memory. Kernel killed {killed_processes}."

ELIF vmstat.free_memory_mb < free_memory_low_mb (e.g. 50MB):
    ADD CAUSE: "Severe Memory Pressure" (Confidence: 80%)
    EVIDENCE: "Free memory dropped to {vmstat.free_memory_mb}MB, likely causing excessive page reclamation."
    
ELIF vmstat.swap_activity_spike > swap_activity_spike_per_sec (e.g. 100k/s):
    ADD CAUSE: "High Swap Activity" (Confidence: 75%)
    EVIDENCE: "Swap activity spiked to {spike} per second, indicating memory thrashing or heavy swap usage."
```

### Category 3: I/O Bottlenecks (Priority: Medium)
*Check `telemetry_data.vmstat.io_wait_percent`*

```python
IF vmstat.io_wait_percent > io_wait_spike_percent (e.g. 30%):
    # Cross-reference with benchmark type
    IF benchmark_category == "Storage":
        ADD CAUSE: "Storage Device Saturation" (Confidence: 85%)
        EVIDENCE: "I/O Wait hit {io_wait}%, expected during heavy storage benchmarks but indicates absolute device limit."
    ELSE:
        ADD CAUSE: "Unexpected I/O Contention" (Confidence: 80%)
        EVIDENCE: "I/O Wait hit {io_wait}% during a non-storage benchmark. Check background processes writing to disk."
```

### Category 4: Scheduler & Contention (Priority: Medium)
*Check `telemetry_data.vmstat.context_switches` and `telemetry_data.ftrace`*

```python
IF vmstat.context_switch_spike > context_switch_spike_per_sec (e.g. 50k/s):
    ADD CAUSE: "High Context Switching" (Confidence: 70%)
    EVIDENCE: "Context switches spiked to {spike}/sec. Indicates heavy thread contention or interrupts."

IF ftrace.sched_wakeup_latency_us > sched_wakeup_latency_us_high (e.g. 5000us):
    ADD CAUSE: "Scheduler Wakeup Latency Spike" (Confidence: 85%)
    EVIDENCE: "Thread wakeup latency reached {latency}us, delaying benchmark execution."

IF ftrace.migration_count > migration_count_high (e.g. 500):
    ADD CAUSE: "Excessive Task Migration" (Confidence: 75%)
    EVIDENCE: "Benchmark threads were migrated between CPU cores {count} times, destroying cache locality."
```

### Category 5: Background Process Interference
*Check `telemetry_data.top_anomalies` for process-level CPU and memory anomalies.*

```python
IF top_anomalies.process_cpu_anomalies is not EMPTY:
    # A non-benchmark process was consuming abnormally high CPU during the run
    FOR each anomaly in top_anomalies.process_cpu_anomalies[:3]:
        ADD CAUSE: "Background Process CPU Interference" (Confidence: 68%)
        EVIDENCE: "Process '{anomaly.command}' (pid {anomaly.pid}) consumed {anomaly.cpu_percent}% CPU during the benchmark run."

IF top_anomalies.zombie_processes is not EMPTY:
    ADD CAUSE: "Zombie Process Accumulation" (Confidence: 65%)
    EVIDENCE: "Zombie processes detected: {zombie_list}. May indicate resource-cleanup issues or leaked file descriptors."

IF top_anomalies.process_memory_leak is not EMPTY:
    # A process's RSS grew significantly during the run — proxy for a memory leak
    FOR each leak in top_anomalies.process_memory_leak[:3]:
        ADD CAUSE: "Suspected Memory Leak (RSS Growth)" (Confidence: 72%)
        EVIDENCE: "Process '{leak.command}' (pid {leak.pid}) RSS grew {leak.growth_percent:.1f}% ({leak.first_rss_kb}KB → {leak.last_rss_kb}KB) during the run."
```

### Category 6: Transient / Noise
*If no anomalies are found across all telemetry data:*

```python
IF telemetry_data is EMPTY:
    ADD CAUSE: "Unknown (No Telemetry)" (Confidence: 0%)
    EVIDENCE: "No telemetry data was collected during this run."

ELSE: # Telemetry exists, but no thresholds breached
    IF regression_data.methods_triggered == ["small_sample_delta"]:
        ADD CAUSE: "Likely Transient Noise" (Confidence: 60%)
        EVIDENCE: "Small sample size regression with clean telemetry. Likely system noise."
    ELSE:
        ADD CAUSE: "Ambiguous Bottleneck" (Confidence: 40%)
        EVIDENCE: "Statistically significant regression occurred, but standard telemetry shows no obvious hardware or OS bottlenecks. Requires deep ftrace/perf analysis."
```

## Phase 3: Final RCA Verdict Construction

Compile the accumulated causes into the final JSON output format expected by the orchestrator. The output is a dict keyed by metric/test name, with each value shaped exactly like `RCADetector.apply_cot_logic()`'s return value -- `cause`, `confidence`, `confidence_basis`, `evidence` (a list of objects, not strings), and `recommendation`:

```json
{
  "sysbench_cpu_prime_multi_test": {
    "cause": "DVFS / Thermal Throttling",
    "confidence": "85%",
    "confidence_basis": "Direct: kernel-logged throttle event and/or thermal-zone reading above the configured high-temp threshold, coincident with the performance regression.",
    "evidence": [
      {
        "type": "CALCULATED",
        "source": "regression_detector",
        "value": "-12.5%",
        "interpretation": "Performance regressed"
      },
      {
        "type": "OBSERVED",
        "source": "thermal_metrics",
        "value": "88.0 C",
        "interpretation": "throttle (cpu-0)"
      }
    ],
    "recommendation": "Investigate thermal design, cooling, or background workloads heating the SoC."
  }
}
```
---
name: run-hackbench
description: Runs the Hackbench benchmark to evaluate Linux scheduler and IPC (Inter-Process Communication) performance, with thermal telemetry-aware regression analysis. Reference only -- routed to by the benchmark-orchestrator skill; do not invoke directly for ad-hoc benchmark requests.
category: Performance Benchmarking
---

# Skill: Run Hackbench Benchmark
**Author:** Sarbojit Ganguly <sarbgang@qti.qualcomm.com>

Executes the Hackbench benchmark suite to evaluate scheduler and IPC (Inter-Process Communication) performance.

## Usage
```bash
python main.py --benchmark hackbench [--runs <count>] [--build-id <id>]
```

## Description
Runs various Hackbench categories (scheduler IPC default, heavy, and extreme sockets) sequentially over serial. Hackbench is an essential Linux benchmark that stresses the kernel scheduler by creating multiple pairs of threads or processes that pass data between each other.

By default, without any parameters, the harness runs all 3 configured tests (`sched_ipc_default`, `sched_ipc_heavy`, `sched_ipc_sockets_extreme`) for 3 iterations each, with a 5-minute cooldown gap between suite runs to allow system thermals to recover.

## Understanding `-r` (Runs) vs `--iterations`

- `-r`/`--runs` (default 1): how many times the entire hackbench suite runs (outer loop; each run produces its own report/output folder).
- `--iterations` (default 3): how many times each selected sched_ipc test repeats *within* a single suite run (inner loop).
- **Total executions per test = runs × iterations.**

## Thermal Telemetry & Regression Analysis
This benchmark integrates with the unified thermal telemetry system. CPU and DDR temperatures are monitored continuously during the benchmark runs and logged to a CSV file.

When regression detection is performed:
1. The framework checks if a significant throughput drop occurred (default > 5% degradation and Z-score < -2.0)
2. If a regression is detected, the Root Cause Analysis (RCA) engine correlates this with thermal telemetry
3. If CPU temperatures spiked (>85°C) or DDR temperatures spiked (>75°C) alongside the performance drop, the regression is categorized as "DVFS / Thermal Throttling" rather than a code-level regression.

## Expected Output
Hackbench produces timing information in seconds (e.g. `Time: 6.787`), which the harness automatically parses and converts to a throughput metric (messages/second) calculated as:
`total_messages = groups (-g) * fds_per_group (-f) * loops (-l)`
`throughput = total_messages / time`
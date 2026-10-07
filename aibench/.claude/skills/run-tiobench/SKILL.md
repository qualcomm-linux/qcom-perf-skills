---
name: run-tiobench
description: Runs the TIOBench (tiotest) storage and I/O performance benchmark, collecting sequential/random I/O throughput rates and latency histograms. Reference only -- routed to by the benchmark-orchestrator skill; do not invoke directly for ad-hoc benchmark requests.
category: Performance Benchmarking
---

# Skill: Run TIOBench Benchmark
**Author:** Sarbojit Ganguly <sarbgang@qti.qualcomm.com>

Executes the TIOBench (tiotest) storage and I/O performance benchmark.

## Usage
```bash
python main.py --benchmark tiobench [--runs <count>] [--build-id <id>]
```

## Description
Executes `tiotest` storage benchmarks (sequential and/or random) over serial, collecting I/O throughput rates and latency histograms while ensuring on-device page cache clearing.

`-t`/`--tests` sub-test filtering works correctly for TIOBench: passing e.g. `-t sequential` runs only the sequential test type, validated against the `tests:` list in `config/benchmarks.yaml`.

## Understanding `-r` (Runs) vs `--iterations`

- `-r`/`--runs` (default 1): how many times the entire tiobench suite runs (outer loop; each run produces its own report/output folder).
- `--iterations` (default 3): how many times each test type (`sequential`, `random`, `mixed`) repeats *within* a single suite run (inner loop).
- **Total executions per type = runs × iterations.**
- Example: "run tiobench 2 times with 3 iterations per run" → `-r 2 --iterations 3` = 2 × 3 = **6 total executions per type**.




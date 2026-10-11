---
name: run-glmark2
description: Runs the GLMark2 GPU graphics performance benchmark in various configurations (default, custom size, offscreen, offscreen+size). Reference only -- routed to by the benchmark-orchestrator skill; do not invoke directly for ad-hoc benchmark requests.
category: Performance Benchmarking
---

# Skill: Run GLMark2 Benchmark
**Author:** Sarbojit Ganguly <sarbgang@qti.qualcomm.com>

Executes the GLMark2 graphics performance benchmark in various configurations.

## Usage
`glmark2_default`, `glmark2_1920x1080`, `glmark2_offscreen`, and `glmark2_offscreen_1920x1080` are **sub-tests** selected via `-t`, not standalone benchmark names — the registry only recognizes `glmark2` as a valid `-b` value.
```bash
python main.py -b glmark2 -t glmark2_default
python main.py -b glmark2 -t glmark2_1920x1080
python main.py -b glmark2 -t glmark2_offscreen
python main.py -b glmark2 -t glmark2_offscreen_1920x1080
```

## Description
Executes GLMark2 benchmarks to evaluate GPU performance. The benchmark can be executed in different modes such as default, with specific rendering size, offscreen, and combined mode.

## Understanding `-r` (Runs) vs `--iterations`

- `-r`/`--runs` (default 1): how many times the entire glmark2 suite runs (outer loop; each run produces its own report/output folder).
- `--iterations`: **⚠️ Confirmed Bug — currently non-functional for GLMark2.** `src/benchmark/glmark2.py` hardcodes 1 iteration per flavor per suite run and never reads the `--iterations` CLI value. As a result, only `-r` has any effect on how many times a GLMark2 flavor executes; `--iterations` is silently ignored.

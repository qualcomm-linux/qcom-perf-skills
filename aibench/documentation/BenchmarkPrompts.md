# Benchmark Prompt Reference Guide

**Author:** Sarbojit Ganguly <sarbgang@qti.qualcomm.com>

This document provides an accurate, effective list of natural-language prompts for invoking each benchmark supported by the `aibench/` harness, derived directly from:
- `aibench/.claude/skills/benchmark-orchestrator/SKILL.md` (root orchestrator) and all `run-<benchmark>/SKILL.md` leaf skills
- `aibench/main.py` (CLI argument parsing/handling)
- `aibench/config/benchmarks.yaml` (valid test names, defaults, active benchmarks)
- `aibench/src/benchmark/*.py` (per-benchmark execution logic)

Each benchmark's prompts are listed **starting with the canonical (simplest) form**, in **increasing order of verbosity/complexity**. **SSH is treated as the default connection** per project convention; explicit Serial/ADB variations are also shown where relevant.

**Output format:** Every run produces an **HTML report** (`report.html` per individual run, plus a unified `output/reports/index.html` dashboard aggregating all benchmarks and builds — rendered via Jinja2 in `src/reporting/individual.py` and `main.py`'s `render_dashboard()`).

**Known harness bugs affecting these prompts:**
- See the callout in [Section 5 (GLMark2)](#5-glmark2--b-glmark2) — `--iterations` is currently non-functional for GLMark2, which hardcodes 1 iteration per flavor per suite run in `src/benchmark/glmark2.py`.

## ⚠️ Understanding `-r` (Runs) vs `--iterations`

These two flags control **two independent, nested loops** and are frequently confused. Both are fully implemented and working correctly in the harness today:

- **`-r` / `--runs`** — the **outer loop**, implemented in `main.py`. Controls how many times the **entire benchmark suite** (one full `execute_lifecycle()` call) is executed. Each suite run gets its own timestamped `run_<...>` output directory, `results.json`, and HTML report; all suite runs for a build are then aggregated into `build_analysis.json`. Default: **1** (run the suite once).
- **`--iterations`** — the **inner loop**, implemented inside each benchmark engine (`src/benchmark/<name>.py`). Controls how many times **each individual sub-test** repeats *within a single suite run*. Default varies per benchmark (see `config/benchmarks.yaml`'s `iterations:` key for that benchmark — typically 3).

**The two loops multiply:** `Total sub-test executions = runs × iterations`

### Worked example (matches the exact scenario "run sysbench 3 times and its fileio test 4 times")
```
python main.py -b sysbench -t sysbench_fileio_random_mixed_test -r 3 --iterations 4 --ssh-connection
```
- The **sysbench suite runs 3 times** (`-r 3` → outer loop in `main.py`, 3 separate `run_<...>` folders/reports).
- **Within each of those 3 suite runs**, the `sysbench_fileio_random_mixed_test` sub-test runs **4 times** (`--iterations 4` → inner loop inside `sysbench.py`).
- **Total fileio executions = 3 × 4 = 12.**

This exact multiplicative relationship applies identically to **every** benchmark below — only the sub-test names/defaults change.

---

## ⚠️ Important Naming Correction: GLMark2

The 4 GLMark2 "flavors" (`glmark2_default`, `glmark2_1920x1080`, `glmark2_offscreen`, `glmark2_offscreen_1920x1080`) are **NOT separate `-b` (benchmark) values** — the benchmark registry (`src/benchmark/registry.py`) only recognizes `glmark2` as a valid `-b` name. The four flavors are **sub-tests selected via `-t`/`--tests`**, exactly like Sysbench's or TIOBench's sub-tests. Running `python main.py -b glmark2_default` will fail with `"Benchmark 'glmark2_default' is not supported"`.

**Correct pattern:** `python main.py -b glmark2 -t glmark2_default ...`

---

## 1. CoreMark (`-b coremark`)

Valid test: `coremark_default` (only one; usually omitted).

| # | Prompt | Resulting Command |
|---|---|---|
| 1 (canonical) | "run coremark over ssh" | `python main.py -b coremark --ssh-connection` |
| 2 | "run coremark with default parameters over ssh" | `python main.py -b coremark --ssh-connection` |
| 3 | "run coremark 5 times over ssh" | `python main.py -b coremark -r 5 --ssh-connection` |
| 4 | "run coremark over serial" | `python main.py -b coremark` |
| 5 | "run coremark 3 times with 5 iterations over ssh" | `python main.py -b coremark -r 3 --iterations 5 --ssh-connection` |
| 6 | "run coremark 4 times bypassing the cooldown gap over ssh" | `python main.py -b coremark -r 4 --bypass-gap --ssh-connection` |
| 7 | "run coremark 2 times with 4 iterations per run over ssh" (2 × 4 = 8 total executions) | `python main.py -b coremark -r 2 --iterations 4 --ssh-connection` |

---

## 2. Sysbench (`-b sysbench`)

Valid tests: `sysbench_cpu_prime_single_test`, `sysbench_cpu_prime_multi_test`, `sysbench_memory_seq_read_test`, `sysbench_memory_seq_write_test`, `sysbench_memory_random_read`, `sysbench_memory_random_write`, `sysbench_threads_scheduler_test`, `sysbench_mutex_contention_test`, `sysbench_fileio_seq_read_test`, `sysbench_fileio_seq_write_test`, `sysbench_fileio_random_read_test`, `sysbench_fileio_random_write_test`, `sysbench_fileio_random_mixed_test`.

| # | Prompt | Resulting Command |
|---|---|---|
| 1 (canonical) | "run sysbench over ssh" | `python main.py -b sysbench --ssh-connection` |
| 2 | "run sysbench with default parameters over ssh" | `python main.py -b sysbench --ssh-connection` |
| 3 | "run sysbench 3 times over ssh" | `python main.py -b sysbench -r 3 --ssh-connection` |
| 4 | "run only the cpu tests of sysbench over ssh" | `python main.py -b sysbench -t sysbench_cpu_prime_single_test sysbench_cpu_prime_multi_test --ssh-connection` |
| 5 | "run only the memory tests of sysbench over ssh" | `python main.py -b sysbench -t sysbench_memory_seq_read_test sysbench_memory_seq_write_test sysbench_memory_random_read sysbench_memory_random_write --ssh-connection` |
| 6 | "run only the fileio tests of sysbench over ssh" | `python main.py -b sysbench -t sysbench_fileio_seq_read_test sysbench_fileio_seq_write_test sysbench_fileio_random_read_test sysbench_fileio_random_write_test sysbench_fileio_random_mixed_test --ssh-connection` |
| 7 | "run sysbench cpu and memory tests with 5 iterations over ssh" | `python main.py -b sysbench -t sysbench_cpu_prime_single_test sysbench_cpu_prime_multi_test sysbench_memory_random_read --iterations 5 --ssh-connection` |
| 8 | "dynamically override sysbench cpu multi test with 10 second runtime and 4 threads over ssh" | `python main.py -b sysbench -t sysbench_cpu_prime_multi_test --time=10 --threads=4 --ssh-connection` |
| 9 | "run sysbench 3 times and its fileio test 4 times over ssh" (3 × 4 = 12 total fileio executions) | `python main.py -b sysbench -t sysbench_fileio_random_mixed_test -r 3 --iterations 4 --ssh-connection` |

---

## 3. TIOBench (`-b tiobench`)

Valid tests (test types, listed in `tests:` and `test_params:` in `config/benchmarks.yaml`): `sequential`, `random`, `mixed`. `-t`/`--tests` filtering is fully functional for TIOBench — passing a subset via `-t` runs only those test types.

| # | Prompt | Resulting Command |
|---|---|---|
| 1 (canonical) | "run tiobench over ssh" | `python main.py -b tiobench --ssh-connection` |
| 2 | "run tiobench with default parameters over ssh" | `python main.py -b tiobench --ssh-connection` |
| 3 | "run tiobench 5 times over ssh" | `python main.py -b tiobench -r 5 --ssh-connection` |
| 4 | "run only the sequential test of tiobench over ssh" | `python main.py -b tiobench -t sequential --ssh-connection` |
| 5 | "run sequential and random tiobench tests for 3 runs over ssh" | `python main.py -b tiobench -t sequential random -r 3 --ssh-connection` |
| 6 | "run tiobench with 5 iterations over ssh" | `python main.py -b tiobench --iterations 5 --ssh-connection` |
| 7 | "run tiobench 2 times with 3 iterations per run over ssh" (2 × 3 = 6 total executions per type) | `python main.py -b tiobench -r 2 --iterations 3 --ssh-connection` |

---

## 4. Hackbench (`-b hackbench`)

Valid tests: `sched_ipc_default`, `sched_ipc_heavy`, `sched_ipc_sockets_extreme`. Metric direction: **lower is better** (time in seconds; converted to throughput internally).

| # | Prompt | Resulting Command |
|---|---|---|
| 1 (canonical) | "run hackbench over ssh" | `python main.py -b hackbench --ssh-connection` |
| 2 | "run hackbench with default parameters over ssh" | `python main.py -b hackbench --ssh-connection` |
| 3 | "run hackbench 3 times over ssh" | `python main.py -b hackbench -r 3 --ssh-connection` |
| 4 | "run only the sched_ipc_heavy test of hackbench over ssh" | `python main.py -b hackbench -t sched_ipc_heavy --ssh-connection` |
| 5 | "run sched_ipc_default and sched_ipc_sockets_extreme hackbench tests over ssh" | `python main.py -b hackbench -t sched_ipc_default sched_ipc_sockets_extreme --ssh-connection` |
| 6 | "run hackbench 3 times bypassing the cooldown gap over ssh" | `python main.py -b hackbench -r 3 --bypass-gap --ssh-connection` |
| 7 | "run hackbench 2 times with 5 iterations per run over ssh" (2 × 5 = 10 total executions) | `python main.py -b hackbench -r 2 --iterations 5 --ssh-connection` |

---

## 5. GLMark2 (`-b glmark2`)

Valid tests (flavors): `glmark2_default`, `glmark2_1920x1080`, `glmark2_offscreen`, `glmark2_offscreen_1920x1080`. Metric direction: **higher is better** (score).

> ⚠️ **Confirmed Bug — `--iterations` is non-functional for GLMark2.**
> `src/benchmark/glmark2.py` hardcodes `self.iterations = 1` in `__init__` and never reads `self.config.get("iterations", ...)`. As a result, **any** value passed via `--iterations` is silently ignored — each requested flavor always runs exactly **once** per suite run, regardless of `--iterations`. Only `-r`/`--runs` (the outer suite-run loop in `main.py`) has any effect on repetition count for GLMark2 today.

| # | Prompt | Resulting Command | Actual Behavior (current harness) |
|---|---|---|---|
| 1 (canonical) | "run glmark2 over ssh" | `python main.py -b glmark2 --ssh-connection` | Runs all 4 flavors, 1 execution each (as intended) |
| 2 | "run glmark2 with default parameters over ssh" | `python main.py -b glmark2 --ssh-connection` | Same as above |
| 3 | "run only the default glmark2 test over ssh" | `python main.py -b glmark2 -t glmark2_default --ssh-connection` | Runs `glmark2_default` once (as intended) |
| 4 | "run glmark2 at 1920x1080 over ssh" | `python main.py -b glmark2 -t glmark2_1920x1080 --ssh-connection` | As intended |
| 5 | "run glmark2 in offscreen mode over ssh" | `python main.py -b glmark2 -t glmark2_offscreen --ssh-connection` | As intended |
| 6 | "run glmark2 offscreen at 1920x1080 over ssh" | `python main.py -b glmark2 -t glmark2_offscreen_1920x1080 --ssh-connection` | As intended |
| 7 | "run the default and offscreen glmark2 tests over ssh" | `python main.py -b glmark2 -t glmark2_default glmark2_offscreen --ssh-connection` | As intended |
| 8 | "run glmark2 2 times over ssh" | `python main.py -b glmark2 -r 2 --ssh-connection` | Runs all 4 flavors × 2 suite runs (as intended; `-r` is unaffected by this bug) |
| 9 | "run glmark2 default test 2 times with 3 iterations per run over ssh" | `python main.py -b glmark2 -t glmark2_default -r 2 --iterations 3 --ssh-connection` | ⚠️ **Bug**: still only 2 total executions (2 suite runs × 1 iteration each) — `--iterations 3` is silently ignored |

---

## 6. CoreMark-Pro (`-b coremark_pro`)

Valid tests: `coremark_pro_single`, `coremark_pro_multi`. Runs 9 microbenchmarks (`core`, `cjpeg-rose7-preset`, `linear_alg-mid-100x100-sp`, `loops-all-mid-10k-sp`, `nnet_test`, `parser-125k`, `radix2-big-64k`, `sha-test`, `zip-test`) per mode.

| # | Prompt | Resulting Command |
|---|---|---|
| 1 (canonical) | "run coremark pro over ssh" | `python main.py -b coremark_pro --ssh-connection` |
| 2 | "run coremark pro with default parameters over ssh" | `python main.py -b coremark_pro --ssh-connection` |
| 3 | "run coremark pro 3 times over ssh" | `python main.py -b coremark_pro -r 3 --ssh-connection` |
| 4 | "run only the single-core coremark pro test over ssh" | `python main.py -b coremark_pro -t coremark_pro_single --ssh-connection` |
| 5 | "run only the multi-core coremark pro test over ssh" | `python main.py -b coremark_pro -t coremark_pro_multi --ssh-connection` |
| 6 | "run coremark pro single and multi core with 5 iterations over ssh" | `python main.py -b coremark_pro -t coremark_pro_single coremark_pro_multi --iterations 5 --ssh-connection` |
| 7 | "run coremark pro 2 times with 4 iterations per run over ssh" (2 × 4 = 8 total executions per microbenchmark) | `python main.py -b coremark_pro -r 2 --iterations 4 --ssh-connection` |

---

## 7. OSBench (`-b osbench`)

Valid test: `osbench_default` (measures `launch_programs`, `create_files`, `create_processes`, `create_threads`). Metric direction: **lower is better** (µs/operation).

| # | Prompt | Resulting Command |
|---|---|---|
| 1 (canonical) | "run osbench over ssh" | `python main.py -b osbench --ssh-connection` |
| 2 | "run osbench with default parameters over ssh" | `python main.py -b osbench --ssh-connection` |
| 3 | "run osbench 3 times over ssh" | `python main.py -b osbench -r 3 --ssh-connection` |
| 4 | "run osbench with 5 iterations over ssh" | `python main.py -b osbench --iterations 5 --ssh-connection` |
| 5 | "run osbench 2 times with 4 iterations per run over ssh" (2 × 4 = 8 total executions) | `python main.py -b osbench -r 2 --iterations 4 --ssh-connection` |

---

## 8. RAMSpeed (`-b ramspeed`)

Valid tests: `ramspeed_single`, `ramspeed_multi`. Sweeps 6 benchmark IDs (int/float write/read/average) per run.

| # | Prompt | Resulting Command |
|---|---|---|
| 1 (canonical) | "run ramspeed over ssh" | `python main.py -b ramspeed --ssh-connection` |
| 2 | "run ramspeed with default parameters over ssh" | `python main.py -b ramspeed --ssh-connection` |
| 3 | "run ramspeed 3 times over ssh" | `python main.py -b ramspeed -r 3 --ssh-connection` |
| 4 | "run only the single-threaded ramspeed test over ssh" | `python main.py -b ramspeed -t ramspeed_single --ssh-connection` |
| 5 | "run only the multi-threaded ramspeed test over ssh" | `python main.py -b ramspeed -t ramspeed_multi --ssh-connection` |
| 6 | "run ramspeed with 5 iterations over ssh" | `python main.py -b ramspeed --iterations 5 --ssh-connection` |
| 7 | "run ramspeed 2 times with 4 iterations per run over ssh" (2 × 4 = 8 total executions per benchmark ID) | `python main.py -b ramspeed -r 2 --iterations 4 --ssh-connection` |

---

## 9. UnixBench (`-b unixbench`)

No sub-tests (`-t` not applicable) — always runs single-core (`-c 1`) then multi-core (`-c $(nproc)`) per iteration, plus derives a scaling-efficiency metric.

| # | Prompt | Resulting Command |
|---|---|---|
| 1 (canonical) | "run unixbench over ssh" | `python main.py -b unixbench --ssh-connection` |
| 2 | "run unixbench with default parameters over ssh" | `python main.py -b unixbench --ssh-connection` |
| 3 | "run unixbench 2 times over ssh" | `python main.py -b unixbench -r 2 --ssh-connection` |
| 4 | "run unixbench bypassing the cooldown gap over ssh" | `python main.py -b unixbench --bypass-gap --ssh-connection` |
| 5 | "run unixbench 2 times with 2 iterations per run over ssh" (2 × 2 = 4 total single+multi-core passes) | `python main.py -b unixbench -r 2 --iterations 2 --ssh-connection` |

---

## 10. bw_mem (`-b bw_mem`)

Valid tests: `bw_mem_rd`, `bw_mem_wr`, `bw_mem_cp`, `bw_mem_rdwr`, `bw_mem_frd`, `bw_mem_fwr`. Sweeps worker counts 1→`$(nproc)` per operation to find bandwidth plateau. Metric direction: **higher is better**.

| # | Prompt | Resulting Command |
|---|---|---|
| 1 (canonical) | "run bw_mem over ssh" | `python main.py -b bw_mem --ssh-connection` |
| 2 | "run bw_mem with default parameters over ssh" | `python main.py -b bw_mem --ssh-connection` |
| 3 | "run only the read bandwidth test of bw_mem over ssh" | `python main.py -b bw_mem -t bw_mem_rd --ssh-connection` |
| 4 | "run the read, write, and copy bw_mem tests over ssh" | `python main.py -b bw_mem -t bw_mem_rd bw_mem_wr bw_mem_cp --ssh-connection` |
| 5 | "run bw_mem 2 times over ssh" | `python main.py -b bw_mem -r 2 --ssh-connection` |
| 6 | "run bw_mem read test 2 times with 2 iterations per run over ssh" (2 × 2 = 4 total full worker-sweeps) | `python main.py -b bw_mem -t bw_mem_rd -r 2 --iterations 2 --ssh-connection` |

---

## 11. lat_mem_rd (`-b lat_mem_rd`)

Valid test: `lat_mem_rd_default`. Sweeps working-set sizes (64M→256M) to find latency plateau. Metric direction: **lower is better** (nanoseconds).

| # | Prompt | Resulting Command |
|---|---|---|
| 1 (canonical) | "run lat_mem_rd over ssh" | `python main.py -b lat_mem_rd --ssh-connection` |
| 2 | "run lat_mem_rd with default parameters over ssh" | `python main.py -b lat_mem_rd --ssh-connection` |
| 3 | "run lat_mem_rd 3 times over ssh" | `python main.py -b lat_mem_rd -r 3 --ssh-connection` |
| 4 | "run lat_mem_rd with 5 iterations over ssh" | `python main.py -b lat_mem_rd --iterations 5 --ssh-connection` |
| 5 | "run lat_mem_rd 2 times with 4 iterations per run over ssh" (2 × 4 = 8 total workload-size sweeps) | `python main.py -b lat_mem_rd -r 2 --iterations 4 --ssh-connection` |

---

## 12. All Benchmarks (No `-b`, or Comma-Separated List)

Active benchmarks (from `config/benchmarks.yaml`): `coremark, sysbench, tiobench, hackbench, glmark2, coremark_pro, osbench, ramspeed, unixbench, bw_mem, lat_mem_rd, geekbench` (12 total).

| # | Prompt | Resulting Command |
|---|---|---|
| 1 (canonical) | "run all benchmarks over ssh" | `python main.py --ssh-connection` |
| 2 | "run all benchmarks with default parameters over ssh" | `python main.py --ssh-connection` |
| 3 | "run all benchmarks over serial" | `python main.py` |
| 4 | "run all benchmarks 2 times over ssh" | `python main.py -r 2 --ssh-connection` |
| 5 | "run all benchmarks except unixbench and hackbench over ssh" | `python main.py --skip unixbench,hackbench --ssh-connection` |
| 6 | "run sysbench, coremark, and tiobench over ssh" | `python main.py -b sysbench,coremark,tiobench --ssh-connection` |
| 7 | "run all benchmarks over ssh bypassing the cooldown gap" | `python main.py --bypass-gap --ssh-connection` |
| 8 | "run all benchmarks except glmark2 and unixbench, 2 times, over ssh" | `python main.py --skip glmark2,unixbench -r 2 --ssh-connection` |
| 9 | "run all benchmarks 2 times with 4 iterations per run over ssh" (applies uniformly: each benchmark's suite runs 2 times, each sub-test 4 iterations per run) | `python main.py -r 2 --iterations 4 --ssh-connection` |

---

## 13. Geekbench (`-b geekbench`)

Valid test: `geekbench_cpu` (only one; usually omitted). Measures Single-Core and Multi-Core CPU performance (plus Integer/Floating Point component scores). Metric direction: **higher is better**.

| # | Prompt | Resulting Command |
|---|---|---|
| 1 (canonical) | "run geekbench over ssh" | `python main.py -b geekbench --ssh-connection` |
| 2 | "run geekbench with default parameters over ssh" | `python main.py -b geekbench --ssh-connection` |
| 3 | "run geekbench 3 times over ssh" | `python main.py -b geekbench -r 3 --ssh-connection` |
| 4 | "run geekbench over serial" | `python main.py -b geekbench` |
| 5 | "run geekbench with 5 iterations over ssh" | `python main.py -b geekbench --iterations 5 --ssh-connection` |
| 6 | "run geekbench 2 times with 4 iterations per run over ssh" (2 × 4 = 8 total executions) | `python main.py -b geekbench -r 2 --iterations 4 --ssh-connection` |

---

## Connection Type Reference

| Keyword in Prompt | Flag Added | Notes |
|---|---|---|
| *(none — SSH is default)* / "over ssh" / "via ssh" | `--ssh-connection` | Default assumption per project convention |
| "over serial" / "via adb" / "default connection" | `--default-connection` *(or simply omit `--ssh-connection`)* | Serial/ADB is `main.py`'s built-in default when no connection flag given |

**Note:** `--default-connection` and `--ssh-connection` are mutually exclusive — `main.py` will error (`parser.error`) if both are passed simultaneously.
---
name: run-all-benchmarks
description: Orchestrates the full active benchmark suite (all benchmarks in benchmarks.yaml, or a user-specified subset) sequentially through main.py, then presents a unified summary and points to the generated dashboard. Reference only -- routed to by the benchmark-orchestrator skill; do not invoke directly for ad-hoc benchmark requests.
category: Performance Benchmarking
---

# Run All Benchmarks (Full Suite Orchestration)
**Author:** Sarbojit Ganguly <sarbgang@qti.qualcomm.com>

This meta-skill triggers the unified `main.py` harness without a `--benchmark` filter (or with a comma-separated list), letting the harness sequentially execute every `active_benchmarks` entry from `config/benchmarks.yaml`, enforcing the 5-minute inter-benchmark cooldown, and finally rendering the aggregated `output/reports/index.html` summary dashboard.

Use this skill when the user wants an overall device performance sweep rather than a single targeted benchmark (e.g. "run the full benchmark suite", "profile this build across all benchmarks", "compare this build against the previous one on everything").

## Prerequisites
- The environment must be configured with `benchmarks.yaml` pointing to a valid target.
- AI Agent must execute this from the `aibench/` directory.
- A full run of all 12 active benchmarks (coremark, sysbench, tiobench, hackbench, glmark2, coremark_pro, osbench, ramspeed, unixbench, bw_mem, lat_mem_rd, geekbench) can take several hours depending on target hardware and `--runs`/`--iterations` settings. Always confirm scope and set time expectations with the user before starting.

## Parameters

- `benchmarks` (list, optional): Comma-separated subset of benchmarks to run (e.g. `sysbench,hackbench,coremark`). If omitted, all `active_benchmarks` from `benchmarks.yaml` are run.
- `skip` (list, optional): Comma-separated list of benchmarks to explicitly exclude from the active set (e.g. `unixbench,hackbench`).
- `runs` (int, default=1): Number of suite runs applied uniformly to every selected benchmark.
- `iterations` (int, optional): Overrides per-sub-test iteration count uniformly across all selected benchmarks.
- `ssh_connection` (boolean, default=false): Whether to use SSH instead of serial/ADB for execution.
- `bypass_gap` (boolean, default=false): Whether to bypass the 5-minute cooldown gap between suite runs/benchmarks.
- `build_id` (string, optional): Identifier for the build being tested. Auto-detected via ADB if omitted.

### Understanding `-r` (Runs) vs `--iterations`

- `-r`/`--runs`: outer loop — how many times **each selected benchmark's entire suite** runs.
- `--iterations`: inner loop — how many times each benchmark's sub-tests repeat *within* a single suite run. Applies uniformly across all selected benchmarks (their individual defaults apply if omitted).

## Usage Instructions

1. Determine from the user's request whether they want the full active suite, an explicit subset (`--benchmark`), or the full suite minus some exclusions (`--skip`).
2. Execute `main.py` with the appropriate combination of `-b`/`--skip`/`-r`/`--iterations`/`--ssh-connection`/`--bypass-gap`.
3. Because this can be long-running, stream/monitor output if the CLI supports it, and inform the user of progress at each `Beginning Benchmark Execution: <NAME>` boundary if visible.
4. Once complete, locate `output/reports/index.html` (the rendered summary dashboard) and report its path to the user.
5. Additionally, for each benchmark that ran, read its latest `build_analysis.json` (or `results.json` for single-run cases) and produce a concise per-benchmark summary table, similar to combining the outputs of the individual `run-<benchmark>` skills.
6. Report any `skipped_benchmarks` (invalid names or explicitly skipped) shown in the dashboard/log output.

### Implementation Example (Python)

```python
import os
import glob
import json
import subprocess

# Parameters derived from AI Agent context
benchmarks = None       # e.g. "sysbench,hackbench,coremark" or None for all active
skip = None             # e.g. "unixbench,hackbench" or None
runs = 1
use_ssh = True
bypass_gap = False

cmd = ["python", "main.py", "-r", str(runs)]
if benchmarks:
    cmd += ["-b", benchmarks]
if skip:
    cmd += ["--skip", skip]
if use_ssh:
    cmd.append("--ssh-connection")
if bypass_gap:
    cmd.append("--bypass-gap")

print(f"Executing: {' '.join(cmd)}")
result = subprocess.run(cmd, capture_output=True, text=True, cwd="aibench")

if result.returncode != 0:
    print(f"Harness Execution Failed!\n{result.stderr}")
else:
    output_root = os.path.join("aibench", "output")
    dashboard_path = os.path.join(output_root, "reports", "index.html")

    print("=====================================")
    print("FULL BENCHMARK SUITE COMPLETE")
    print("=====================================")
    print(f"Unified Dashboard: {dashboard_path}\n")

    # Summarize each benchmark that has output
    for bench_dir in sorted(glob.glob(os.path.join(output_root, "*"))):
        bench_name = os.path.basename(bench_dir)
        if bench_name == "reports" or not os.path.isdir(bench_dir):
            continue

        build_dirs = sorted(glob.glob(os.path.join(bench_dir, "build_*")), key=os.path.getmtime)
        if not build_dirs:
            continue

        latest_build = build_dirs[-1]
        analysis_file = os.path.join(latest_build, "build_analysis.json")

        print(f"--- {bench_name.upper()} ---")
        if os.path.exists(analysis_file):
            with open(analysis_file, "r") as f:
                data = json.load(f)
            stats = data.get("statistics", {})
            for metric, metric_stats in sorted(stats.items()):
                print(f"  {metric}: {metric_stats.get('mean', 'N/A')}")
        else:
            # Fall back to the latest run's results.json for single-run benchmarks
            run_dirs = sorted(glob.glob(os.path.join(latest_build, "run_*")))
            if run_dirs:
                res_file = os.path.join(run_dirs[-1], "results.json")
                if os.path.exists(res_file):
                    print(f"  (single run) see {res_file}")
        print()
```

## Expected Output Format

```
I have executed the full benchmark suite (12 benchmarks) on build <build_id>.

**Unified Dashboard**: aibench/output/reports/index.html

**Per-Benchmark Highlights**:
- coremark: 25634.45 Iterations/Sec (higher is better)
- sysbench_cpu_prime_single_test: 1450.2 events/sec (higher is better)
- tiobench sequential_write_rate: 210.5 MB/s (higher is better)
- hackbench sched_ipc_default: 4800 msgs/sec (lower time is better)
- glmark2_default: 950 score (higher is better)
- coremark_pro (single/multi): see detailed breakdown
- osbench: 74.68 us/program (lower is better)
- ramspeed (single/multi): see detailed breakdown
- unixbench: single=1245.3, multi=8414.3, scaling=84.5% (higher is better)
- bw_mem: plateau bandwidths per operation (higher is better)
- lat_mem_rd: 141.72 ns plateau latency (lower is better)
- geekbench: single-core=1125, multi-core=5448 (higher is better)

**Skipped Benchmarks**: none
```

## Error Handling
- If an individual benchmark fails mid-suite (e.g. device disconnect, binary missing), the harness logs the error and `continue`s to the next benchmark rather than aborting the whole suite — reflect this in the summary (mark that benchmark as "FAILED" rather than omitting it silently).
- If the gap-validation check (`validate_and_enforce_gap`) rejects the run because a benchmark was run too recently, the harness aborts with exit code 2 before starting anything — surface this clearly and suggest `--bypass-gap` only if the user explicitly accepts the risk of thermal-skewed results.
- Any benchmark name passed via `-b`/`--skip` that doesn't exist in `benchmarks.yaml` is recorded in `skipped_benchmarks` with reason "Not found in configuration" and shown in the dashboard — call this out to the user rather than assuming all requested benchmarks ran.
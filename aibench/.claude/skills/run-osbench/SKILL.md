---
name: run-osbench
description: Runs the OSBench microbenchmark suite to measure OS-level operation latency for launching programs, creating files, creating processes, and creating threads. Reference only -- routed to by the benchmark-orchestrator skill; do not invoke directly for ad-hoc benchmark requests.
category: Performance Benchmarking
---

# Run OSBench Benchmark
**Author:** Sarbojit Ganguly <sarbgang@qti.qualcomm.com>

This skill executes OSBench, which times four OS-level microbenchmarks: `launch_programs`, `create_files` (writes into `/root/` by default), `create_processes`, and `create_threads`. Lower times (microseconds per operation) are better for this benchmark.

## Prerequisites
- The environment must be configured with `benchmarks.yaml` pointing to a valid target.
- AI Agent must execute this from the `aibench/` directory.
- The target must have the OSBench binaries (`launch_programs`, `create_files`, `create_processes`, `create_threads`) present under `/usr/bin/`.

## Parameters

- `runs` (int, default=1): The number of sequential suite runs to perform.
- `iterations` (int, default=3): The number of internal repetitions per microbenchmark per suite run.
- `ssh_connection` (boolean, default=false): Whether to use SSH instead of serial/ADB for execution.
- `bypass_gap` (boolean, default=false): Whether to bypass the 5-minute cooldown gap between suite runs.
- `build_id` (string, optional): Identifier for the build being tested. Auto-detected via ADB if omitted.

### Understanding `-r` (Runs) vs `--iterations`

- `-r`/`--runs`: outer loop — how many times the entire osbench suite runs.
- `--iterations`: inner loop — how many times each microbenchmark repeats *within* a single suite run.

## Usage Instructions

1. Parse the user's intent to determine how many times they want to run osbench.
2. Execute the `main.py` harness with the `-b osbench` and `-r <runs>` arguments.
3. Once completed, parse the `build_analysis.json` and `results.json` files generated in the `output/osbench/` folder to present the aggregated microsecond-per-operation timings.

**IMPORTANT**: Because `metric_direction: lower` for this benchmark, remind the user that a *lower* value indicates *better* performance when presenting results.

### Implementation Example (Python)

```python
import os
import glob
import json
import subprocess

runs = 1  # Example
use_ssh = True
bypass_gap = False

cmd = ["python", "main.py", "-b", "osbench", "-r", str(runs)]
if use_ssh:
    cmd.append("--ssh-connection")
if bypass_gap:
    cmd.append("--bypass-gap")

print(f"Executing: {' '.join(cmd)}")
result = subprocess.run(cmd, capture_output=True, text=True, cwd="aibench")

if result.returncode != 0:
    print(f"Harness Execution Failed!\n{result.stderr}")
else:
    out_dir = os.path.join("aibench", "output", "osbench")
    build_dirs = sorted(glob.glob(os.path.join(out_dir, "build_*")), key=os.path.getmtime)

    if not build_dirs:
        print("Error: No build directories found for osbench.")
    else:
        latest_build = build_dirs[-1]
        analysis_file = os.path.join(latest_build, "build_analysis.json")

        if os.path.exists(analysis_file):
            with open(analysis_file, "r") as f:
                data = json.load(f)

            stats = data.get("statistics", {})
            print(f"=====================================")
            print(f"OSBENCH SUMMARY (lower is better)")
            print(f"=====================================")
            for test_key, test_stats in sorted(stats.items()):
                mean_val = test_stats.get("mean", "N/A")
                print(f"  {test_key}: {mean_val} us/operation")
            print(f"=====================================")
        else:
            print("Error: build_analysis.json not generated.")
```

## Expected Output Format

```
I have executed the OSBench microbenchmark suite.

**Results (microseconds/operation, LOWER is better)**:
- osbench_launch_programs: 74.68 us/program
- osbench_create_files: 12.34 us/file
- osbench_create_processes: 145.21 us/process
- osbench_create_threads: 28.90 us/thread
```

## Error Handling
- If any OSBench binary is not found under `/usr/bin/`, the harness logs a warning during setup but continues with remaining benchmarks.
- If output parsing fails for a given microbenchmark/iteration (missing `us /` pattern in output), `time_us` defaults to `0.0` and is logged as a warning.
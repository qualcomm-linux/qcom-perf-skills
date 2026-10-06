---
name: run-lat-mem-rd
description: Runs the lat_mem_rd (lmbench) memory-latency benchmark, sweeping working-set sizes to detect the memory-bound latency plateau and its iteration-to-iteration repeatability. Reference only -- routed to by the benchmark-orchestrator skill; do not invoke directly for ad-hoc benchmark requests.
category: Performance Benchmarking
---

# Run lat_mem_rd Benchmark
**Author:** Sarbojit Ganguly <sarbgang@qti.qualcomm.com>

This skill executes lmbench's `lat_mem_rd` tool across a sweep of working-set sizes (default: 64M, 96M, 128M, 192M, 256M) at a fixed stride (default: 64 bytes), per command: `lat_mem_rd -t -N 7 <size> <stride>`. For each iteration, it detects the latency "plateau" (the memory-bound region at large working sets) and reports the plateau latency in nanoseconds plus the spread across iterations.

## Prerequisites
- The environment must be configured with `benchmarks.yaml` pointing to a valid target.
- AI Agent must execute this from the `aibench/` directory.
- The target must have `/usr/bin/lat_mem_rd` present.
- Each iteration runs 5 workload-size commands with an inter-command delay (default 5s), so a single iteration can take a few minutes.

## Parameters

- `runs` (int, default=1): The number of sequential suite runs to perform.
- `iterations` (int, default=3): The number of full workload-size sweeps per suite run.
- `ssh_connection` (boolean, default=false): Whether to use SSH instead of serial/ADB for execution.
- `bypass_gap` (boolean, default=false): Whether to bypass the 5-minute cooldown gap between suite runs.
- `build_id` (string, optional): Identifier for the build being tested. Auto-detected via ADB if omitted.

### Understanding `-r` (Runs) vs `--iterations`

- `-r`/`--runs`: outer loop — how many times the entire lat_mem_rd suite runs.
- `--iterations`: inner loop — how many full workload-size sweeps run *within* a single suite run.

Note: `lat_mem_rd` is a `metric_direction: lower` benchmark — a **lower** plateau latency (ns) indicates **better** (faster) memory performance.

## Usage Instructions

1. Parse the user's intent to determine how many times they want to run lat_mem_rd.
2. Execute the `main.py` harness with the `-b lat_mem_rd` and `-r <runs>` arguments.
3. Once completed, parse the `build_analysis.json` and `results.json` files generated in the `output/lat_mem_rd/` folder to present the overall plateau latency and repeatability.

### Implementation Example (Python)

```python
import os
import glob
import json
import subprocess

runs = 1  # Example
use_ssh = True
bypass_gap = False

cmd = ["python", "main.py", "-b", "lat_mem_rd", "-r", str(runs)]
if use_ssh:
    cmd.append("--ssh-connection")
if bypass_gap:
    cmd.append("--bypass-gap")

print(f"Executing: {' '.join(cmd)}")
result = subprocess.run(cmd, capture_output=True, text=True, cwd="aibench")

if result.returncode != 0:
    print(f"Harness Execution Failed!\n{result.stderr}")
else:
    out_dir = os.path.join("aibench", "output", "lat_mem_rd")
    build_dirs = sorted(glob.glob(os.path.join(out_dir, "build_*")), key=os.path.getmtime)

    if not build_dirs:
        print("Error: No build directories found for lat_mem_rd.")
    else:
        latest_build = build_dirs[-1]
        run_dirs = sorted(glob.glob(os.path.join(latest_build, "run_*")))
        if run_dirs:
            latest_run = run_dirs[-1]
            results_file = os.path.join(latest_run, "results.json")
            if os.path.exists(results_file):
                with open(results_file, "r") as f:
                    data = json.load(f)

                tests = data.get("tests", {})
                for test_name, test_data in tests.items():
                    plateau_ns = test_data.get("overall_plateau_latency_ns", "N/A")
                    spread_pct = test_data.get("iteration_to_iteration_spread_pct", "N/A")
                    discarded = test_data.get("outlier_discarded_count", 0)
                    print(f"=====================================")
                    print(f"LAT_MEM_RD SUMMARY: {test_name} (lower is better)")
                    print(f"=====================================")
                    print(f"Overall Plateau Latency: {plateau_ns} ns")
                    print(f"Iteration-to-Iteration Spread: {spread_pct}%")
                    print(f"Outlier Iterations Discarded: {discarded}")
            else:
                print("Error: results.json not found in latest run.")
        else:
            print("Error: No run directories found.")
```

## Expected Output Format

```
I have executed the lat_mem_rd benchmark.

**Results for lat_mem_rd_default (LOWER is better)**:
- **Overall Plateau Latency**: 141.72 ns
- **Iteration-to-Iteration Spread**: 1.85%
- **Outlier Iterations Discarded**: 0 (out of 3)

The plateau was detected using the trailing points of the largest working-set size (256M),
indicating stable, memory-bound latency behavior.
```

## Error Handling
- If `/usr/bin/lat_mem_rd` is not found, the harness logs an error during setup but still attempts execution.
- Each workload-size command retries up to `retry_attempts` (default 3) times if parsing fails or output is empty.
- If no valid trailing window satisfies the plateau-validity thresholds, the result is marked `plateau_valid: false` with a best-effort fallback average and a `reason` explaining why — surface this caveat to the user if present.
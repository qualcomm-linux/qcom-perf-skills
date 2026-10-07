---
name: run-bw-mem
description: Runs the bw_mem (lmbench) memory-bandwidth benchmark across a worker-count sweep to detect the bandwidth saturation plateau for read/write/copy operations. Reference only -- routed to by the benchmark-orchestrator skill; do not invoke directly for ad-hoc benchmark requests.
category: Performance Benchmarking
---

# Run bw_mem Benchmark
**Author:** Sarbojit Ganguly <sarbgang@qti.qualcomm.com>

This skill executes lmbench's `bw_mem` tool once per worker count (from `worker_start` to `worker_end`, default `1` to `$(nproc)`) for each configured operation (`rd`, `wr`, `cp`, `rdwr`, `frd`, `fwr`), per command: `/usr/bin/bw_mem -P <workers> <memory_size> <op>`. It then detects the bandwidth-saturation plateau across the worker sweep for each operation.

## Prerequisites
- The environment must be configured with `benchmarks.yaml` pointing to a valid target.
- AI Agent must execute this from the `aibench/` directory.
- The target must have `/usr/bin/bw_mem` present.
- Because it sweeps `worker_start` to `nproc` for each of up to 6 operations, this benchmark can take a long time on high-core-count targets — set expectations accordingly.

## Parameters

- `runs` (int, default=1): The number of sequential suite runs to perform.
- `iterations` (int, default=1): The number of full worker-sweeps per operation per suite run.
- `ssh_connection` (boolean, default=false): Whether to use SSH instead of serial/ADB for execution.
- `bypass_gap` (boolean, default=false): Whether to bypass the 5-minute cooldown gap between suite runs.
- `tests` (list, optional): Restrict execution to specific operations, e.g. `bw_mem_rd`, `bw_mem_wr` (default: all configured operations).
- `build_id` (string, optional): Identifier for the build being tested. Auto-detected via ADB if omitted.

### Understanding `-r` (Runs) vs `--iterations`

- `-r`/`--runs`: outer loop — how many times the entire bw_mem suite runs.
- `--iterations`: inner loop — how many full worker-sweeps run per operation *within* a single suite run.

Note: `bw_mem` is a `metric_direction: higher` benchmark — a **higher** plateau bandwidth (GB/s) indicates **better** memory performance.

## Usage Instructions

1. Parse the user's intent to determine how many times, and which memory operations (rd/wr/cp/rdwr/frd/fwr), they want to run.
2. Execute the `main.py` harness with the `-b bw_mem` and `-r <runs>` arguments (optionally `-t bw_mem_rd bw_mem_wr` etc.).
3. Once completed, parse the `results.json` file generated in the `output/bw_mem/` folder's latest run directory to present the plateau bandwidth and saturation point per operation.

### Implementation Example (Python)

```python
import os
import glob
import json
import subprocess

runs = 1  # Example
use_ssh = True
bypass_gap = False

cmd = ["python", "main.py", "-b", "bw_mem", "-r", str(runs)]
if use_ssh:
    cmd.append("--ssh-connection")
if bypass_gap:
    cmd.append("--bypass-gap")

print(f"Executing: {' '.join(cmd)}")
result = subprocess.run(cmd, capture_output=True, text=True, cwd="aibench")

if result.returncode != 0:
    print(f"Harness Execution Failed!\n{result.stderr}")
else:
    out_dir = os.path.join("aibench", "output", "bw_mem")
    build_dirs = sorted(glob.glob(os.path.join(out_dir, "build_*")), key=os.path.getmtime)

    if not build_dirs:
        print("Error: No build directories found for bw_mem.")
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
                for iter_key, iter_data in tests.items():
                    print(f"=====================================")
                    print(f"BW_MEM SUMMARY: {iter_key} (higher is better)")
                    print(f"=====================================")
                    for op, op_data in iter_data.items():
                        plateau = op_data.get("plateau", "N/A")
                        sat_worker = op_data.get("saturation_worker", "N/A")
                        detected = op_data.get("plateau_detected", False)
                        anomaly = op_data.get("anomaly")
                        line = f"  {op}: plateau={plateau} GB/s, saturation_worker={sat_worker}, detected={detected}"
                        if anomaly:
                            line += f", anomaly={anomaly}"
                        print(line)
            else:
                print("Error: results.json not found in latest run.")
        else:
            print("Error: No run directories found.")
```

## Expected Output Format

```
I have executed the bw_mem benchmark.

**Results (GB/sec, HIGHER is better)**:
- bw_mem_rd: plateau=12.45 GB/s, saturation at P=4 workers, range=4-8
- bw_mem_wr: plateau=9.87 GB/s, saturation at P=3 workers, range=3-8
- bw_mem_cp: plateau=6.21 GB/s, saturation at P=5 workers, range=5-8
- bw_mem_rdwr: plateau=8.03 GB/s, saturation at P=4 workers, range=4-8
- bw_mem_frd: plateau=11.98 GB/s, saturation at P=4 workers, range=4-8
- bw_mem_fwr: plateau=9.55 GB/s, no plateau detected (bandwidth still scaling at max worker count)
```

## Error Handling
- If `/usr/bin/bw_mem` is not found, the harness logs an error during setup but still attempts execution.
- If a "bandwidth_collapse" anomaly is detected (bandwidth drops >20% between consecutive worker counts), the analysis is restricted to the pre-collapse region and the collapse worker count is reported — surface this to the user.
- If no worker count yields a valid plateau, `plateau_detected` is `false` and the `reason` field explains why (e.g. insufficient stable samples); the max observed bandwidth (`peak_observed`) is still reported as a best-effort figure.
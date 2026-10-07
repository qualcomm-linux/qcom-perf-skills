---
name: run-unixbench
description: Runs the UnixBench (BYTE UNIX Benchmarks) suite to measure OS/Kernel/Scheduler performance via single-core and multi-core index scores plus scaling efficiency. Reference only -- routed to by the benchmark-orchestrator skill; do not invoke directly for ad-hoc benchmark requests.
category: Performance Benchmarking
---

# Run UnixBench Benchmark
**Author:** Sarbojit Ganguly <sarbgang@qti.qualcomm.com>

This skill executes the UnixBench suite, which runs the full `Run` script once in single-core mode (`-c 1`) and once in multi-core mode (`-c $(nproc)`) per iteration, then derives a scaling-efficiency metric from the two index scores.

## Prerequisites
- The environment must be configured with `benchmarks.yaml` pointing to a valid target.
- AI Agent must execute this from the `aibench/` directory.
- The target must have `/usr/share/unixbench/Run` present.

## Parameters

- `runs` (int, default=1): The number of sequential suite runs to perform.
- `iterations` (int, default=1): Number of internal single/multi-core passes per suite run (configured via `benchmarks.yaml`, can be overridden with `--iterations`).
- `ssh_connection` (boolean, default=false): Whether to use SSH instead of serial/ADB for execution.
- `bypass_gap` (boolean, default=false): Whether to bypass the 5-minute cooldown gap between suite runs.
- `build_id` (string, optional): Identifier for the build being tested. Auto-detected via ADB if omitted.

### Understanding `-r` (Runs) vs `--iterations`

- `-r`/`--runs`: outer loop — how many times the entire unixbench suite runs.
- `--iterations`: inner loop — how many single+multi-core passes run *within* a single suite run (default 1, since each pass is already lengthy).

## Usage Instructions

1. Parse the user's intent to determine how many times they want to run unixbench.
2. Execute the `main.py` harness with the `-b unixbench` and `-r <runs>` arguments.
3. Once completed, parse the `build_analysis.json` and `results.json` files generated in the `output/unixbench/` folder to present the aggregated results and run details.

Note: A single UnixBench pass (single-core + multi-core) can take 15-40 minutes depending on target hardware. Set expectations with the user accordingly.

### Implementation Example (Python)

```python
import os
import glob
import json
import subprocess

# Parameters derived from AI Agent context
runs = 1  # Example
use_ssh = True
bypass_gap = False

cmd = ["python", "main.py", "-b", "unixbench", "-r", str(runs)]
if use_ssh:
    cmd.append("--ssh-connection")
if bypass_gap:
    cmd.append("--bypass-gap")

print(f"Executing: {' '.join(cmd)}")
result = subprocess.run(cmd, capture_output=True, text=True, cwd="aibench")

if result.returncode != 0:
    print(f"Harness Execution Failed!\n{result.stderr}")
else:
    unixbench_out_dir = os.path.join("aibench", "output", "unixbench")
    build_dirs = sorted(glob.glob(os.path.join(unixbench_out_dir, "build_*")), key=os.path.getmtime)

    if not build_dirs:
        print("Error: No build directories found for unixbench.")
    else:
        latest_build = build_dirs[-1]
        analysis_file = os.path.join(latest_build, "build_analysis.json")

        if os.path.exists(analysis_file):
            with open(analysis_file, "r") as f:
                data = json.load(f)

            stats = data.get("statistics", {})
            single_score = stats.get("unixbench_single_core", {}).get("mean", "N/A")
            multi_score = stats.get("unixbench_multi_core", {}).get("mean", "N/A")
            scaling = stats.get("unixbench_scaling", {}).get("mean", "N/A")

            print(f"=====================================")
            print(f"UNIXBENCH SUMMARY")
            print(f"=====================================")
            print(f"Single-Core Index Score: {single_score}")
            print(f"Multi-Core Index Score: {multi_score}")
            print(f"Scaling Efficiency: {scaling}%")
            print(f"=====================================")
        else:
            print("Error: build_analysis.json not generated.")
```

## Expected Output Format

```
I have executed the UnixBench suite.

**Overall Results**:
- **Single-Core Index Score**: 1245.3 (Higher is better)
- **Multi-Core Index Score**: 8414.3 (Higher is better)
- **Scaling Efficiency**: 84.5% (multi/single normalized by core count)

Note: Scaling efficiency below ~70% may indicate scheduler contention or thermal throttling under multi-core load.
```

## Error Handling
- If `/usr/share/unixbench` is not found on the target, the harness logs an error but still attempts execution; the skill should surface this warning to the user.
- If the "System Benchmarks Index Score" cannot be parsed from either the single-core or multi-core run, that pass is skipped and excluded from averages.
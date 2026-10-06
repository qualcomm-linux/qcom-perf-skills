---
name: run-ramspeed
description: Runs the RAMSpeed benchmark (single-threaded and multi-threaded) to measure DDR memory throughput across integer/float read/write/average workloads. Reference only -- routed to by the benchmark-orchestrator skill; do not invoke directly for ad-hoc benchmark requests.
category: Performance Benchmarking
---

# Run RAMSpeed Benchmark
**Author:** Sarbojit Ganguly <sarbgang@qti.qualcomm.com>

This skill executes RAMSpeed, using the `ramspeed` binary for single-threaded runs (`ramspeed_single`) and `ramsmp` with `-p $(nproc)` for multi-threaded runs (`ramspeed_multi`). Each run sweeps through 6 benchmark IDs: `intmark_writing`, `intmark_reading`, `integer_average`, `floatmark_writing`, `floatmark_reading`, `float_average`.

## Prerequisites
- The environment must be configured with `benchmarks.yaml` pointing to a valid target.
- AI Agent must execute this from the `aibench/` directory.
- The target must have `/usr/bin/ramspeed` and `/usr/bin/ramsmp` present.

## Parameters

- `runs` (int, default=1): The number of sequential suite runs to perform.
- `iterations` (int, default=3): The number of internal repetitions per benchmark ID per suite run.
- `ssh_connection` (boolean, default=false): Whether to use SSH instead of serial/ADB for execution.
- `bypass_gap` (boolean, default=false): Whether to bypass the 5-minute cooldown gap between suite runs.
- `tests` (list, optional): Restrict execution to `ramspeed_single` and/or `ramspeed_multi` (default: both).
- `build_id` (string, optional): Identifier for the build being tested. Auto-detected via ADB if omitted.

### Understanding `-r` (Runs) vs `--iterations`

- `-r`/`--runs`: outer loop — how many times the entire ramspeed suite runs.
- `--iterations`: inner loop — how many times each benchmark ID repeats *within* a single suite run.

## Usage Instructions

1. Parse the user's intent to determine how many times they want to run ramspeed, and whether they want single-threaded, multi-threaded, or both.
2. Execute the `main.py` harness with the `-b ramspeed` and `-r <runs>` arguments.
3. Once completed, parse the `build_analysis.json` and `results.json` files generated in the `output/ramspeed/` folder to present the aggregated Mb/s throughput for each benchmark ID.

### Implementation Example (Python)

```python
import os
import glob
import json
import subprocess

runs = 1  # Example
use_ssh = True
bypass_gap = False

cmd = ["python", "main.py", "-b", "ramspeed", "-r", str(runs)]
if use_ssh:
    cmd.append("--ssh-connection")
if bypass_gap:
    cmd.append("--bypass-gap")

print(f"Executing: {' '.join(cmd)}")
result = subprocess.run(cmd, capture_output=True, text=True, cwd="aibench")

if result.returncode != 0:
    print(f"Harness Execution Failed!\n{result.stderr}")
else:
    out_dir = os.path.join("aibench", "output", "ramspeed")
    build_dirs = sorted(glob.glob(os.path.join(out_dir, "build_*")), key=os.path.getmtime)

    if not build_dirs:
        print("Error: No build directories found for ramspeed.")
    else:
        latest_build = build_dirs[-1]
        analysis_file = os.path.join(latest_build, "build_analysis.json")

        if os.path.exists(analysis_file):
            with open(analysis_file, "r") as f:
                data = json.load(f)

            stats = data.get("statistics", {})
            print(f"=====================================")
            print(f"RAMSPEED BENCHMARK SUMMARY")
            print(f"=====================================")
            for test_key, test_stats in sorted(stats.items()):
                mean_val = test_stats.get("mean", "N/A")
                print(f"  {test_key}: {mean_val} Mb/s")
            print(f"=====================================")
        else:
            print("Error: build_analysis.json not generated.")
```

## Expected Output Format

```
I have executed the RAMSpeed benchmark suite.

**Single-Threaded Results (Mb/s, higher is better)**:
- ramspeed_single_b1_intmark_writing: 4521.3
- ramspeed_single_b2_intmark_reading: 4890.1
- ramspeed_single_b3_integer_average: 4705.7
- ramspeed_single_b4_floatmark_writing: 4488.9
- ramspeed_single_b5_floatmark_reading: 4802.5
- ramspeed_single_b6_float_average: 4645.7

**Multi-Threaded Results (Mb/s, higher is better)**:
- ramspeed_multi_b1_intmark_writing: 15200.4
- ... (similarly for remaining benchmark IDs)
```

## Error Handling
- If `/usr/bin/ramspeed` or `/usr/bin/ramsmp` are not found, the harness logs a warning during setup but continues with remaining benchmarks.
- If output parsing fails for a given benchmark ID/iteration (missing `Mb/s` line), `throughput_mbps` defaults to `0.0` and is logged as a warning.
---
name: run-coremark-pro
description: Runs the Coremark-Pro benchmark suite (9 microbenchmarks in both single-core and multi-core modes) to measure advanced CPU performance across mixed-integer, floating-point, and DSP-style workloads. Reference only -- routed to by the benchmark-orchestrator skill; do not invoke directly for ad-hoc benchmark requests.
category: Performance Benchmarking
---

# Run Coremark-Pro Benchmark
**Author:** Sarbojit Ganguly <sarbgang@qti.qualcomm.com>

This skill executes the Coremark-Pro suite, running each configured microbenchmark (`core`, `cjpeg-rose7-preset`, `linear_alg-mid-100x100-sp`, `loops-all-mid-10k-sp`, `nnet_test`, `parser-125k`, `radix2-big-64k`, `sha-test`, `zip-test`) in both single-core (`-c1`) and multi-core (`-c$(nproc)`) modes, for a configurable number of iterations.

## Prerequisites
- The environment must be configured with `benchmarks.yaml` pointing to a valid target.
- AI Agent must execute this from the `aibench/` directory.
- The 9 microbenchmark binaries must be present under `/usr/bin/` on the target.

## Parameters

- `runs` (int, default=1): The number of sequential suite runs to perform.
- `iterations` (int, default=3): The number of internal repetitions per microbenchmark per suite run.
- `ssh_connection` (boolean, default=false): Whether to use SSH instead of serial/ADB for execution.
- `bypass_gap` (boolean, default=false): Whether to bypass the 5-minute cooldown gap between suite runs.
- `tests` (list, optional): Restrict execution to `coremark_pro_single` and/or `coremark_pro_multi` (default: both).
- `build_id` (string, optional): Identifier for the build being tested. Auto-detected via ADB if omitted.

### Understanding `-r` (Runs) vs `--iterations`

- `-r`/`--runs`: outer loop — how many times the entire coremark_pro suite runs.
- `--iterations`: inner loop — how many times each microbenchmark repeats *within* a single suite run.

## Usage Instructions

1. Parse the user's intent to determine how many times they want to run coremark-pro, and whether they want single-core, multi-core, or both.
2. Execute the `main.py` harness with the `-b coremark_pro` and `-r <runs>` arguments (optionally `-t coremark_pro_single` / `coremark_pro_multi`).
3. Once completed, parse the `build_analysis.json` and `results.json` files generated in the `output/coremark_pro/` folder to present the aggregated workloads/sec for each microbenchmark.

### Implementation Example (Python)

```python
import os
import glob
import json
import subprocess

runs = 1  # Example
use_ssh = True
bypass_gap = False

cmd = ["python", "main.py", "-b", "coremark_pro", "-r", str(runs)]
if use_ssh:
    cmd.append("--ssh-connection")
if bypass_gap:
    cmd.append("--bypass-gap")

print(f"Executing: {' '.join(cmd)}")
result = subprocess.run(cmd, capture_output=True, text=True, cwd="aibench")

if result.returncode != 0:
    print(f"Harness Execution Failed!\n{result.stderr}")
else:
    out_dir = os.path.join("aibench", "output", "coremark_pro")
    build_dirs = sorted(glob.glob(os.path.join(out_dir, "build_*")), key=os.path.getmtime)

    if not build_dirs:
        print("Error: No build directories found for coremark_pro.")
    else:
        latest_build = build_dirs[-1]
        analysis_file = os.path.join(latest_build, "build_analysis.json")

        if os.path.exists(analysis_file):
            with open(analysis_file, "r") as f:
                data = json.load(f)

            stats = data.get("statistics", {})
            print(f"=====================================")
            print(f"COREMARK-PRO BENCHMARK SUMMARY")
            print(f"=====================================")
            for test_key, test_stats in sorted(stats.items()):
                mean_val = test_stats.get("mean", "N/A")
                print(f"  {test_key}: {mean_val} workloads/sec")
            print(f"=====================================")
        else:
            print("Error: build_analysis.json not generated.")
```

## Expected Output Format

```
I have executed the Coremark-Pro benchmark suite.

**Single-Core Results (workloads/sec, higher is better)**:
- coremark_pro_single_core: 12.45
- coremark_pro_single_cjpeg-rose7-preset: 8.32
- coremark_pro_single_linear_alg-mid-100x100-sp: 45.67
- coremark_pro_single_loops-all-mid-10k-sp: 3.21
- coremark_pro_single_nnet_test: 1.98
- coremark_pro_single_parser-125k: 15.60
- coremark_pro_single_radix2-big-64k: 22.10
- coremark_pro_single_sha-test: 33.45
- coremark_pro_single_zip-test: 9.87

**Multi-Core Results (workloads/sec, higher is better)**:
- coremark_pro_multi_core: 88.30
- ... (similarly for each microbenchmark)
```

## Error Handling
- If any microbenchmark binary is not found under `/usr/bin/`, the harness logs a warning during setup but continues with remaining benchmarks.
- If output parsing fails for a given microbenchmark/iteration (missing `workloads/sec` line), the corresponding entry is recorded with `workload_id=""` and excluded from aggregation.
---
name: run-coremark
description: Runs the Coremark benchmark multiple times sequentially to measure CPU performance. Evaluates iterations per second. Reference only -- routed to by the benchmark-orchestrator skill; do not invoke directly for ad-hoc benchmark requests.
category: Performance Benchmarking
---

# Run Coremark Benchmark
**Author:** Sarbojit Ganguly <sarbgang@qti.qualcomm.com>

This skill executes the Coremark benchmark sequentially for a requested number of runs. It bypasses the cooldown gap if needed and captures the overall average Iterations/Sec score across all successful runs, along with detailed run logs.

## Prerequisites
- The environment must be configured with `benchmarks.yaml` pointing to a valid target.
- AI Agent must execute this from the `aibench/` directory.

## Parameters

- `runs` (int, default=1): The number of sequential **suite** runs to perform (`-r`/`--runs`, outer loop).
- `iterations` (int, default=3): The number of internal repetitions **per suite run** for the coremark test (`--iterations`, inner loop).
- `ssh_connection` (boolean, default=false): Whether to use SSH instead of serial/ADB for execution.
- `bypass_gap` (boolean, default=false): Whether to bypass the 5-minute cooldown gap between suite runs.

### Understanding `-r` (Runs) vs `--iterations`

- `-r`/`--runs`: how many times the entire suite runs (each producing its own report/output folder).
- `--iterations`: how many times the coremark test repeats *within* a single suite run.
- **Total executions = runs × iterations.**

## Usage Instructions

1. Parse the user's intent to determine how many times they want to run coremark.
2. Execute the `main.py` harness with the `-b coremark` and `-r <runs>` arguments.
3. Once completed, parse the `build_analysis.json` and `results.json` files generated in the `output/coremark/` folder to present the aggregated results and run details.

### Implementation Example (Python)

```python
import os
import glob
import json
import subprocess

# Parameters derived from AI Agent context
runs = 3 # Example
use_ssh = True
bypass_gap = False

cmd = ["python", "main.py", "-b", "coremark", "-r", str(runs)]
if use_ssh:
    cmd.append("--ssh-connection")
if bypass_gap:
    cmd.append("--bypass-gap")

print(f"Executing: {' '.join(cmd)}")
result = subprocess.run(cmd, capture_output=True, text=True, cwd="aibench")

if result.returncode != 0:
    print(f"Harness Execution Failed!\n{result.stderr}")
else:
    # Find latest build analysis
    coremark_out_dir = os.path.join("aibench", "output", "coremark")
    build_dirs = sorted(glob.glob(os.path.join(coremark_out_dir, "build_*")), key=os.path.getmtime)
    
    if not build_dirs:
        print("Error: No build directories found for coremark.")
    else:
        latest_build = build_dirs[-1]
        analysis_file = os.path.join(latest_build, "build_analysis.json")
        
        if os.path.exists(analysis_file):
            with open(analysis_file, "r") as f:
                data = json.load(f)
            
            stats = data.get("statistics", {})
            avg_score = stats.get("coremark_default", {}).get("mean", "N/A")
            
            print(f"=====================================")
            print(f"COREMARK BENCHMARK SUMMARY")
            print(f"=====================================")
            print(f"Total Runs Aggregated: {data.get('metadata', {}).get('total_runs_aggregated', runs)}")
            print(f"Average Iterations/Sec: {avg_score}")
            print(f"=====================================")
            
            # Print detailed logs for each run
            print("\nDetailed Logs per Run:")
            run_dirs = sorted(glob.glob(os.path.join(latest_build, "run_*")))
            
            for i, rdir in enumerate(run_dirs):
                res_file = os.path.join(rdir, "results.json")
                if os.path.exists(res_file):
                    with open(res_file, "r") as rf:
                        rdata = json.load(rf)
                    
                    c_default = rdata.get("tests", {}).get("coremark_default", {})
                    tp = c_default.get("throughput", [])
                    if tp:
                        run_avg = sum(tp) / len(tp)
                        print(f"  Run {i+1}: {run_avg:.2f} Iterations/Sec (Successful)")
                    else:
                        print(f"  Run {i+1}: FAILED (No valid throughput data)")
                else:
                    print(f"  Run {i+1}: FAILED (Missing results.json)")
        else:
            print("Error: build_analysis.json not generated.")
```

## Expected Output Format

When presenting the final results to the user, ensure it includes both the average metric and the detailed success/failure log.

Example response to user:
```
I have executed the Coremark benchmark 5 times.

**Overall Results**:
- **Average Performance**: 25634.45 Iterations/Sec
- **Unit**: Iterations/Sec (Higher is better)

**Detailed Run Logs**:
- Run 1: 25634.45 Iterations/Sec (Successful)
- Run 2: 25500.12 Iterations/Sec (Successful)
- Run 3: FAILED (No valid throughput data)
- Run 4: 25700.89 Iterations/Sec (Successful)
- Run 5: 25650.23 Iterations/Sec (Successful)

Note: Failed runs were automatically excluded from the final average by the aggregator engine.
---
name: run-geekbench
description: Runs the Geekbench 6 CPU benchmark to measure single-core and multi-core performance. Reference only -- routed to by the benchmark-orchestrator skill; do not invoke directly for ad-hoc benchmark requests.
category: Performance Benchmarking
---

# Run Geekbench Benchmark
**Author:** Sarbojit Ganguly <sarbgang@qti.qualcomm.com>

This skill executes the Geekbench 6 CPU benchmark sequentially for a requested number of runs. It captures Single-Core and Multi-Core scores, along with detailed Integer and Floating Point component scores.

## Prerequisites
- Geekbench 6 binary must be installed at `/root/geekbench6` on the target device (the native Linux/GNU build — not `geekbench_aarch64`, which is the Android/NDK build and cannot execute on this Linux target)
- AI Agent must execute this from the `aibench/` directory
- Geekbench execution takes approximately 2-3 minutes per iteration

## Parameters

- `runs` (int, default=1): The number of sequential **suite** runs to perform (`-r`/`--runs`, outer loop)
- `iterations` (int, default=3): The number of internal repetitions **per suite run** (`--iterations`, inner loop)
- `ssh_connection` (boolean, default=false): Whether to use SSH instead of serial/ADB for execution
- `bypass_gap` (boolean, default=false): Whether to bypass the 5-minute cooldown gap between suite runs

### Understanding `-r` (Runs) vs `--iterations`

- `-r`/`--runs`: how many times the entire suite runs (each producing its own report/output folder)
- `--iterations`: how many times Geekbench executes *within* a single suite run
- **Total executions = runs × iterations**

## Metrics Collected

### Primary Metrics (Displayed in Dashboards)
- **Single-Core Score**: Overall single-threaded CPU performance (higher is better)
- **Multi-Core Score**: Overall multi-threaded CPU performance (higher is better)

### Component Metrics (Stored in results.json)
- **Single-Core Integer Score**: Integer computation performance
- **Single-Core Floating Point Score**: Floating point computation performance
- **Multi-Core Integer Score**: Multi-threaded integer performance
- **Multi-Core Floating Point Score**: Multi-threaded floating point performance

All 6 metrics are stored in `results.json` for detailed analysis. Only Single-Core and Multi-Core scores appear in `build_history.json` and dashboard visualizations.

## Usage Instructions

1. Parse the user's intent to determine how many times they want to run Geekbench
2. Execute the `main.py` harness with the `-b geekbench` and `-r <runs>` arguments
3. Once completed, parse the `build_analysis.json` and `results.json` files generated in the `output/geekbench/` folder to present the aggregated results

### Implementation Example (Python)

```python
import os
import glob
import json
import subprocess

# Parameters derived from AI Agent context
runs = 3  # Example
use_ssh = True
bypass_gap = False

cmd = ["python", "main.py", "-b", "geekbench", "-r", str(runs)]
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
    geekbench_out_dir = os.path.join("aibench", "output", "geekbench")
    build_dirs = sorted(glob.glob(os.path.join(geekbench_out_dir, "build_*")), key=os.path.getmtime)
    
    if not build_dirs:
        print("Error: No build directories found for geekbench.")
    else:
        latest_build = build_dirs[-1]
        analysis_file = os.path.join(latest_build, "build_analysis.json")
        
        if os.path.exists(analysis_file):
            with open(analysis_file, "r") as f:
                data = json.load(f)
            
            stats = data.get("statistics", {})
            single_core_avg = stats.get("geekbench_cpu", {}).get("single_core_mean", "N/A")
            multi_core_avg = stats.get("geekbench_cpu", {}).get("multi_core_mean", "N/A")
            
            print(f"=====================================")
            print(f"GEEKBENCH BENCHMARK SUMMARY")
            print(f"=====================================")
            print(f"Total Runs Aggregated: {data.get('metadata', {}).get('total_runs_aggregated', runs)}")
            print(f"Average Single-Core Score: {single_core_avg}")
            print(f"Average Multi-Core Score: {multi_core_avg}")
            print(f"=====================================")
            
            # Print detailed logs for each run
            print("\nDetailed Logs per Run:")
            run_dirs = sorted(glob.glob(os.path.join(latest_build, "run_*")))
            
            for i, rdir in enumerate(run_dirs):
                res_file = os.path.join(rdir, "results.json")
                if os.path.exists(res_file):
                    with open(res_file, "r") as rf:
                        rdata = json.load(rf)
                    
                    test_data = rdata.get("tests", {}).get("geekbench_cpu", {})
                    sc_scores = test_data.get("single_core_scores", [])
                    mc_scores = test_data.get("multi_core_scores", [])
                    
                    if sc_scores and mc_scores:
                        sc_avg = sum(sc_scores) / len(sc_scores)
                        mc_avg = sum(mc_scores) / len(mc_scores)
                        print(f"  Run {i+1}: Single-Core={sc_avg:.0f}, Multi-Core={mc_avg:.0f} (Successful)")
                    else:
                        print(f"  Run {i+1}: FAILED (No valid score data)")
                else:
                    print(f"  Run {i+1}: FAILED (Missing results.json)")
        else:
            print("Error: build_analysis.json not generated.")
```

## Expected Output Format

When presenting the final results to the user, ensure it includes both the average metrics and the detailed success/failure log.

Example response to user:
```
I have executed the Geekbench benchmark 3 times.

**Overall Results**:
- **Average Single-Core Score**: 1125 (Higher is better)
- **Average Multi-Core Score**: 5448 (Higher is better)

**Detailed Run Logs**:
- Run 1: Single-Core=1125, Multi-Core=5448 (Successful)
- Run 2: Single-Core=1126, Multi-Core=5450 (Successful)
- Run 3: Single-Core=1124, Multi-Core=5446 (Successful)

**Note**: All 6 component metrics (Integer/Float scores for both Single-Core and Multi-Core) are available in the detailed results.json file for in-depth analysis.
```

## Command Examples

Run Geekbench with default parameters over SSH:
```bash
python main.py -b geekbench --ssh-connection
```

Run Geekbench for 3 runs over SSH:
```bash
python main.py -b geekbench -r 3 --ssh-connection
```

Run Geekbench with custom iterations:
```bash
python main.py -b geekbench --iterations 5 --ssh-connection
```

Run Geekbench bypassing cooldown gap:
```bash
python main.py -b geekbench -r 2 --bypass-gap --ssh-connection
```

## Output Files

- **results.json**: Contains all 6 metrics for each iteration
- **build_analysis.json**: Contains aggregated statistics (Single-Core and Multi-Core averages)
- **individual_report.html**: Visual dashboard showing Single-Core and Multi-Core scores
- **rca_report.json**: Root cause analysis if regression detected (automatic)

## Notes

- Geekbench takes approximately 2-3 minutes per iteration
- The benchmark automatically includes a 10-second cooldown between iterations
- Outlier detection monitors all 6 metrics to ensure data quality
- Failed runs are automatically excluded from the final average by the aggregator engine
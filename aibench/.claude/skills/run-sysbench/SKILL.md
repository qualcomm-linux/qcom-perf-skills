---
name: run-sysbench
description: Runs the Sysbench multi-category benchmark suite (CPU prime, memory sequential/random, thread yielding, mutex locking) sequentially over serial/SSH. Reference only -- routed to by the benchmark-orchestrator skill; do not invoke directly for ad-hoc benchmark requests.
category: Performance Benchmarking
---

# Skill: Run Sysbench Benchmark
**Author:** Sarbojit Ganguly <sarbgang@qti.qualcomm.com>

Executes the Sysbench multi-category benchmark suite.

## Location & Entry Point
The entry point is `main.py`, located in the root of the `aibench/` folder.
You **must** run it from the `aibench/` directory.

## Usage
```bash
python main.py --benchmark sysbench [options]
```

## Description
Runs various Sysbench categories (CPU prime, memory sequentials/randoms, thread yieldings, and mutex locking) sequentially over serial/SSH, ensuring system cache drops between runs.

## Command-Line Parameters
Do not run `python main.py --help`. All supported parameters are documented here:
- `--benchmark sysbench` (or `-b sysbench`): Specifies this benchmark.
- `--runs <N>` (or `-r <N>`): Number of times the entire sysbench suite runs (outer loop). Default: 1.
- `--iterations <N>`: Number of times each selected sub-test repeats within a single suite run (inner loop). Default: 3.
- `--bypass-gap`: Skips the default 5-minute sequential execution cooling gap between runs.
- `--ssh-connection`: Perform all activities via SSH instead of ADB/Serial.
- `--tests <test1> <test2>` (or `-t`): Run specific sub-tests instead of the full suite.
- `--build-id <id>`: Manually specify a build ID (auto-detected if omitted).

### Root Cause Analysis (RCA) & Baselines
- `--store-baseline`: Saves the current run's statistics as a named baseline for RCA regression detection.
- `--baseline-tag <name>`: Names the baseline slot. Defaults to "default" if omitted.
*Note: The regression detection and RCA skill is automatically invoked by `main.py` after completion. No additional arguments are needed to trigger RCA during a normal run, it compares against prior runs automatically. The RCA feature itself currently has limited regression detection capabilities in this repository version.*

### Logging & Progress Monitoring (CRITICAL RULE)
During benchmark execution, progress is automatically logged to the following centralized location:
`aibench/logging/log-<date>_<timestamp>.log`

**CRITICAL RULE FOR THE LLM: DO NOT INVESTIGATE LOGGING.**
- Do **NOT** search the codebase (`main.py`, `src/utils/logger.py`, etc.) for logging patterns.
- Do **NOT** run `find`, `ls`, or glob searches to locate `.log` files.
- The logging mechanism is fully automatic and requires no configuration on your part.

If the user asks to monitor progress or see logs:
1. Start the benchmark process in the background.
2. Inform the user that logs are being generated at `aibench/logging/log-*.log` (resolve the exact filename dynamically if needed by listing the `aibench/logging/` directory *after* the run starts).
3. If necessary, you can tail the file to stream progress, e.g., `tail -f aibench/logging/log-*.log`. Do not search for `main.py` logging configurations to figure this out.

## Examples

Run sysbench for 3 runs without gaps (cooldown bypassed):
```bash
python main.py -b sysbench -r 3 --bypass-gap
```

Run sysbench over SSH, store it as a baseline for future RCA:
```bash
python main.py -b sysbench --ssh-connection --store-baseline --baseline-tag golden
```

**Total executions per sub-test = runs × iterations.**

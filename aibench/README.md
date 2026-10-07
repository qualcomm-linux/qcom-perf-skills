# AIBench

AIBench is an AI-powered unified benchmark harness for embedded Linux devices. It drives a suite of industry-standard benchmarks (CoreMark, Sysbench, Hackbench, TIOBench, UnixBench, GLMark2, and more) against a target device over SSH, serial, or ADB, then automatically generates reports, tracks performance across builds, and flags regressions with root-cause analysis.

It's built around Claude Code's agent-skill framework: you can drive the whole workflow conversationally ("run coremark and sysbench on my device") and let the `benchmark-orchestrator` skill parse intent and route to the right benchmark, or invoke `main.py` directly for scripted/CI use.

## Overview

AIBench orchestrates benchmark execution on target devices with comprehensive reporting, device history management, and regression detection capabilities.

## Quick Start

```bash
# Run all active benchmarks (default mode)
python main.py

# Run specific benchmark over SSH
python main.py -b sysbench --ssh-connection

# Run with custom iterations
python main.py -b coremark -r 5 --iterations 3

# Connect using device name (from history)
python main.py --host lemans
```

## Documentation

- **[Quick Start Guide](documentation/quickstart.md)** - Get started quickly
- **[Adding New Benchmarks](documentation/AddNewBenchmark.md)** - Developer guide
- **[FAQ](FAQ.md)** - Frequently asked questions
- **[benchmark-orchestrator](.claude/skills/benchmark-orchestrator/SKILL.md)** - AI agent entry point: routes natural-language requests to the right benchmark skill (see also `.claude/skills/run-<benchmark>/`)

## Features

- **Multiple Execution Modes:** ADB/Serial, SSH
- **Device History Management:** Automatic tracking of up to 10 recent devices
- **Comprehensive Benchmarks:** CoreMark, Sysbench, Hackbench, Tiobench, UnixBench, GLMark2, and more
- **Automated Reporting:** Individual run reports, aggregated build analysis, dashboard generation
- **Regression Detection:** Automatic detection with root cause analysis (RCA)
- **Telemetry Collection:** Device metrics during benchmark execution
- **Excel Export:** Automated report generation for QA workflows

## Requirements

See [requirements.txt](requirements.txt) for Python dependencies.

## Usage Examples

```bash
# Run multiple benchmarks
python main.py -b hackbench,sysbench,coremark --ssh-connection

# Run specific tests only
python main.py -b sysbench -t sysbench_cpu_prime_single_test --ssh-connection

# Skip certain benchmarks
python main.py --skip unixbench,hackbench

# Store baseline for regression detection
python main.py --store-baseline --baseline-tag golden_build

# Connect to device by name (after first connection)
python main.py --host lemans -b sysbench
```

## Device History Management

AIBench automatically maintains a history of recently used devices:

**First time (with IP):**
```bash
python main.py --host 10.92.197.120
# Device details automatically saved to config/device_history.yaml
```

**Subsequent times (with device name):**
```bash
python main.py --host lemans
# Looks up IP, verifies reachability, connects automatically
```

## Configuration

### Credential Setup (Required for SSH)

**IMPORTANT:** Never commit credentials to git!

1. **Copy the template:**
   ```bash
   cp config/credentials.yaml.example config/credentials.yaml
   ```

2. **Edit credentials.yaml with your device details:**
   ```yaml
   ssh:
     host: "192.168.1.100"    # Your device IP
     port: 22
     username: "root"
     password: "your_password"
   ```

3. **Verify credentials.yaml is in .gitignore:**
   ```bash
   grep credentials.yaml ../.gitignore
   # Should show: aibench/config/credentials.yaml
   ```

**Alternative: Environment Variables**

Instead of credentials.yaml, you can use environment variables:
```bash
export SSH_HOST="192.168.1.100"
export SSH_USERNAME="root"
export SSH_PASSWORD="your_password"
python main.py --ssh-connection
```

### Benchmark Configuration

Edit `config/benchmarks.yaml` to configure:
- Active benchmarks
- Test parameters
- Device-specific thresholds
- Reporting options

## Output Structure

```
output/
├── <benchmark_name>/
│   └── build_<build_id>/
│       └── run_<timestamp>_<seq>/
│           ├── results.json
│           ├── report.html
│           ├── logs/
│           └── rca_report.json (if applicable)
└── reports/
    ├── index.html (dashboard)
    └── build_history.json
```

## Support

For issues or questions, refer to the [FAQ](FAQ.md) or contact the development team.

## License

BSD 3-Clause License. See [LICENSE](../LICENSE) for details.
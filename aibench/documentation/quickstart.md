# Benchmarks Suite - Quick Start Guide

**Estimated Reading Time: 5-7 minutes**

## Overview

The Benchmarks Suite is an enterprise-grade agentic AI orchestration framework for automated performance evaluation of embedded systems and devices. The framework leverages Large Language Model (LLM) integration to provide natural language interfaces for benchmark execution, regression detection, and root cause analysis.

**Key Architecture:** Users interact with the suite exclusively through LLM prompts (currently supporting Claude). The system utilizes skill-based orchestration files to translate natural language requests into automated benchmark workflows, eliminating the need for direct code execution or command-line expertise.

---

## System Architecture

### Interaction Model

1. **User Input:** Submit natural language requests to Claude
2. **Skill Orchestration:** Claude interprets requests using skill definition files
3. **Automated Execution:** Framework executes benchmarks on target devices
4. **Results Generation:** Comprehensive reports, dashboards, and analysis artifacts are automatically produced

### Prerequisites

- Target device accessible via SSH or Serial/ADB connection
- Claude LLM with repository access
- Python 3.8+ environment (managed automatically by the framework)

---

## Getting Started

### Initial Benchmark Execution

Submit the following prompt to Claude:

> **"run coremark over ssh"**

**Expected Behavior:**
- CoreMark CPU benchmark executes on the target device
- Execution time: approximately 1-2 minutes
- Results stored in `aibench/output/coremark/`
- Interactive dashboard generated at `aibench/output/reports/index.html`

**Result Access:**
Claude will provide the file system paths for HTML dashboards and detailed result artifacts.

---

## Standard Prompt Templates

### Performance Validation

**CPU Performance Verification:**
> "run coremark over ssh"

**Storage Subsystem Verification:**
> "run tiobench over ssh"

**GPU Performance Verification:**
> "run glmark2 over ssh"

### Comprehensive System Evaluation

**Full Benchmark Suite Execution:**
> "run all benchmarks over ssh"
> 
> **Note:** Execution time spans several hours due to mandatory 5-minute thermal stabilization intervals between benchmarks.

**Accelerated Full Suite (Thermal Stabilization Bypassed):**
> "run all benchmarks over ssh and bypass the gap"
> 
> **Caution:** Results may exhibit thermal variance. Recommended only for functional validation, not performance characterization.

### Regression Analysis

**Subsystem Regression Check:**
> "run sysbench over ssh"
> 
> Provides comprehensive coverage: CPU, Memory, Threading, Mutex, and File I/O subsystems.

**Baseline Establishment:**
> "run all benchmarks over ssh and store this as baseline"

**Baseline Comparison:**
> "run sysbench over ssh and compare against baseline"

### Statistical Confidence

**Multiple Execution Runs:**
> "run coremark 5 times over ssh"

**Trend Analysis (Requires ≥4 Historical Runs):**
> "run sysbench over ssh and analyze trends across all runs"

### Targeted Benchmark Execution

**Single Benchmark Specification:**
> "run only the default glmark2 test over ssh"

**Multiple Benchmark Selection:**
> "run sysbench and coremark over ssh"

**Benchmark Exclusion:**
> "run all benchmarks except unixbench and bw_mem over ssh"

**Sub-Test Specification:**
> "run only the sequential test of tiobench over ssh"

### Advanced Configuration

**Custom Iteration Control:**
> "run sysbench 3 times with 4 iterations per run over ssh"
> 
> Total executions: 3 runs × 4 iterations = 12 sub-test executions

**Targeted Sub-Test with Repetition:**
> "run sysbench fileio random mixed test 3 times with 4 iterations over ssh"

---

## Results and Reporting

### Automated Artifacts

The framework generates the following artifacts after each execution:

1. **Interactive HTML Dashboard** (`output/reports/index.html`)
   - Performance visualization with charts and graphs
   - Regression detection highlights
   - Historical trend analysis

2. **Excel Report** (`output/reports/benchmark_report_<build_id>_<timestamp>.xlsx`)
   - Device-specific tabular data
   - Statistical metrics: Mean, Min, Max, Standard Deviation, Coefficient of Variation
   - Compatible with QA_Data_Template.xlsx format

3. **Raw JSON Results** (`output/<benchmark>/build_<id>/run_<run>/results.json`)
   - Detailed metric data for each test execution

4. **Root Cause Analysis Reports** (`output/<benchmark>/build_<id>/run_<run>/rca_report.json`)
   - Automated regression analysis with diagnostic telemetry

### Intelligent Root Cause Analysis

The framework implements automated multi-tier Root Cause Analysis (RCA):

**Workflow:**
1. Initial benchmark execution without telemetry overhead (clean baseline)
2. Automated regression detection across runs, builds, and baselines
3. **Tier 1 Response:** Regressed benchmarks automatically re-execute with system telemetry (vmstat, dmesg, thermal sensors, CPU frequency)
4. **Tier 2 Response:** Inconclusive results trigger ftrace-enabled re-execution
5. **Report Generation:** Findings documented in structured RCA reports

**Note:** RCA activation is automatic upon regression detection. No explicit user request required.

---

## Best Practices

### Connection Configuration

**SSH Connection (Recommended):**
> "run coremark over ssh"

- Optimized connection establishment
- Direct device access
- Default configuration for all examples

**Serial/ADB Connection:**
> "run coremark over serial"

- Alternative when SSH is unavailable
- Extended initialization time
- Automatic ADB fallback

### Thermal Management

**Default Behavior:** 5-minute mandatory cooldown intervals between benchmarks ensure thermal stability and measurement accuracy.

**Bypass Option:** Include "bypass the gap" in prompts to skip cooldown intervals. Recommended only for functional validation where thermal variance is acceptable.

### Benchmark Duration Reference

| Benchmark | Typical Duration | Characteristics |
|-----------|------------------|-----------------|
| coremark | 1-2 minutes | Minimal execution time, suitable for rapid validation |
| sysbench | 5-10 minutes | Comprehensive single-benchmark coverage |
| tiobench | 3-5 minutes | Storage I/O bound |
| glmark2 | 5-10 minutes | GPU-bound, requires Wayland compositor |
| unixbench | 15-40 minutes | Most time-intensive single benchmark |
| **Full Suite** | **3-6 hours** | Complete system evaluation across all benchmarks with inter-benchmark stabilization periods |

---

## Use Case Examples

### Development Validation
> "run sysbench over ssh and compare against baseline to check if my code change caused any regression"

### Quality Assurance
> "run all benchmarks over ssh and generate the Excel report for the weekly quality review"

### Performance Characterization
> "run coremark 10 times over ssh to establish statistical confidence in the results"

### Diagnostic Analysis
> "run hackbench over ssh and show me the RCA report if there are any regressions"

---

## Troubleshooting

**Issue: "must be executed from aibench/ directory"**
- **Resolution:** Framework automatically handles working directory context. Retry the request if this message appears.

**Issue: "not found in configuration"**
- **Resolution:** Verify benchmark name spelling. Valid identifiers: coremark, sysbench, tiobench, hackbench, glmark2, coremark_pro, osbench, ramspeed, unixbench, bw_mem, lat_mem_rd, geekbench

**Issue: "Gap validation error"**
- **Resolution:** Previous benchmark execution occurred within the 5-minute cooldown window. Either wait for the interval to complete or include "bypass the gap" in your prompt.

**Issue: GLMark2 rendering failure**
- **Resolution:** Verify Wayland compositor is active on the target device and display environment is properly configured.

**Issue: Thermally inconsistent results**
- **Resolution:** Avoid "bypass the gap" for performance-critical measurements. Ensure mandatory cooldown intervals complete between benchmark executions.

---

## Additional Resources

- **Comprehensive FAQ:** `aibench/FAQ.md` - Detailed troubleshooting and advanced configuration
- **AI Agent Entry Point:** `aibench/.claude/skills/benchmark-orchestrator/SKILL.md` - Routes natural-language requests to the right benchmark skill
- **Benchmark-Specific Documentation:** `aibench/.claude/skills/` - Individual benchmark skill definitions

---

## Workflow Example

**Scenario:** Validating CPU performance regression in latest build

**User Request:**
> "I need to check if the latest build has any CPU performance regressions"

**Framework Response:**
- Executes sysbench over SSH
- Detects regression in CPU prime test
- Automatically re-runs with telemetry collection
- Generates RCA report identifying thermal throttling at 87°C

**Follow-up Request:**
> "Can you run it again but this time store it as baseline for future comparisons?"

**Framework Response:**
- Executes sysbench over SSH with baseline storage flag
- Saves aggregated statistics for future regression analysis

**Final Request:**
> "Now generate the Excel report for the QA team"

**Framework Response:**
- Provides path to auto-generated Excel report in `output/reports/`

---

## Recommended Workflow

For optimal efficiency, begin with targeted smoke tests (coremark, tiobench) before executing the full benchmark suite. This approach enables rapid identification of critical issues while minimizing execution time.

---

**Framework Version:** 1.0  
**Supported LLM:** Claude (Anthropic)  
**License:** See LICENSE file in repository root  
**Maintainer:** Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
# Guide: Adding a New Benchmark

This comprehensive guide provides step-by-step instructions for adding a new benchmark to the Unified Benchmark Harness. The harness uses a **Plugin Architecture** with automatic discovery, enabling you to add benchmarks without modifying core files.

**Estimated Time:** 2-4 hours for a simple benchmark

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Prerequisites](#prerequisites)
3. [Step-by-Step Implementation](#step-by-step-implementation)
4. [Testing & Validation](#testing--validation)
5. [Skill File Integration](#skill-file-integration)
6. [Troubleshooting](#troubleshooting)
7. [Complete Working Example](#complete-working-example)

---

## Architecture Overview

The system requires three primary components for each benchmark:

### 1. Benchmark Engine (`src/benchmark/<name>.py`)
- Inherits from `BenchmarkBase`
- Builds CLI commands for the target device
- Executes benchmarks via SSH/Serial connection
- Parses raw output into structured metrics
- Integrates with outlier detection

### 2. Outlier Detector (`src/reporting/outlier_detector_<name>.py`)
- Inherits from `OutlierDetectorBase`
- Analyzes parsed iterations for statistical anomalies
- Discards outlier runs based on configurable thresholds
- Returns clean dataset for reporting

### 3. Configuration (`config/benchmarks.yaml`)
- Defines execution parameters
- Specifies test variants and CLI flags
- Sets iteration counts and timeouts

### Auto-Discovery Mechanism

The system uses `BenchmarkRegistry` and `OutlierDetectorRegistry` to automatically discover components based on:
- **File naming conventions**: `<name>.py` and `outlier_detector_<name>.py`
- **Class exports**: `BENCHMARK_CLASS` and `OutlierDetector` variables
- **Inheritance**: Must inherit from base classes

---

## Prerequisites

Before starting, ensure you have:

1. **Target Device Access**: SSH or Serial/ADB connection configured
2. **Benchmark Tool Installed**: The benchmark executable must be present on the target device
3. **Python Environment**: Python 3.8+ with required dependencies
4. **Repository Access**: Clone and navigate to the benchmarks directory

**Verify Setup:**
```bash
cd benchmarks
python -c "from src.benchmark.registry import BenchmarkRegistry; print('Registry OK')"
```

---

## Step-by-Step Implementation

We'll use `coremark` as a reference example throughout this guide.

### Step 1: Add Configuration to `benchmarks.yaml`

Define your benchmark's execution parameters in the central configuration file.

**File:** `aibench/config/benchmarks.yaml`

**Required Fields:**
- `command`: Full path to the executable on target device
- `iterations`: Number of valid runs (warmup run added automatically)
- `test_params`: Dictionary of test variants with CLI flags
- `tests`: List of test variants to run by default

**Optional Fields:**
- `timeout`: Override default timeout (seconds)
- `category`: Grouping for reports (CPU, Memory, Storage, GPU, OS)
- `cooldown`: Delay between iterations (seconds)

**Example Configuration:**

```yaml
coremark:
  command: /usr/bin/coremark      # Full path to executable
  iterations: 3                   # Number of valid runs (+1 warmup)
  timeout: 300                    # Optional: override default timeout
  test_params:
    default:                      # Test variant name
      category: CPU               # Report grouping: CPU, Memory, Storage, GPU, OS
      --iterations: 0             # CLI flag (0 = use default)
      --verbose: 1                # CLI flag
  tests:
    - default                     # List of variants to run by default
```

**Multiple Test Variants Example:**

```yaml
sysbench:
  command: /usr/bin/sysbench
  iterations: 3
  test_params:
    cpu_single:
      category: CPU
      --test: cpu
      --cpu-max-prime: 20000
      --threads: 1
    cpu_multi:
      category: CPU
      --test: cpu
      --cpu-max-prime: 20000
      --threads: 8
    memory:
      category: Memory
      --test: memory
      --memory-total-size: 10G
  tests:
    - cpu_single
    - cpu_multi
    - memory
```

**Add to Active Benchmarks List:**

```yaml
active_benchmarks:
  - coremark
  - sysbench
  - your_new_benchmark  # Add your benchmark here
```

---

### Step 2: Create the Benchmark Engine

Create a Python module for your benchmark in the `src/benchmark/` directory.

**File:** `aibench/src/benchmark/<name>.py`

**Critical Requirements:**

1. ✅ **Inherit from `BenchmarkBase`**
2. ✅ **Implement `execute_lifecycle()` method**
3. ✅ **Export class as `BENCHMARK_CLASS`** (required for auto-discovery)
4. ✅ **Separate warmup iterations** (index 0) from analysis iterations
5. ✅ **Invoke outlier detector** for statistical validation
6. ✅ **Handle connection types** (SSH/Serial/ADB)

**Complete Template with Annotations:**

```python
"""
<name>.py - Benchmark engine for <Benchmark Name>

Author: Your Name <your.email@company.com>
"""

import re
import time
from pathlib import Path
from typing import Any, Dict, List
from src.benchmark.base import BenchmarkBase
from src.utils.logger import phase_logger
from src.reporting.outlier_registry import OutlierDetectorRegistry

class YourBenchmarkName(BenchmarkBase):
    """
    Benchmark engine for <Benchmark Name>.
    
    This class handles:
    - Command construction with CLI flags
    - Execution via SSH/Serial connection
    - Output parsing and metric extraction
    - Integration with outlier detection
    """
    
    def __init__(self, name: str, config: Dict[str, Any], run_dir: Path):
        """
        Initialize the benchmark engine.
        
        Args:
            name: Benchmark identifier (lowercase)
            config: Configuration from benchmarks.yaml
            run_dir: Output directory for this run
        """
        super().__init__(name, config, run_dir)
        
        # Extract configuration parameters
        self.command_base = self.config.get("command", "/usr/bin/your_benchmark")
        self.iterations = self.config.get("iterations", 3)
        self.timeout = self.config.get("timeout", 300)
        self.cooldown = self.config.get("cooldown", 5)
        self.tests_to_run = self.config.get("tests", ["default"])
        
        phase_logger.info(f"Initialized {name} with {self.iterations} iterations")
    
    def _build_command(self, test_name: str, params: Dict[str, Any]) -> str:
        """
        Construct the CLI command string for execution.
        
        Args:
            test_name: Name of the test variant
            params: Parameters from test_params in config
            
        Returns:
            Complete command string ready for execution
            
        Example:
            Input: {"--threads": 4, "--time": 60}
            Output: "/usr/bin/benchmark --threads 4 --time 60"
        """
        cmd_parts = [self.command_base]
        
        for key, value in params.items():
            # Skip metadata fields
            if key in ["category"]:
                continue
            
            # Handle boolean flags
            if isinstance(value, bool):
                if value:
                    cmd_parts.append(key)
            # Handle key-value pairs
            else:
                cmd_parts.extend([key, str(value)])
        
        command = " ".join(cmd_parts)
        phase_logger.debug(f"Built command: {command}")
        return command
    
    def _parse_output(self, output: str, test_name: str) -> Dict[str, float]:
        """
        Parse raw benchmark output to extract metrics.
        
        Args:
            output: Raw stdout/stderr from benchmark execution
            test_name: Name of the test variant (for context)
            
        Returns:
            Dictionary of metric_name -> value
            
        Example:
            Input: "Score: 12345.67 iterations/sec"
            Output: {"score": 12345.67}
        """
        metrics = {}
        
        try:
            # Example: Extract score using regex
            score_match = re.search(r'Score:\s+([\d.]+)', output)
            if score_match:
                metrics["score"] = float(score_match.group(1))
            else:
                phase_logger.warning(f"Could not parse score from output")
                metrics["score"] = 0.0
            
            # Add more metric extractions as needed
            # throughput_match = re.search(r'Throughput:\s+([\d.]+)', output)
            # if throughput_match:
            #     metrics["throughput"] = float(throughput_match.group(1))
            
        except Exception as e:
            phase_logger.error(f"Error parsing output: {e}")
            metrics["score"] = 0.0
        
        return metrics
    
    def execute_lifecycle(self, serial_executor, adb_manager) -> Dict[str, Any]:
        """
        Main execution lifecycle for the benchmark.
        
        This method:
        1. Iterates through all configured test variants
        2. Executes iterations + 1 warmup run
        3. Parses output and collects metrics
        4. Runs outlier detection on analysis iterations
        5. Returns structured results
        
        Args:
            serial_executor: SSH/Serial connection manager
            adb_manager: ADB connection manager (if needed)
            
        Returns:
            Dictionary with structure:
            {
                "metadata": {"benchmark": "name", "timestamp": "..."},
                "tests": {
                    "test_variant_1": {
                        "iterations": [...],
                        "metric_name": [clean_values]
                    }
                }
            }
        """
        phase_logger.info(f"Starting {self.name} benchmark lifecycle")
        
        results = {
            "metadata": {
                "benchmark": self.name,
                "total_iterations": self.iterations + 1  # +1 for warmup
            },
            "tests": {}
        }
        
        # Iterate through all test variants
        for test_id in self.tests_to_run:
            phase_logger.info(f"Running test variant: {test_id}")
            
            # Get test parameters
            test_params = self.config.get("test_params", {}).get(test_id, {})
            command = self._build_command(test_id, test_params)
            
            raw_iterations = []
            
            # Execute iterations + 1 warmup
            for iteration_num in range(1, self.iterations + 2):
                is_warmup = (iteration_num == 1)
                
                phase_logger.info(
                    f"Iteration {iteration_num}/{self.iterations + 1} "
                    f"{'(warmup)' if is_warmup else ''}"
                )
                
                try:
                    # Execute command on target device
                    output = serial_executor.execute_command(
                        command,
                        timeout_override=self.timeout
                    )
                    
                    # Parse metrics from output
                    metrics = self._parse_output(output, test_id)
                    
                    # Store iteration data
                    iteration_data = {
                        "iteration": iteration_num,
                        "is_warmup": is_warmup,
                        "is_outlier": False,  # Will be updated by detector
                        **metrics  # Unpack all metrics
                    }
                    
                    raw_iterations.append(iteration_data)
                    
                    phase_logger.info(f"Iteration {iteration_num} metrics: {metrics}")
                    
                except Exception as e:
                    phase_logger.error(f"Iteration {iteration_num} failed: {e}")
                    # Add failed iteration with zero metrics
                    raw_iterations.append({
                        "iteration": iteration_num,
                        "is_warmup": is_warmup,
                        "is_outlier": True,
                        "error": str(e),
                        "score": 0.0
                    })
                
                # Cooldown between iterations (skip after last iteration)
                if iteration_num < self.iterations + 1:
                    time.sleep(self.cooldown)
            
            # Run Outlier Detection on analysis iterations only
            analysis_iterations = [
                it for it in raw_iterations 
                if not it.get("is_warmup", False)
            ]
            
            phase_logger.info(f"Running outlier detection on {len(analysis_iterations)} iterations")
            
            try:
                detector = OutlierDetectorRegistry.get(self.name)
                detection_result = detector.run_detection(analysis_iterations)
                
                clean_iterations = detection_result.get("clean_iterations", analysis_iterations)
                discarded_indices = detection_result.get("discarded_indices", [])
                
                phase_logger.info(
                    f"Outlier detection: {len(clean_iterations)} clean, "
                    f"{len(discarded_indices)} discarded"
                )
                
                # Mark outliers in raw_iterations
                for idx in discarded_indices:
                    # Adjust index to account for warmup iteration
                    if idx + 1 < len(raw_iterations):
                        raw_iterations[idx + 1]["is_outlier"] = True
                
            except Exception as e:
                phase_logger.warning(f"Outlier detection failed: {e}, using all iterations")
                clean_iterations = analysis_iterations
            
            # Extract clean metric values for reporting
            # Assuming primary metric is "score" - adjust as needed
            clean_scores = [it.get("score", 0.0) for it in clean_iterations]
            
            # Store test results
            results["tests"][test_id] = {
                "iterations": raw_iterations,
                "score": clean_scores,  # Primary metric
                "category": test_params.get("category", "performance"),
                "outlier_detection": detection_result if 'detection_result' in locals() else {}
            }
        
        phase_logger.info(f"Completed {self.name} benchmark lifecycle")
        return results

# REQUIRED FOR AUTO-DISCOVERY
# This export enables the registry to find and load this benchmark
BENCHMARK_CLASS = YourBenchmarkName
```

**Key Implementation Notes:**

1. **Connection Handling**: The `serial_executor` parameter handles both SSH and Serial/ADB connections automatically
2. **Error Handling**: Always wrap execution in try-except blocks
3. **Logging**: Use `phase_logger` for consistent logging
4. **Warmup Runs**: Always execute `iterations + 1` total runs, marking the first as warmup
5. **Metric Names**: Use consistent metric names that match your outlier detector

---

### Step 3: Create the Outlier Detector

Create a Python module for outlier detection in the `src/reporting/` directory.

**File:** `aibench/src/reporting/outlier_detector_<name>.py`

**Critical Requirements:**

1. ✅ **File name must be** `outlier_detector_<name>.py`
2. ✅ **Inherit from `OutlierDetectorBase`**
3. ✅ **Implement `METRIC_THRESHOLDS` property**
4. ✅ **Implement `run_detection()` method**
5. ✅ **Export class as `OutlierDetector`** (required for auto-discovery)

**Complete Template with Annotations:**

```python
"""
outlier_detector_<name>.py - Outlier detection for <Benchmark Name>

Author: Your Name <your.email@company.com>
"""

import copy
from typing import Any, Dict, List
from src.reporting.outlier_detector_base import OutlierDetectorBase

class OutlierDetector(OutlierDetectorBase):
    """
    Outlier detector for <Benchmark Name>.
    
    Implements statistical methods to identify and discard anomalous
    benchmark iterations based on configurable thresholds.
    """
    
    @property
    def METRIC_THRESHOLDS(self) -> Dict[str, Dict[str, float]]:
        """
        Define thresholds for each metric.
        
        Returns:
            Dictionary mapping metric names to threshold configurations:
            {
                "metric_name": {
                    "pct": float,      # Median percentage method threshold
                    "iqr_mult": float, # IQR multiplier for outlier detection
                    "mad_z": float     # MAD Z-score threshold
                }
            }
        
        Threshold Guidelines:
        - pct: 0.05 = 5% deviation from median (strict)
        - iqr_mult: 1.5 = standard outlier, 3.0 = extreme outlier
        - mad_z: 2.5 = moderate, 3.0 = strict
        """
        return {
            "score": {
                "pct": 0.05,      # 5% deviation from median
                "iqr_mult": 1.5,  # Standard IQR multiplier
                "mad_z": 2.5      # Moderate MAD Z-score
            },
            # Add more metrics as needed
            # "throughput": {
            #     "pct": 0.10,
            #     "iqr_mult": 2.0,
            #     "mad_z": 3.0
            # }
        }
    
    def run_detection(
        self, 
        iterations: List[Dict[str, Any]], 
        **kwargs
    ) -> Dict[str, Any]:
        """
        Run outlier detection on benchmark iterations.
        
        Args:
            iterations: List of iteration dictionaries with metrics
            **kwargs: Additional parameters (unused, for future extension)
            
        Returns:
            Dictionary with structure:
            {
                "status": str,              # "VALID", "UNSTABLE", or "FAILED"
                "clean_iterations": list,   # Iterations without outliers
                "discarded_indices": list,  # Indices of outlier iterations
                "detection_method": str,    # Method used: "median_pct", "iqr", "mad"
                "statistics": dict          # Optional: statistical summary
            }
        """
        # Create working copy to avoid modifying input
        working_iterations = copy.deepcopy(iterations)
        
        # Determine detection method based on sample size
        sample_size = len(working_iterations)
        
        if sample_size < 3:
            # Too few samples for statistical analysis
            return {
                "status": "INSUFFICIENT_DATA",
                "clean_iterations": working_iterations,
                "discarded_indices": [],
                "detection_method": "none",
                "message": f"Only {sample_size} iterations, skipping outlier detection"
            }
        
        # Choose method based on sample size
        if sample_size <= 6:
            method = "median_pct"
            metric_keys = list(self.METRIC_THRESHOLDS.keys())
            flagged_indices, stats = self.median_pct_method(
                working_iterations, 
                metric_keys
            )
        else:
            method = "iqr"
            metric_keys = list(self.METRIC_THRESHOLDS.keys())
            flagged_indices, stats = self.iqr_method(
                working_iterations,
                metric_keys
            )
        
        # Filter clean iterations
        clean_iterations = [
            it for i, it in enumerate(working_iterations)
            if i not in flagged_indices
        ]
        
        # Determine status
        if len(flagged_indices) == 0:
            status = "VALID"
        elif len(flagged_indices) <= 1:
            status = "VALID"  # Single outlier is acceptable
        elif len(clean_iterations) >= 2:
            status = "UNSTABLE"  # Multiple outliers but enough clean data
        else:
            status = "FAILED"  # Too many outliers
        
        return {
            "status": status,
            "clean_iterations": clean_iterations,
            "discarded_indices": flagged_indices,
            "detection_method": method,
            "statistics": stats,
            "total_iterations": sample_size,
            "clean_count": len(clean_iterations),
            "outlier_count": len(flagged_indices)
        }

# REQUIRED FOR AUTO-DISCOVERY
# This export enables the registry to find and load this detector
OutlierDetector = OutlierDetector
```

**Available Detection Methods:**

The base class provides three statistical methods:

1. **`median_pct_method()`**: Best for small samples (≤6 iterations)
   - Flags values deviating >X% from median
   - Simple and robust for small datasets

2. **`iqr_method()`**: Best for larger samples (>6 iterations)
   - Uses Interquartile Range (IQR)
   - Standard statistical outlier detection

3. **`mad_method()`**: Alternative robust method
   - Uses Median Absolute Deviation (MAD)
   - Less sensitive to extreme outliers

---

### Step 4: Add HTML Report Template (Optional)

If you want custom visualization in the dashboard, add a rendering block.

**File:** `aibench/config/templates/individual_report.html`

Find the sequence of `{% if benchmark_name == "..." %}` blocks and add your own:

```html
{% if benchmark_name == "your_benchmark" %}
<div class="benchmark-section">
    <h2>Your Benchmark Results</h2>
    {% for test_id, test_data in tests.items() %}
    <div class="test-subsection">
        <h3>{{ test_id }}</h3>
        
        <!-- Display primary metric -->
        <div class="metric-display">
            <h4>Score</h4>
            <p>Mean: {{ "%.2f"|format(test_data.score|mean) }}</p>
            <p>StdDev: {{ "%.2f"|format(test_data.score|stdev) }}</p>
            <p>CV: {{ "%.2f"|format(test_data.score|cv) }}%</p>
        </div>
        
        <!-- Iteration details -->
        <table class="iterations-table">
            <thead>
                <tr>
                    <th>Iteration</th>
                    <th>Score</th>
                    <th>Status</th>
                </tr>
            </thead>
            <tbody>
                {% for iter in test_data.iterations %}
                <tr class="{{ 'warmup' if iter.is_warmup else ('outlier' if iter.is_outlier else 'valid') }}">
                    <td>{{ iter.iteration }}</td>
                    <td>{{ "%.2f"|format(iter.score) }}</td>
                    <td>
                        {% if iter.is_warmup %}Warmup
                        {% elif iter.is_outlier %}Outlier
                        {% else %}Valid
                        {% endif %}
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
    {% endfor %}
</div>
{% endif %}
```

**Note:** The dashboard will still work without custom templates, using default formatting.

---

### Step 5: Add Unit Tests

Create unit tests to validate your implementation.

**File:** `aibench/tests/test_<name>.py`

```python
"""
test_<name>.py - Unit tests for <Benchmark Name>

Author: Your Name <your.email@company.com>
"""

import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from src.benchmark.<name> import YourBenchmarkName

class TestYourBenchmark(unittest.TestCase):
    """Unit tests for YourBenchmarkName benchmark engine."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.config = {
            "command": "/usr/bin/test_benchmark",
            "iterations": 3,
            "timeout": 60,
            "test_params": {
                "default": {
                    "category": "CPU",
                    "--threads": 4
                }
            },
            "tests": ["default"]
        }
        self.run_dir = Path("/tmp/test_run")
        self.benchmark = YourBenchmarkName("test_benchmark", self.config, self.run_dir)
    
    def test_initialization(self):
        """Test benchmark initialization."""
        self.assertEqual(self.benchmark.name, "test_benchmark")
        self.assertEqual(self.benchmark.iterations, 3)
        self.assertEqual(self.benchmark.command_base, "/usr/bin/test_benchmark")
    
    def test_build_command(self):
        """Test command building."""
        params = {"--threads": 4, "--time": 60, "category": "CPU"}
        command = self.benchmark._build_command("default", params)
        
        self.assertIn("/usr/bin/test_benchmark", command)
        self.assertIn("--threads 4", command)
        self.assertIn("--time 60", command)
        self.assertNotIn("category", command)  # Should be filtered out
    
    def test_parse_output_valid(self):
        """Test parsing valid output."""
        output = "Score: 12345.67 iterations/sec\nCompleted successfully"
        metrics = self.benchmark._parse_output(output, "default")
        
        self.assertIn("score", metrics)
        self.assertEqual(metrics["score"], 12345.67)
    
    def test_parse_output_invalid(self):
        """Test parsing invalid output."""
        output = "Error: benchmark failed"
        metrics = self.benchmark._parse_output(output, "default")
        
        self.assertIn("score", metrics)
        self.assertEqual(metrics["score"], 0.0)
    
    @patch('src.benchmark.<name>.phase_logger')
    def test_execute_lifecycle(self, mock_logger):
        """Test full execution lifecycle."""
        # Mock serial executor
        mock_executor = Mock()
        mock_executor.execute_command.return_value = "Score: 1000.0 iterations/sec"
        
        # Mock ADB manager
        mock_adb = Mock()
        
        # Execute lifecycle
        results = self.benchmark.execute_lifecycle(mock_executor, mock_adb)
        
        # Verify structure
        self.assertIn("metadata", results)
        self.assertIn("tests", results)
        self.assertIn("default", results["tests"])
        
        # Verify iterations (3 + 1 warmup = 4 total)
        iterations = results["tests"]["default"]["iterations"]
        self.assertEqual(len(iterations), 4)
        self.assertTrue(iterations[0]["is_warmup"])
        self.assertFalse(iterations[1]["is_warmup"])

if __name__ == '__main__':
    unittest.main()
```

---

## Testing & Validation

### Verification Checklist

Before finalizing your benchmark, complete these verification steps:

#### 1. Auto-Discovery Test

Verify the registry can find your benchmark:

```bash
cd benchmarks
python -c "from src.benchmark.registry import BenchmarkRegistry; BenchmarkRegistry.auto_discover(); print(list(BenchmarkRegistry.list_all().keys()))"
```

**Expected Output:** Your benchmark name should appear in the list.

#### 2. Outlier Detector Discovery Test

Verify the outlier detector is registered:

```bash
python -c "from src.reporting.outlier_registry import OutlierDetectorRegistry; OutlierDetectorRegistry.auto_discover(); print(list(OutlierDetectorRegistry.list_all().keys()))"
```

**Expected Output:** Your benchmark name should appear in the list.

#### 3. Unit Tests

Run your unit tests:

```bash
python -m unittest tests/test_<name>.py -v
```

**Expected Output:** All tests should pass.

#### 4. Configuration Validation

Verify your YAML configuration is valid:

```bash
python -c "from src.utils.config_loader import load_config; config = load_config(); print(config.get('your_benchmark', 'NOT FOUND'))"
```

**Expected Output:** Your benchmark configuration should be displayed.

#### 5. Dry Run Test

Test command building without execution:

```python
from pathlib import Path
from src.benchmark.<name> import YourBenchmarkName

config = {
    "command": "/usr/bin/test",
    "iterations": 3,
    "test_params": {"default": {"--threads": 4}},
    "tests": ["default"]
}

benchmark = YourBenchmarkName("test", config, Path("/tmp"))
cmd = benchmark._build_command("default", config["test_params"]["default"])
print(f"Generated command: {cmd}")
```

#### 6. End-to-End Execution

Run the full benchmark on your target device:

```bash
cd benchmarks
python main.py --benchmark=your_benchmark --iterations=3 --ssh-connection
```

**Expected Output:**
- Benchmark executes successfully
- Results saved to `output/your_benchmark/`
- Dashboard updated at `output/reports/index.html`

---

## Skill File Integration

To enable LLM-based interaction with your benchmark, create a skill file.

**File:** `aibench/.claude/skills/run-<name>/SKILL.md`

```markdown
---
name: run-your-benchmark
description: Execute <Benchmark Name> performance benchmark on target device
category: Performance Benchmarking
---

# Run <Benchmark Name> Benchmark

**Author:** Your Name <your.email@company.com>

This skill enables execution of <Benchmark Name> benchmark for [brief description of what it measures].

## Quick Start Commands

| User Request | Command |
|---|---|
| Run default benchmark | `python main.py -b your_benchmark --ssh-connection` |
| Run with 5 iterations | `python main.py -b your_benchmark -r 5 --ssh-connection` |
| Run specific test variant | `python main.py -b your_benchmark -t variant_name --ssh-connection` |

## What This Benchmark Measures

- **Primary Metric:** [e.g., CPU performance, memory bandwidth]
- **Test Duration:** [e.g., 2-3 minutes per iteration]
- **Resource Impact:** [e.g., CPU-intensive, memory-bound]

## Available Test Variants

### default
- **Description:** [What this variant tests]
- **Typical Duration:** [Time estimate]
- **Command:** `python main.py -b your_benchmark -t default --ssh-connection`

## Interpreting Results

- **Score:** [What the score represents, higher/lower is better]
- **Typical Range:** [Expected values for reference hardware]
- **Regression Threshold:** [What constitutes a performance regression]

## Common Issues

**Issue:** [Common problem]
- **Cause:** [Why it happens]
- **Fix:** [How to resolve]

## Integration Notes

- **Outlier Detection:** Uses [method] with [threshold] threshold
- **Warmup Runs:** 1 warmup iteration automatically added
- **Cooldown:** [X] seconds between iterations
```

---

## Troubleshooting

### Common Issues and Solutions

#### Issue: Benchmark Not Discovered

**Symptoms:**
```
ValueError: Benchmark 'your_benchmark' is not supported
```

**Causes & Fixes:**

1. **Missing `BENCHMARK_CLASS` export**
   - **Fix:** Add `BENCHMARK_CLASS = YourBenchmarkName` at the end of your benchmark file

2. **File naming mismatch**
   - **Fix:** Ensure file is named `<name>.py` and matches the name in `benchmarks.yaml`

3. **Not inheriting from `BenchmarkBase`**
   - **Fix:** Change class definition to `class YourBenchmark(BenchmarkBase):`

4. **Registry not discovering**
   - **Fix:** Run `BenchmarkRegistry.auto_discover()` before accessing

#### Issue: Outlier Detector Not Found

**Symptoms:**
```
KeyError: 'your_benchmark' in OutlierDetectorRegistry
```

**Causes & Fixes:**

1. **Missing `OutlierDetector` export**
   - **Fix:** Add `OutlierDetector = OutlierDetector` at the end of your detector file

2. **File naming mismatch**
   - **Fix:** Ensure file is named `outlier_detector_<name>.py`

3. **Not inheriting from `OutlierDetectorBase`**
   - **Fix:** Change class definition to `class OutlierDetector(OutlierDetectorBase):`

#### Issue: Parsing Failures

**Symptoms:**
- All metrics return 0.0
- Warnings about parsing failures in logs

**Causes & Fixes:**

1. **Regex pattern doesn't match output**
   - **Fix:** Test your regex against actual benchmark output
   - **Debug:** Print raw output to see actual format

2. **Output format changed**
   - **Fix:** Update parsing logic to handle new format

3. **Benchmark failed to execute**
   - **Fix:** Check benchmark is installed on target device
   - **Fix:** Verify command path is correct

#### Issue: Connection Failures

**Symptoms:**
- Timeout errors
- "Connection refused" messages

**Causes & Fixes:**

1. **SSH not configured**
   - **Fix:** Verify SSH access: `ssh user@target_ip`
   - **Fix:** Check SSH keys are set up

2. **Serial port issues**
   - **Fix:** Verify port in `benchmarks.yaml` (e.g., `COM7`, `/dev/ttyUSB0`)
   - **Fix:** Check baud rate matches device

3. **Firewall blocking**
   - **Fix:** Allow SSH port (22) through firewall

#### Issue: Outlier Detection Too Aggressive

**Symptoms:**
- Most iterations flagged as outliers
- "UNSTABLE" or "FAILED" status

**Causes & Fixes:**

1. **Thresholds too strict**
   - **Fix:** Increase threshold values in `METRIC_THRESHOLDS`
   - **Example:** Change `pct: 0.05` to `pct: 0.10`

2. **High variance in benchmark**
   - **Fix:** Increase cooldown time between iterations
   - **Fix:** Ensure device is thermally stable

3. **Wrong detection method**
   - **Fix:** Use `median_pct` for small samples, `iqr` for larger

---

## Complete Working Example

Here's a minimal but complete "Hello World" benchmark for reference:

### File: `src/benchmark/hello_benchmark.py`

```python
"""
hello_benchmark.py - Minimal example benchmark

Author: Example <example@company.com>
"""

import re
import time
from pathlib import Path
from typing import Any, Dict
from src.benchmark.base import BenchmarkBase
from src.utils.logger import phase_logger
from src.reporting.outlier_registry import OutlierDetectorRegistry

class HelloBenchmark(BenchmarkBase):
    """Minimal example benchmark that echoes a message."""
    
    def __init__(self, name: str, config: Dict[str, Any], run_dir: Path):
        super().__init__(name, config, run_dir)
        self.command_base = self.config.get("command", "echo")
        self.iterations = self.config.get("iterations", 3)
        self.tests_to_run = self.config.get("tests", ["default"])
    
    def _build_command(self, test_name: str, params: Dict[str, Any]) -> str:
        message = params.get("--message", "Hello World")
        return f'{self.command_base} "{message}"'
    
    def _parse_output(self, output: str, test_name: str) -> Dict[str, float]:
        # Count characters as our "score"
        score = float(len(output.strip()))
        return {"score": score}
    
    def execute_lifecycle(self, serial_executor, adb_manager) -> Dict[str, Any]:
        results = {"metadata": {"benchmark": self.name}, "tests": {}}
        
        for test_id in self.tests_to_run:
            test_params = self.config.get("test_params", {}).get(test_id, {})
            command = self._build_command(test_id, test_params)
            raw_iterations = []
            
            for i in range(1, self.iterations + 2):
                is_warmup = (i == 1)
                output = serial_executor.execute_command(command, timeout_override=10)
                metrics = self._parse_output(output, test_id)
                
                raw_iterations.append({
                    "iteration": i,
                    "is_warmup": is_warmup,
                    "is_outlier": False,
                    **metrics
                })
                
                time.sleep(1)
            
            analysis_iters = [it for it in raw_iterations if not it.get("is_warmup")]
            
            try:
                detector = OutlierDetectorRegistry.get(self.name)
                detection = detector.run_detection(analysis_iters)
                clean_iters = detection.get("clean_iterations", analysis_iters)
            except:
                clean_iters = analysis_iters
            
            results["tests"][test_id] = {
                "iterations": raw_iterations,
                "score": [it.get("score", 0.0) for it in clean_iters],
                "category": test_params.get("category", "test")
            }
        
        return results

BENCHMARK_CLASS = HelloBenchmark
```

### File: `src/reporting/outlier_detector_hello_benchmark.py`

```python
"""
outlier_detector_hello_benchmark.py - Outlier detector for hello benchmark

Author: Example <example@company.com>
"""

import copy
from typing import Any, Dict, List
from src.reporting.outlier_detector_base import OutlierDetectorBase

class OutlierDetector(OutlierDetectorBase):
    
    @property
    def METRIC_THRESHOLDS(self) -> Dict[str, Dict[str, float]]:
        return {
            "score": {"pct": 0.10, "iqr_mult": 1.5, "mad_z": 2.5}
        }
    
    def run_detection(self, iterations: List[Dict[str, Any]], **kwargs) -> Dict[str, Any]:
        working = copy.deepcopy(iterations)
        
        if len(working) < 3:
            return {
                "status": "INSUFFICIENT_DATA",
                "clean_iterations": working,
                "discarded_indices": [],
                "detection_method": "none"
            }
        
        method = "median_pct" if len(working) <= 6 else "iqr"
        
        if method == "median_pct":
            flagged, stats = self.median_pct_method(working, ["score"])
        else:
            flagged, stats = self.iqr_method(working, ["score"])
        
        clean = [it for i, it in enumerate(working) if i not in flagged]
        
        return {
            "status": "VALID" if len(flagged) <= 1 else "UNSTABLE",
            "clean_iterations": clean,
            "discarded_indices": flagged,
            "detection_method": method,
            "statistics": stats
        }

OutlierDetector = OutlierDetector
```

### File: `config/benchmarks.yaml` (add this section)

```yaml
hello_benchmark:
  command: echo
  iterations: 3
  test_params:
    default:
      category: test
      --message: "Hello from benchmark"
  tests:
    - default
```

### Test It

```bash
cd benchmarks
python main.py -b hello_benchmark --ssh-connection
```

---

## FAQ

**Q: My benchmark doesn't have a concept of "warm-up" runs. Do I still need them?**

A: Yes. The harness relies on warm-up runs to prime device caching layers and ensure consistent measurements. Always execute `iterations + 1` loops, mark index 0 with `is_warmup: True`, and exclude it from outlier detection.

**Q: My benchmark produces multiple metrics. How do I configure outlier detection for all of them?**

A: Add all metrics to the `METRIC_THRESHOLDS` dictionary in your outlier detector. The base class methods accept a list of metric keys and will flag an iteration if *any* metric breaches its threshold.

Example:
```python
@property
def METRIC_THRESHOLDS(self) -> Dict[str, Dict[str, float]]:
    return {
        "throughput": {"pct": 0.05, "iqr_mult": 1.5, "mad_z": 2.5},
        "latency": {"pct": 0.10, "iqr_mult": 2.0, "mad_z": 3.0},
        "iops": {"pct": 0.05, "iqr_mult": 1.5, "mad_z": 2.5}
    }
```

**Q: How do I handle benchmarks with sub-tests (like sysbench)?**

A: Define multiple test variants in `test_params` and list them in the `tests` array. Each variant will be executed independently with its own outlier detection.

**Q: Can I skip outlier detection?**

A: Not recommended, but you can create a pass-through detector that returns all iterations as clean. However, this may affect result quality and regression detection accuracy.

**Q: How do I integrate with the RCA (Root Cause Analysis) system?**

A: RCA integration is automatic. Ensure your benchmark returns proper metric names and categories. The RCA system will automatically collect telemetry if regressions are detected.

**Q: My benchmark takes a long time. How do I adjust timeouts?**

A: Add a `timeout` field to your benchmark configuration in `benchmarks.yaml`:
```yaml
your_benchmark:
  command: /usr/bin/long_benchmark
  timeout: 600  # 10 minutes
  iterations: 3
```

**Q: How do I test my benchmark locally without a target device?**

A: Create a mock executor that returns sample output:
```python
class MockExecutor:
    def execute_command(self, cmd, timeout_override=0):
        return "Score: 1000.0 iterations/sec"

benchmark = YourBenchmark("test", config, Path("/tmp"))
results = benchmark.execute_lifecycle(MockExecutor(), None)
```

---

## Summary Checklist

Before submitting your new benchmark, verify:

- [ ] Configuration added to `benchmarks.yaml`
- [ ] Benchmark engine created in `src/benchmark/<name>.py`
- [ ] Inherits from `BenchmarkBase`
- [ ] Exports `BENCHMARK_CLASS`
- [ ] Implements `execute_lifecycle()`
- [ ] Handles warmup iterations correctly
- [ ] Outlier detector created in `src/reporting/outlier_detector_<name>.py`
- [ ] Inherits from `OutlierDetectorBase`
- [ ] Exports `OutlierDetector`
- [ ] Implements `METRIC_THRESHOLDS` and `run_detection()`
- [ ] Unit tests created and passing
- [ ] Auto-discovery verified
- [ ] End-to-end execution successful
- [ ] Skill file created (optional but recommended)
- [ ] Documentation updated

---

**Need Help?**

- Review existing benchmarks in `src/benchmark/` for reference
- Check `src/benchmark/base.py` for base class interface
- See `src/reporting/outlier_detector_base.py` for detection methods
- Consult `FAQ.md` for common issues
- Contact: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
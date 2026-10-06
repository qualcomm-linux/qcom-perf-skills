# Code Patterns to Detect

This document defines the code patterns that the update-doc skill should detect and document.

## 1. Benchmark Implementations

### Pattern
```python
class XyzBenchmark(BenchmarkBase):
    """Benchmark docstring"""
    
    def setup(self, serial_executor, adb_manager):
        """Setup phase"""
        pass
    
    def run(self, serial_executor, adb_manager):
        """Run phase"""
        pass
    
    def teardown(self, serial_executor, adb_manager):
        """Teardown phase"""
        pass
```

### Extract
- Class name (e.g., `CoremarkBenchmark`)
- Docstring
- Methods: `setup()`, `run()`, `teardown()`
- Method signatures and parameters
- Return types

### Update Section
- Section 5.2.X (Benchmark Implementations)
- Add new subsection for new benchmark
- Update existing subsection if benchmark modified

### Example Documentation
```markdown
#### 5.2.X New Benchmark

**Purpose**: [Extract from docstring]

**Category**: [Extract from config]

**Implementation**: `src/benchmark/new_benchmark.py`

**Metrics Extracted:**
- [List metrics from run() method]

**Command Example:**
```bash
[Extract command from code]
```
```

## 2. Outlier Detection Methods

### Pattern
```python
class OutlierDetectorXyz(OutlierDetectorBase):
    """Outlier detector docstring"""
    
    @property
    def METRIC_THRESHOLDS(self):
        return {
            "metric_name": {
                "pct": 0.05,
                "iqr_mult": 1.5,
                "mad_z": 2.5
            }
        }
    
    def run_detection(self, iterations, **kwargs):
        """Detection logic"""
        pass
```

### Extract
- Class name
- Docstring
- Metric thresholds
- Detection methods used

### Update Section
- Section 6.2 (Benchmark-Specific Outlier Detectors)
- Add new subsection for new detector

## 3. Statistical Methods (Regression Detection)

### Pattern
```python
def _detect_xyz(self, baseline_data, current_data):
    """
    Detect regression using XYZ method
    
    Args:
        baseline_data: Baseline metric values
        current_data: Current metric values
        
    Returns:
        Dict with detection results or None
    """
    # Implementation
    pass
```

### Extract
- Method name
- Docstring
- Parameters and types
- Return type
- Algorithm description

### Update Section
- Section 8.2 (Statistical Methods Used)
- Add new subsection for new method

### Example Documentation
```markdown
#### 8.2.X New Statistical Method

**Purpose**: [Extract from docstring]

**Formula:**
```
[Extract from code comments or docstring]
```

**Implementation:**
```python
[Code snippet]
```

**Threshold**: [Extract from code]

**Industry Justification**: [Manual - preserve existing]
```

## 4. RCA Categories

### Pattern
```python
def detect_xyz_anomaly(self, telemetry):
    """Detect XYZ anomaly"""
    if len(telemetry["xyz_events"]) > 0:
        return {
            "cause": "XYZ Issue",
            "confidence": 85,
            "evidence": telemetry["xyz_events"]
        }
    return None
```

### Extract
- Method name
- Anomaly type
- Confidence score
- Evidence sources

### Update Section
- Section 9.2 (Hierarchical Anomaly Evaluation)
- Add new category subsection

## 5. Configuration Parameters

### Pattern (YAML)
```yaml
telemetry_thresholds:
  devices:
    IQ-9075:
      thermal:
        cpu_high_temp_c: 85
        cpu_throttle_temp_c: 95
```

### Extract
- Device name
- Parameter hierarchy
- Parameter values
- Parameter types

### Update Section
- Section 11.2 (Device-Specific Customization)
- Update device profile tables

## 6. Execution Phases

### Pattern
```python
def execute_phase_xyz(self):
    """Execute XYZ phase"""
    # Phase 1: Initialize
    # Phase 2: Execute
    # Phase 3: Cleanup
    pass
```

### Extract
- Phase name
- Phase steps
- Error handling
- Integration points

### Update Section
- Section 12 (Control Flow & Execution)
- Update phase documentation

## Detection Priority

1. **High Priority** (Always document):
   - New benchmark classes
   - New statistical methods
   - New RCA categories
   - Configuration changes

2. **Medium Priority** (Document if significant):
   - Method signature changes
   - Threshold modifications
   - Algorithm updates

3. **Low Priority** (Document if requested):
   - Bug fixes
   - Refactoring
   - Code cleanup

## Special Markers

### Manual Documentation Marker
```markdown
<!-- MANUAL: This section is manually maintained -->
Content here will be preserved during auto-updates
<!-- /MANUAL -->
```

### Auto-Generated Marker
```markdown
<!-- AUTO: Generated from src/benchmark/coremark.py -->
Content here will be auto-updated
<!-- /AUTO -->
```

## Extraction Rules

### Rule 1: Preserve Context
- Include surrounding code for context
- Extract complete function/class definitions
- Include docstrings and comments

### Rule 2: Format Consistently
- Use consistent markdown formatting
- Follow existing section structure
- Maintain code block syntax highlighting

### Rule 3: Link References
- Cross-reference related sections
- Link to source files
- Reference industry standards

### Rule 4: Version Tracking
- Track which commit introduced changes
- Note deprecations
- Document migration paths

## Example: Full Extraction

### Input (Python Code)
```python
class NewBenchmark(BenchmarkBase):
    """
    New benchmark for XYZ performance testing
    
    Measures: throughput, latency, resource usage
    Category: CPU
    """
    
    def run(self, serial_executor, adb_manager):
        """Execute benchmark and collect metrics"""
        output = serial_executor.execute_command("/usr/bin/new_benchmark")
        return self._parse_output(output)
```

### Output (Markdown Documentation)
```markdown
#### 5.2.12 NewBenchmark

**Purpose**: New benchmark for XYZ performance testing

**Category**: CPU

**Implementation**: `src/benchmark/new_benchmark.py`

**Metrics Extracted:**
- Throughput
- Latency
- Resource usage

**Execution:**
```python
def run(self, serial_executor, adb_manager):
    """Execute benchmark and collect metrics"""
    output = serial_executor.execute_command("/usr/bin/new_benchmark")
    return self._parse_output(output)
```

**Command Example:**
```bash
/usr/bin/new_benchmark
```
```

## Notes

- Always preserve manual documentation sections
- Update table of contents after adding new sections
- Validate markdown syntax before writing
- Test cross-references after updates
- Keep code examples concise and relevant
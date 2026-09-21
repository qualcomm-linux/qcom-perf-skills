# anomaly-rca

Internal component. Ingests findings from one or more memory analysis components
and produces a ranked `RCAReport` JSON with correlated anomalies, confidence
scores, and recommended actions.

See [references/REFERENCE.md](references/REFERENCE.md) for the full `RCAReport`
schema, correlation patterns, and confidence scoring methodology.

## How to Run

```bash
python internal/anomaly-rca/scripts/analyze_rca.py \
    --map-report          reports/memory_map_report.json \
    --carveout-report     reports/carveout_validation_report.json \
    --comparison-report   reports/snapshot_comparison_report.json \
    --kernel-diff         reports/kernel_diff_report.json \
    --userspace-diff      reports/userspace_diff_report.json \
    --output-dir          reports/
```

All `--*-report` flags are optional. Pass whichever reports are available.
Handles any combination — including a single report.

---

## Single-Snapshot Mode (no baseline required)

When only `--map-report` is provided:

- Analyzes absolute memory values against built-in thresholds
- Flags high absolute memory consumers (e.g. Slab > 1 GB, single process PSS > 500 MB)
- Reports `overall_health` based on available evidence only
- Does **not** report GROWING/SHRINKING trends (no baseline to compare against)

```bash
python internal/anomaly-rca/scripts/analyze_rca.py \
    --map-report      memory_map_report.json \
    --output-dir      reports/
```

## Two-Snapshot Mode (baseline required)

When comparison, kernel-diff, or userspace-diff reports are also provided:

- Correlates growing trends with absolute anomalies
- Generates higher-confidence hypotheses (more evidence sources)
- Reports GROWING/SHRINKING trends and leak patterns

---

## Inputs

| Flag | Type | Required | Description |
|---|---|---|---|
| `--map-report` | path | No | `MemoryMapReport` JSON from `internal/memory-map`. |
| `--carveout-report` | path | No | `CarveoutValidationReport` JSON from `internal/nhlos-carveout-validation` (informational). |
| `--comparison-report` | path | No | `SnapshotComparisonReport` JSON from `internal/snapshot-comparison`. |
| `--kernel-diff` | path | No | `KernelDiffReport` JSON from `internal/kernel-diff`. |
| `--userspace-diff` | path | No | `UserspaceDiffReport` JSON from `internal/userspace-diff`. |
| `--output-dir` | path | No | Directory for reports (default: `.`). |

---

## Outputs

| File | Description |
|---|---|
| `rca_report.json` | Structured `RCAReport` JSON with ranked anomalies. |
| `rca_report.html` | HTML report with anomaly cards, evidence, and recommendations. |
| `rca_report.txt` | Plain-text report. |

---

## Correlation Patterns

| Pattern | Hypothesis | Confidence Boost |
|---|---|---|
| Single slab > 100% growth | Targeted kernel subsystem leak | +0.30 |
| Slab growing + high pgscan_kswapd | Kernel memory leak under pressure | +0.20 |
| DMA-BUF + KGSL both growing + single process PSS growing | Graphics/media process leak | +0.25 |
| Buddy fragmentation high + OOM events | Memory fragmentation causing allocation failures | +0.35 |
| CMA used > 80% + DMA-BUF growing | CMA exhaustion risk for contiguous allocations | +0.30 |
| oom_kill > 0 + MemFree < 5% MemTotal | Active OOM condition | +0.50 |

---

## Dependencies

- Input: report JSONs from `internal/memory-map`, `internal/nhlos-carveout-validation`,
  `internal/snapshot-comparison`, `internal/kernel-diff`, `internal/userspace-diff`
- Output consumed by: `internal/report-generation`
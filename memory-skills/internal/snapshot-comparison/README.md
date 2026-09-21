# snapshot-comparison

Internal component. Compares two `MemorySnapshot` JSON files and produces a
`SnapshotComparisonReport` JSON plus human-readable reports.

See [references/REFERENCE.md](references/REFERENCE.md) for the full output
schema and delta calculation methodology.

## How to Run

```bash
python internal/snapshot-comparison/scripts/compare_snapshots.py \
    --current   current/snapshot.json \
    --reference baseline/snapshot.json \
    --output-dir reports/
```

---

## Inputs

| Flag | Type | Required | Description |
|---|---|---|---|
| `--current` | path | Yes | Current `snapshot.json` (the state to analyze). |
| `--reference` | path | Yes | Reference `snapshot.json` (baseline to compare against). |
| `--output-dir` | path | No | Directory for reports (default: `.`). |
| `--threshold-pct` | float | No | Delta % threshold for flagging (default: 5.0). |
| `--threshold-mb` | float | No | Absolute delta MB threshold for flagging (default: 50.0). |

---

## Outputs

| File | Description |
|---|---|
| `snapshot_comparison_report.json` | Structured `SnapshotComparisonReport` JSON. |
| `snapshot_comparison_report.html` | Color-coded HTML comparison table. |
| `snapshot_comparison_report.txt` | Plain-text comparison table. |
| `snapshot_comparison_report.xlsx` | Excel comparison workbook. |

---

## Delta Calculation

```
delta_kb  = current_kb - reference_kb
delta_pct = (delta_kb / reference_kb) x 100   (if reference_kb > 0)
trend     = GROWING   if delta_pct > +threshold_pct
            SHRINKING if delta_pct < -threshold_pct
            STABLE    otherwise
```

---

## Dependencies

- Input: `snapshot.json` from `internal/data-collection`
- Output consumed by: `internal/kernel-diff`, `internal/userspace-diff`, `internal/anomaly-rca`
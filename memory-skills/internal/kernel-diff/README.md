# kernel-diff

Internal component. Analyzes kernel memory changes between two `MemorySnapshot`
files. Produces a `KernelDiffReport` JSON with per-slab, per-vmalloc,
per-module, and buddy fragmentation deltas.

See [common/schema/kernel-diff-report.schema.json](../common/schema/kernel-diff-report.schema.json)
for the full output schema.

## How to Run

```bash
python internal/kernel-diff/scripts/analyze_kernel_diff.py \
    --current   current/snapshot.json \
    --reference baseline/snapshot.json \
    --output-dir reports/
```

---

## Inputs

| Flag | Type | Required | Description |
|---|---|---|---|
| `--current` | path | Yes | Current `snapshot.json`. |
| `--reference` | path | Yes | Reference `snapshot.json`. |
| `--output-dir` | path | No | Directory for reports (default: `.`). |
| `--slab-growth-pct` | float | No | Slab growth % threshold for flagging (default: 100.0). |
| `--slab-growth-mb` | float | No | Slab absolute growth MB threshold (default: 50.0). |

---

## Outputs

| File | Description |
|---|---|
| `kernel_diff_report.json` | Structured `KernelDiffReport` JSON. |
| `kernel_diff_report.html` | HTML report with sortable slab/vmalloc tables. |
| `kernel_diff_report.txt` | Plain-text report. |
| `kernel_diff_report.xlsx` | Excel workbook with Slab Diff, Vmalloc Diff, Module Diff, Buddy sheets. |

---

## Leak Detection Heuristics

A slab is flagged as a potential leak when:
- Growth > `--slab-growth-pct` (default 100%) AND absolute growth > `--slab-growth-mb` (default 50 MB)
- OR: growth > 500% regardless of absolute size

A vmstat pattern is flagged as memory pressure when:
- `pgscan_kswapd` delta > 10,000 (active reclaim)
- `oom_kill` delta > 0 (OOM events occurred)

## Buddy Fragmentation Index

```
fragmentation_index = 1 - (sum(count x 2^order) / total_free_pages)
```

Range: 0.0 (no fragmentation) to 1.0 (fully fragmented).
A delta > +0.1 between snapshots indicates increasing fragmentation.

---

## Dependencies

- Input: `snapshot.json` from `internal/data-collection`
- Output consumed by: `internal/anomaly-rca`
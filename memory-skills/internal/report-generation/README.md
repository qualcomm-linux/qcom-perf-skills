# report-generation

Internal component. Renders any memory analysis output JSON into HTML, TXT,
and/or Excel reports. Report templates are selected automatically based on the
report type embedded in the input JSON.

See [references/REFERENCE.md](references/REFERENCE.md) for supported report
types and template extension points.

## How to Run

### Single report

```bash
python internal/report-generation/scripts/generate_report.py \
    --input  reports/rca_report.json \
    --format html,txt,xlsx \
    --output-dir reports/
```

### Unified multi-section report

```bash
python internal/report-generation/scripts/generate_report.py \
    --input  reports/memory_map_report.json \
            reports/carveout_validation_report.json \
            reports/rca_report.json \
    --format html \
    --unified \
    --title  "Memory Analysis — QCS6490 Build 1234" \
    --output-dir reports/
```

---

## Inputs

| Flag | Type | Required | Description |
|---|---|---|---|
| `--input` | path(s) | Yes | One or more report JSON files. |
| `--format` | string | No | Comma-separated: `html`, `txt`, `xlsx` (default: `html,txt`). |
| `--output-dir` | path | No | Directory for output files (default: `.`). |
| `--unified` | flag | No | Combine all inputs into a single multi-section HTML report. |
| `--title` | string | No | Title for the unified report. |

---

## Outputs

| File | Description |
|---|---|
| `<report_name>.html` | Self-contained HTML report with color-coded tables and charts. |
| `<report_name>.txt` | Plain-text version. |
| `<report_name>.xlsx` | Excel workbook. |
| `unified_report.html` | Combined multi-section report (when `--unified` is used). |

---

## Supported Report Types

| Input JSON Type | Template Used |
|---|---|
| `MemoryMapReport` | Memory breakdown tables + bar charts |
| `CarveoutValidationReport` | Carveout layout table (name, base address, size) |
| `SnapshotComparisonReport` | Side-by-side delta table with trend indicators |
| `KernelDiffReport` | Slab diff, vmalloc diff, buddy fragmentation tables |
| `UserspaceDiffReport` | Process PSS diff, DMA-BUF diff, KGSL diff tables |
| `RCAReport` | Anomaly cards with evidence, hypothesis, and recommendations |

---

## Color Coding

| Color | Meaning |
|---|---|
| 🔴 Red background | Memory increased (current > baseline) or CRITICAL anomaly |
| 🟢 Green background | Memory decreased (current < baseline) or carveout FOUND |
| 🟡 Yellow/Orange | WARNING anomaly |
| ⚪ White | STABLE |

---

## Dependencies

- Input: report JSONs from any internal analysis component
- This is the final step in the analysis pipeline
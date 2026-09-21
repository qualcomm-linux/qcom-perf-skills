# nhlos-carveout-validation

Internal component. Parses NHLOS (Non-High Level OS) carve-out allocations
from device tree reserved-memory nodes and reports their layout and sizes.
Produces a `CarveoutValidationReport` JSON plus HTML, TXT, and Excel reports.

No external spec or IP-XACT file required — carveout data is parsed directly
from the device tree binaries collected during data collection.

## How to Run

```bash
python internal/nhlos-carveout-validation/scripts/validate.py \
    --dump mem_dump/ \
    --report-dir reports/
```

---

## Inputs

| Flag | Type | Required | Description |
|---|---|---|---|
| `--dump` / `-d` | path | Yes | Dump directory containing `reserved-memory/` binaries or `DMA_reservations.txt`. |
| `--report-dir` | path | No | Output directory for reports (default: `.`). |

### Supported Input Formats

| Format | Description |
|---|---|
| `reserved-memory/*.bin` | Device tree reserved-memory node binaries (memory-map skill format) |
| `DMA_reservations.txt` | Reference script format (name + base + size per line) |

---

## Outputs

| File | Description |
|---|---|
| `carveout_validation_report.json` | Structured `CarveoutValidationReport` JSON. |
| `nhlos_validation_report.html` | HTML report — open in browser. |
| `nhlos_validation_report.xlsx` | Excel workbook. |
| `nhlos_validation_report.txt` | Plain-text report. |

---

## Output Format

Each carveout entry in the JSON report contains:

| Field | Description |
|---|---|
| `name` | Carveout name (e.g. mpss, cdsp, hyp, tz) |
| `base_addr` | Base address (hex string) |
| `actual_size_kb` | Size in KB |
| `actual_size_mb` | Size in MB |
| `status` | Always `FOUND` (parsed from device tree) |

Summary fields:

| Field | Description |
|---|---|
| `found` | Number of carveouts found |
| `total_actual_mb` | Total carveout size in MB |

---

## Dependencies

- Input: `reserved-memory/` binaries from `internal/data-collection`
- Output consumed by: `internal/report-generation`
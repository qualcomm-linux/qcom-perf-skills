# memory-map

Internal component. Breaks down physical memory into **NHLOS** and **HLOS**
categories from a `MemorySnapshot` JSON. Produces a `MemoryMapReport` JSON
plus HTML, TXT, and Excel reports.

- **NHLOS** — memory reserved for modem, DSP, TrustZone and other subsystems (not visible to Linux)
- **HLOS** — memory managed by Linux (kernel + userspace + free)

## How to Run

### From a snapshot (primary mode)

```bash
python internal/memory-map/scripts/memory_map.py \
    --snapshot <snapshot.json> \
    --output-dir reports/
```

### Live pull (device connected)

```bash
python internal/memory-map/scripts/memory_map.py --serial <serial> --output mem_dump/
```

### Offline (existing dump directory)

```bash
python internal/memory-map/scripts/memory_map.py --no-pull --output mem_dump/
```

### Compare two dumps

```bash
python internal/memory-map/scripts/memory_map.py --compare <dump_dir_1> <dump_dir_2>
```

---

## Outputs

| File | Description |
|---|---|
| `memory_map_report.json` | Structured `MemoryMapReport` JSON — primary output. |
| `memory_report.html` | HTML report — open in any browser. |
| `memory_report.txt` | Plain-text report. |
| `memory_report.xlsx` | Excel workbook with 14 sheets. |
| `memory_compare.html` | HTML comparison (compare mode). |
| `memory_compare.xlsx` | Excel comparison (compare mode). |

---

## Dependencies

- Input: `snapshot.json` from `internal/data-collection`
- Output consumed by: `internal/anomaly-rca`, `internal/report-generation`
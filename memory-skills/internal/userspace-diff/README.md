# userspace-diff

Internal component. Analyzes userspace memory changes between two `MemorySnapshot`
files. Computes per-process PSS and RSS deltas, identifies new and exited
processes, analyzes DMA-BUF allocator changes (per allocator), and KGSL GPU
memory changes (per process). Flags processes with abnormal PSS growth as
potential userspace memory leaks.

See [common/schema/userspace-diff-report.schema.json](../common/schema/userspace-diff-report.schema.json)
for the full output schema.

## How to Run

```bash
python internal/userspace-diff/scripts/analyze_userspace_diff.py \
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
| `--pss-growth-pct` | float | No | PSS growth % threshold for flagging (default: 50.0). |
| `--pss-growth-mb` | float | No | PSS absolute growth MB threshold (default: 20.0). |

---

## Outputs

| File | Description |
|---|---|
| `userspace_diff_report.json` | Structured `UserspaceDiffReport` JSON. |
| `userspace_diff_report.html` | HTML report with sortable process and DMA-BUF tables. |
| `userspace_diff_report.txt` | Plain-text report. |
| `userspace_diff_report.xlsx` | Excel workbook with Process Diff, DMA-BUF Diff, KGSL Diff sheets. |

---

## Leak Detection Heuristics

A process is flagged as a potential leak when:
- PSS growth > `--pss-growth-pct` (default 50%) AND absolute growth > `--pss-growth-mb` (default 20 MB)

Common Qualcomm leak patterns:
- `surfaceflinger` PSS growing — graphics buffer leak
- `mediaserver` / `media.codec` PSS growing — video/audio buffer leak
- `camera_server` PSS growing — camera HAL buffer leak
- DMA-BUF `qcom,adsp` allocator growing — ADSP buffer leak

---

## Dependencies

- Input: `snapshot.json` from `internal/data-collection`
- Output consumed by: `internal/anomaly-rca`
# data-collection

Internal component. Connects to a Linux device via ADB or SSH, pulls all
memory-related files, parses each source into a normalized structure, and
emits a `MemorySnapshot` JSON file. This snapshot is the common data contract
consumed by all downstream analysis components.

See [references/REFERENCE.md](references/REFERENCE.md) for the full
`MemorySnapshot` schema and parser specifications.

## How to Run

### Interactive (auto-detect transport)

```bash
python internal/data-collection/scripts/collect.py \
    --output mem_dump/ \
    --label "baseline"
```
The script auto-detects ADB devices and prompts for selection if needed,
or falls back to SSH (prompting for hostname, username, and password).

### Specify ADB device

```bash
python internal/data-collection/scripts/collect.py \
    --serial <serial> \
    --output mem_dump/ \
    --label "baseline"
```

### Specify SSH host

```bash
python internal/data-collection/scripts/collect.py \
    --host <ip_or_hostname> \
    --user <username> \
    --output mem_dump/ \
    --label "baseline"
```
Password is prompted interactively (not accepted on command line).

### Offline normalization (existing dump)

```bash
python internal/data-collection/scripts/collect.py \
    --no-pull \
    --output mem_dump/ \
    --label "baseline"
```

---

## Inputs

### ADB transport (USB or WiFi ADB)

| Flag | Type | Required | Default | Description |
|---|---|---|---|---|
| `--serial` / `-s` | string | No | interactive | ADB device serial (from `adb devices`). |
| `--output` / `-o` | string | No | `mem_dump` | Directory for raw files and snapshot.json. |
| `--label` | string | No | `snapshot` | Human-readable label (e.g. `baseline`, `after_test`). |
| `--no-pull` | flag | No | false | Skip collection; normalize files already in `--output`. |

### SSH transport (network access via paramiko)

| Flag | Type | Required | Default | Description |
|---|---|---|---|---|
| `--host` | string | No | interactive | SSH hostname or IP address. |
| `--user` | string | No | `root` | SSH username. |
| `--port` | int | No | `22` | SSH port. |
| `--key` | string | No | — | SSH private key file (password prompted if not provided). |
| `--output` / `-o` | string | No | `mem_dump` | Directory for raw files and snapshot.json. |
| `--label` | string | No | `snapshot` | Human-readable label. |

**Transport selection:**
- `--host` → SSH (password prompted interactively if no `--key`)
- `--serial` → ADB with specified serial
- neither → interactive: auto-detects ADB devices, prompts if multiple, falls back to SSH

**SSH dependency:** `pip install paramiko` (only required for SSH transport).

---

## Outputs

| File | Description |
|---|---|
| `<output>/snapshot.json` | Normalized `MemorySnapshot` JSON — primary output. |
| `<output>/meminfo.txt` | Raw `/proc/meminfo`. |
| `<output>/slabinfo.txt` | Raw `/proc/slabinfo`. |
| `<output>/vmstat.txt` | Raw `/proc/vmstat`. |
| `<output>/buddyinfo.txt` | Raw `/proc/buddyinfo`. |
| `<output>/zoneinfo.txt` | Raw `/proc/zoneinfo`. |
| `<output>/pagetypeinfo.txt` | Raw `/proc/pagetypeinfo`. |
| `<output>/dmabuf_bufinfo.txt` | Raw DMA-BUF info from debugfs. |
| `<output>/cma_used.txt` | Raw CMA usage from debugfs. |
| `<output>/kgsl_alloc.txt` | Raw KGSL GPU memory total. |
| `<output>/procrank.txt` | Raw procrank output (if available). |
| `<output>/reserved-memory/*.bin` | Raw DT reserved-memory node binaries. |
| `<output>/iomem.txt` | Raw `/proc/iomem`. |

---

## Error Handling

- Each source is collected independently; failure of one does not abort others.
- Unavailable sources are marked `available: false` in `snapshot.json`.
- Collection errors are appended to `snapshot.json["collection_errors"]`.
- Always produces a valid (possibly partial) snapshot.

---

## Consumed By

The `snapshot.json` produced by this component is consumed by:
- `internal/memory-map`
- `internal/nhlos-carveout-validation`
- `internal/snapshot-comparison`
- `internal/kernel-diff`
- `internal/userspace-diff`
- `internal/anomaly-rca`
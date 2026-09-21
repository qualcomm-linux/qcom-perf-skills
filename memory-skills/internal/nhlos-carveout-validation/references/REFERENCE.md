# NHLOS Carveout Reporter — Reference

Carveout parsing logic, supported input formats, and output schema.

---

## Supported Input Formats

### Format 1: `reserved-memory/*.bin` (memory-map skill format)

Binary files collected from the device tree reserved-memory nodes.
Each `.bin` file represents one reserved-memory node.

**Binary layout:** Repeated 16-byte records:
```
[addr: 8 bytes big-endian] [size: 8 bytes big-endian]
```

**Source on device:** `/proc/device-tree/reserved-memory/<node>/reg`

### Format 2: `DMA_reservations.txt` (reference script format)

Plain-text file with one carveout per line:
```
<name>  <high_base>  <low_base>  <high_size>  <low_size>
```
All address/size fields are 8-digit hex without `0x` prefix.

---

## Known Qualcomm NHLOS Carveout Names

| Carveout | Subsystem |
|---|---|
| `mpss` | Modem Processor SubSystem |
| `adsp` | Audio DSP |
| `cdsp` | Compute DSP |
| `cdsp-secure-heap` | CDSP Secure Heap |
| `trusted-apps` | TrustZone / QTEE |
| `wpss` | WiFi Processor SubSystem |
| `wlan-fw` | WLAN Firmware |
| `video` | Video Codec |
| `hyp` | Hypervisor |
| `camera` | Camera |
| `cvp` | Computer Vision Processor |
| `qtee` | Qualcomm Trusted Execution Environment |
| `smem` | Shared Memory |
| `tags` | Tags region |

---

## Output JSON Schema

```json
{
  "report_type": "CarveoutValidationReport",
  "generated_at": "2026-08-16T08:30:00",
  "dump_dir": "mem_dump/",
  "carveout_source": "reserved-memory/*.bin",
  "results": [
    {
      "name": "mpss",
      "base_addr": "0x8b000000",
      "base_addr_int": 2332033024,
      "actual_size_kb": 98304,
      "actual_size_mb": 96.0,
      "status": "FOUND"
    },
    {
      "name": "cdsp",
      "base_addr": "0x98000000",
      "base_addr_int": 2550136832,
      "actual_size_kb": 32768,
      "actual_size_mb": 32.0,
      "status": "FOUND"
    }
  ],
  "summary": {
    "found": 12,
    "total_actual_mb": 349.0
  }
}
```

---

## Changelog

| Version | Date | Notes |
|---|---|---|
| 2.0.0 | 2026-09-21 | Simplified to parsing-only. Added JSON output. |
| 1.0.0 | 2026-08-10 | Initial release. DT carve-out reader, HTML/XLSX/TXT reports. |

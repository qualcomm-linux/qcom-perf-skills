# Data Collection & Normalization — Reference

Full `MemorySnapshot` schema, parser specifications, and source inventory.

---

## MemorySnapshot JSON Schema

```json
{
  "schema_version": "1.0.0",
  "snapshot_id": "<uuid>",
  "timestamp": "2026-08-16T08:30:00+05:30",
  "label": "baseline",
  "device": {
    "serial": "R5CX123ABCD",
    "model": "Qualcomm RB3 Gen2",
    "kernel_version": "6.6.28-qcom",
    "soc_id": "QCS6490",
    "android_version": "14"
  },
  "dump_dir": "mem_dump/",
  "sources": {
    "meminfo":      { "available": true,  "path": "mem_dump/meminfo.txt",      "parsed": { "MemTotal": 12288000, "MemFree": 2048000 } },
    "slabinfo":     { "available": true,  "path": "mem_dump/slabinfo.txt",     "parsed": [ { "name": "kmalloc-256", "active_objs": 4096, "obj_size": 256, "total_kb": 1024 } ] },
    "vmstat":       { "available": true,  "path": "mem_dump/vmstat.txt",       "parsed": { "pgalloc_normal": 123456 } },
    "buddyinfo":    { "available": true,  "path": "mem_dump/buddyinfo.txt",    "parsed": { "Normal": { "order_0": 128, "order_1": 64 } } },
    "zoneinfo":     { "available": true,  "path": "mem_dump/zoneinfo.txt",     "parsed": [ { "zone": "Normal", "present": 3145728, "managed": 2883584 } ] },
    "pagetypeinfo": { "available": true,  "path": "mem_dump/pagetypeinfo.txt", "parsed": { "Normal": { "Unmovable": 1024, "Movable": 8192 } } },
    "debugfs": {
      "dmabuf": { "available": true, "path": "mem_dump/dmabuf_bufinfo.txt", "parsed": { "total_kb": 204800, "by_allocator": { "system": 102400 } } },
      "cma":    { "available": true, "path": "mem_dump/cma_used.txt",       "parsed": [ { "region": "linux,cma", "used_kb": 65536 } ] },
      "kgsl":   { "available": true, "path": "mem_dump/kgsl_alloc.txt",     "parsed": { "total_kb": 131072, "by_process": [ { "pid": 1234, "name": "surfaceflinger", "kb": 32768 } ] } }
    },
    "process_stats": { "available": true, "path": "mem_dump/procrank.txt", "parsed": [ { "pid": 1234, "name": "surfaceflinger", "vss_kb": 204800, "rss_kb": 65536, "pss_kb": 32768 } ] },
    "reserved_memory": {
      "available": true,
      "nodes": [
        { "name": "mpss@8b000000",  "base": "0x8b000000", "size_kb": 196608 },
        { "name": "adsp@96400000",  "base": "0x96400000", "size_kb": 32768  },
        { "name": "hyp@80000000",   "base": "0x80000000", "size_kb": 8192   }
      ]
    },
    "iomem": { "available": true, "path": "mem_dump/iomem.txt", "parsed": { "system_ram_ranges": [ { "start": "0x80000000", "end": "0xFFFFFFFF" } ] } }
  },
  "collection_errors": [
    { "source": "ion", "error": "path not found — kernel >= 5.15 uses dma_buf" }
  ]
}
```

---

## Parser Specifications

| Source | Remote Path | Parser Function | Output Type |
|---|---|---|---|
| meminfo | `/proc/meminfo` | `parse_meminfo(text)` | `dict[str, int]` (values in kB) |
| slabinfo | `/proc/slabinfo` | `parse_slabinfo(text)` | `list[SlabEntry]` |
| vmstat | `/proc/vmstat` | `parse_vmstat(text)` | `dict[str, int]` |
| buddyinfo | `/proc/buddyinfo` | `parse_buddyinfo(text)` | `dict[zone, dict[order, int]]` |
| zoneinfo | `/proc/zoneinfo` | `parse_zoneinfo(text)` | `list[ZoneEntry]` |
| pagetypeinfo | `/proc/pagetypeinfo` | `parse_pagetypeinfo(text)` | `dict[zone, dict[type, int]]` |
| dmabuf | `/sys/kernel/debug/dma_buf/bufinfo` | `parse_dmabuf(text)` | `DmaBufInfo` |
| cma | `/sys/kernel/debug/cma/*/used` | `parse_cma(text)` | `list[CmaEntry]` |
| kgsl | `/sys/class/kgsl/kgsl/page_alloc` | `parse_kgsl(text)` | `KgslInfo` |
| process_stats | `procrank -p` | `parse_procrank(text)` | `list[ProcessEntry]` |
| reserved_memory | DT binary nodes | `parse_dt_reserved_memory(dir)` | `list[ReservedMemNode]` |
| iomem | `/proc/iomem` | `parse_iomem(text)` | `IomemInfo` |

All sizes are normalized to **kB** internally.

---

## Qualcomm-Specific Notes

- **DMA-BUF vs ION**: Kernels >= 5.15 use `/sys/kernel/debug/dma_buf/bufinfo`; older kernels use `/sys/kernel/debug/ion/`. Probe both, prefer dma_buf.
- **KGSL**: Always collect both total (`page_alloc`) and per-process (`proc/*/mem`).
- **CMA**: Flag when CMA used > 80% of CMA total — exhaustion risk for camera/video.
- **Offlined memory**: Collect `/sys/devices/system/memory/memory*/state` and subtract offlined pages from free memory calculations.
- **16K page kernels**: Check `PAGE_SIZE` from kernel config for correct buddy fragmentation analysis.
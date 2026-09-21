# Snapshot Comparison — Reference

Full `SnapshotComparisonReport` schema, memory categories compared, and delta methodology.

---

## SnapshotComparisonReport JSON Schema

```json
{
  "schema_version": "1.0.0",
  "current_snapshot_id": "a3f2c1d0-...",
  "reference_snapshot_id": "b4e3d2c1-...",
  "current_label": "after_test",
  "reference_label": "baseline",
  "delta_seconds": 3600,
  "categories": [
    {
      "category": "MemTotal",
      "reference_kb": 12288000,
      "current_kb": 12288000,
      "delta_kb": 0,
      "delta_pct": 0.0,
      "trend": "STABLE"
    },
    {
      "category": "Slab",
      "reference_kb": 524288,
      "current_kb": 786432,
      "delta_kb": 262144,
      "delta_pct": 50.0,
      "trend": "GROWING"
    }
  ],
  "top_growers": [
    { "category": "Slab", "delta_kb": 262144, "delta_pct": 50.0 }
  ],
  "top_reducers": [],
  "findings": [
    { "severity": "WARNING", "message": "Slab grew by 256 MB (50%) since baseline" }
  ]
}
```

---

## Memory Categories Compared

| Category | Source Field in MemorySnapshot |
|---|---|
| MemTotal | `sources.meminfo.parsed.MemTotal` |
| MemFree | `sources.meminfo.parsed.MemFree` |
| Slab | `sources.meminfo.parsed.Slab` |
| Vmalloc | `sources.meminfo.parsed.VmallocUsed` |
| PageTables | `sources.meminfo.parsed.PageTables` |
| KernelStack | `sources.meminfo.parsed.KernelStack` |
| AnonPages | `sources.meminfo.parsed.AnonPages` |
| Shmem | `sources.meminfo.parsed.Shmem` |
| DMA-BUF | `sources.debugfs.dmabuf.parsed.total_kb` |
| KGSL | `sources.debugfs.kgsl.parsed.total_kb` |
| CMA Used | sum of `sources.debugfs.cma.parsed[*].used_kb` |
| SwapCached | `sources.meminfo.parsed.SwapCached` |
| NHLOS Total | sum of `sources.reserved_memory.nodes[*].size_kb` |

---

## Delta Calculation

```
delta_kb  = current_kb - reference_kb
delta_pct = (delta_kb / reference_kb) x 100   (if reference_kb > 0)

trend = GROWING   if delta_pct > +threshold_pct  (default: +5%)
        SHRINKING if delta_pct < -threshold_pct  (default: -5%)
        STABLE    otherwise
```

Top growers and reducers are ranked by absolute `delta_kb`.

---

## Flagging Thresholds

| Threshold | Default | Description |
|---|---|---|
| `--threshold-pct` | 5.0 | Minimum % change to classify as GROWING or SHRINKING |
| `--threshold-mb` | 50.0 | Minimum absolute MB change to generate a WARNING finding |

A WARNING finding is generated when both thresholds are exceeded simultaneously.
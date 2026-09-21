# Anomaly Correlation & Root Cause Analysis — Reference

Full `RCAReport` schema, confidence scoring methodology, and correlation patterns.

---

## RCAReport JSON Schema

```json
{
  "schema_version": "1.0.0",
  "generated_at": "2026-08-16T08:30:00+05:30",
  "input_reports": ["memory_map_report.json", "kernel_diff_report.json"],
  "anomalies": [
    {
      "id": "ANO-001",
      "title": "Kernel slab memory leak in kmalloc-256",
      "severity": "CRITICAL",
      "confidence": 0.87,
      "layer": "kernel",
      "evidence": [
        { "source": "kernel_diff",  "finding": "kmalloc-256 grew 300% (3 GB)" },
        { "source": "comparison",   "finding": "Slab total grew 50% since baseline" },
        { "source": "vmstat_diff",  "finding": "pgscan_kswapd increased by 12345" }
      ],
      "hypothesis": "A kernel subsystem is allocating kmalloc-256 objects without freeing them.",
      "recommended_actions": [
        "Run `cat /proc/slabinfo | grep kmalloc-256` over time to confirm growth rate",
        "Check `kmemleak` output if enabled (CONFIG_DEBUG_KMEMLEAK)",
        "Inspect recently loaded modules for kmalloc-256 usage patterns"
      ]
    },
    {
      "id": "ANO-002",
      "title": "CMA exhaustion risk",
      "severity": "WARNING",
      "confidence": 0.90,
      "layer": "kernel",
      "evidence": [
        { "source": "comparison", "finding": "CMA Used grew by 45.0 MB (+22.5%)" }
      ],
      "hypothesis": "CMA usage is growing, which may exhaust contiguous memory available for camera, video, and ADSP subsystems.",
      "recommended_actions": [
        "Check `cat /sys/kernel/debug/cma/*/used` for per-region usage",
        "Identify which subsystem is consuming CMA (camera, video, ADSP)"
      ]
    }
  ],
  "summary": {
    "critical": 1,
    "warning": 2,
    "info": 3,
    "layers_affected": ["kernel", "nhlos"],
    "overall_health": "DEGRADED"
  }
}
```

---

## Severity Levels

| Severity | Criteria |
|---|---|
| `CRITICAL` | Active OOM, confirmed leak > 500 MB, carveout overlap |
| `WARNING` | Growing trend > 50 MB, carveout mismatch, fragmentation index > 0.7 |
| `INFO` | Minor growth, informational carveout notes |

---

## Confidence Scoring

Base confidence starts at 0.50. Each corroborating evidence piece adds a boost:

| Pattern | Confidence Boost |
|---|---|
| Single slab > 100% growth | +0.30 |
| Slab growing + high `pgscan_kswapd` | +0.20 |
| DMA-BUF + KGSL both growing + single process PSS growing | +0.25 |
| Buddy fragmentation high + OOM events | +0.35 |
| CMA used > 80% + DMA-BUF growing | +0.30 |
| `oom_kill` > 0 + MemFree < 5% MemTotal | +0.50 |

Confidence is capped at 0.99.

---

## Overall Health States

| State | Criteria |
|---|---|
| `HEALTHY` | No anomalies found |
| `DEGRADED` | One or more WARNING anomalies, no CRITICAL |
| `CRITICAL` | One or more CRITICAL anomalies |
#!/usr/bin/env python3
# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause
"""
anomaly-rca -- Anomaly Correlation & Root Cause Analysis
Ingests findings from any combination of memory skill report JSONs,
applies correlation heuristics, and produces a ranked RCAReport.

Usage:
    python analyze_rca.py [--map-report <json>] [--carveout-report <json>]
                          [--comparison-report <json>] [--kernel-diff <json>]
                          [--userspace-diff <json>] [--output-dir <dir>]
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Correlation patterns
# ---------------------------------------------------------------------------

CORRELATION_PATTERNS = [
    {
        "id": "KERN-SLAB-LEAK",
        "title": "Kernel slab memory leak",
        "layer": "kernel",
        "base_confidence": 0.50,
        "check": lambda r: _check_slab_leak(r),
    },
    {
        "id": "KERN-OOM",
        "title": "Active OOM condition",
        "layer": "kernel",
        "base_confidence": 0.70,
        "check": lambda r: _check_oom(r),
    },
    {
        "id": "KERN-PRESSURE",
        "title": "Kernel memory pressure (active reclaim)",
        "layer": "kernel",
        "base_confidence": 0.50,
        "check": lambda r: _check_memory_pressure(r),
    },
    {
        "id": "KERN-FRAG",
        "title": "Memory fragmentation increasing",
        "layer": "kernel",
        "base_confidence": 0.50,
        "check": lambda r: _check_fragmentation(r),
    },
    {
        "id": "USER-PROC-LEAK",
        "title": "Userspace process memory leak",
        "layer": "userspace",
        "base_confidence": 0.50,
        "check": lambda r: _check_process_leak(r),
    },
    {
        "id": "USER-GRAPHICS-LEAK",
        "title": "Graphics/media memory leak (DMA-BUF + KGSL + process)",
        "layer": "userspace",
        "base_confidence": 0.50,
        "check": lambda r: _check_graphics_leak(r),
    },
    {
        "id": "CMA-EXHAUSTION",
        "title": "CMA exhaustion risk",
        "layer": "kernel",
        "base_confidence": 0.60,
        "check": lambda r: _check_cma_exhaustion(r),
    },
    {
        "id": "GROWING-TREND",
        "title": "Significant memory growth since baseline",
        "layer": "system",
        "base_confidence": 0.50,
        "check": lambda r: _check_growing_trend(r),
    },
]


# ---------------------------------------------------------------------------
# Pattern check functions
# ---------------------------------------------------------------------------

def _check_slab_leak(reports: dict) -> dict | None:
    kd = reports.get("kernel_diff")
    if not kd:
        return None
    flagged = [s for s in kd.get("top_slab_growers", []) if s.get("delta_kb", 0) > 0]
    if not flagged:
        return None
    top = flagged[0]
    delta_mb = top["delta_kb"] / 1024
    confidence_boost = min(0.30, delta_mb / 1000)
    evidence = [
        {"source": "kernel_diff",
         "finding": f"Slab '{top['name']}' grew by {delta_mb:.1f} MB ({top['delta_pct']:+.1f}%)"},
    ]
    # Cross-correlate with comparison report
    comp = reports.get("comparison")
    if comp:
        slab_cat = next((c for c in comp.get("categories", []) if c["category"] == "Slab"), None)
        if slab_cat and slab_cat.get("trend") == "GROWING":
            confidence_boost += 0.20
            evidence.append({
                "source": "comparison",
                "finding": f"Slab total trend: GROWING ({slab_cat['delta_pct']:+.1f}%)",
            })
    # Cross-correlate with vmstat pressure
    pgscan = kd.get("vmstat_diff", {}).get("pgscan_kswapd_delta", 0)
    if pgscan > 10000:
        confidence_boost += 0.10
        evidence.append({
            "source": "vmstat_diff",
            "finding": f"kswapd scanned {pgscan:,} pages -- memory pressure",
        })
    return {
        "confidence_boost": confidence_boost,
        "evidence": evidence,
        "hypothesis": (
            f"A kernel subsystem is allocating '{top['name']}' objects without freeing them. "
            f"Likely candidates: network socket buffers, crypto subsystem, or a loadable module."
        ),
        "recommended_actions": [
            f"Run `cat /proc/slabinfo | grep {top['name']}` over time to confirm growth rate",
            "Check `kmemleak` output if enabled (CONFIG_DEBUG_KMEMLEAK=y)",
            "Inspect recently loaded modules for slab allocation patterns",
        ],
        "severity": "CRITICAL" if delta_mb > 500 else "WARNING",
    }


def _check_oom(reports: dict) -> dict | None:
    kd = reports.get("kernel_diff")
    if not kd:
        return None
    oom = kd.get("vmstat_diff", {}).get("oom_kill_delta", 0)
    if oom <= 0:
        return None
    return {
        "confidence_boost": 0.50,
        "evidence": [
            {"source": "vmstat_diff",
             "finding": f"OOM killer fired {oom} time(s) between snapshots"},
        ],
        "hypothesis": (
            "The system ran out of memory and the OOM killer terminated processes. "
            "This indicates severe memory pressure."
        ),
        "recommended_actions": [
            "Check `dmesg | grep -i oom` for killed process names",
            "Investigate the largest memory consumers at the time of OOM",
            "Consider increasing swap or reducing memory consumers",
        ],
        "severity": "CRITICAL",
    }


def _check_memory_pressure(reports: dict) -> dict | None:
    kd = reports.get("kernel_diff")
    if not kd:
        return None
    pgscan = kd.get("vmstat_diff", {}).get("pgscan_kswapd_delta", 0)
    if pgscan < 50000:
        return None
    return {
        "confidence_boost": 0.20,
        "evidence": [
            {"source": "vmstat_diff",
             "finding": f"kswapd scanned {pgscan:,} pages -- sustained memory pressure"},
        ],
        "hypothesis": (
            "The kernel is under sustained memory pressure, actively reclaiming pages. "
            "This may cause performance degradation and eventual OOM."
        ),
        "recommended_actions": [
            "Identify the largest memory consumers with `cat /proc/meminfo`",
            "Check for memory leaks in kernel slabs or userspace processes",
        ],
        "severity": "WARNING",
    }


def _check_fragmentation(reports: dict) -> dict | None:
    kd = reports.get("kernel_diff")
    if not kd:
        return None
    frag_delta = kd.get("buddy_fragmentation", {}).get("fragmentation_index_delta", 0)
    if frag_delta < 0.1:
        return None
    bd = kd["buddy_fragmentation"]
    return {
        "confidence_boost": 0.35,
        "evidence": [
            {"source": "kernel_diff",
             "finding": (
                 f"Buddy fragmentation index: {bd['reference_index']:.3f} -> "
                 f"{bd['current_index']:.3f} (delta: {frag_delta:+.3f})"
             )},
        ],
        "hypothesis": (
            "Memory fragmentation is increasing, which may cause failures for "
            "contiguous memory allocations (CMA, DMA, large kmalloc)."
        ),
        "recommended_actions": [
            "Run `cat /proc/buddyinfo` to see current fragmentation state",
            "Consider enabling memory compaction (CONFIG_COMPACTION)",
            "Check for long-lived pinned pages preventing compaction",
        ],
        "severity": "WARNING",
    }


def _check_process_leak(reports: dict) -> dict | None:
    ud = reports.get("userspace_diff")
    if not ud:
        return None
    flagged = [p for p in ud.get("top_pss_growers", []) if p.get("delta_pss_kb", 0) > 0]
    if not flagged:
        return None
    top = flagged[0]
    delta_mb = top["delta_pss_kb"] / 1024
    return {
        "confidence_boost": 0.25,
        "evidence": [
            {"source": "userspace_diff",
             "finding": f"Process '{top['name']}' PSS grew by {delta_mb:.1f} MB ({top['delta_pct']:+.1f}%)"},
        ],
        "hypothesis": (
            f"Process '{top['name']}' is accumulating memory without releasing it. "
            f"This may indicate a memory leak in the application or its libraries."
        ),
        "recommended_actions": [
            f"Monitor '{top['name']}' PSS over time with `procrank | grep {top['name']}`",
            f"Check for unclosed file descriptors or growing heap in '{top['name']}'",
            "Use `valgrind` or `heaptrack` if the process can be reproduced in a test environment",
        ],
        "severity": "CRITICAL" if delta_mb > 200 else "WARNING",
    }


def _check_graphics_leak(reports: dict) -> dict | None:
    ud = reports.get("userspace_diff")
    if not ud:
        return None
    dma_delta = ud.get("dmabuf_diff", {}).get("delta_kb", 0)
    kgsl_delta = ud.get("kgsl_diff", {}).get("delta_kb", 0)
    if dma_delta < 20480 and kgsl_delta < 20480:  # < 20 MB each
        return None
    evidence = []
    confidence_boost = 0.0
    if dma_delta > 20480:
        evidence.append({
            "source": "userspace_diff",
            "finding": f"DMA-BUF total grew by {dma_delta/1024:.1f} MB",
        })
        confidence_boost += 0.25
    if kgsl_delta > 20480:
        evidence.append({
            "source": "userspace_diff",
            "finding": f"KGSL GPU memory grew by {kgsl_delta/1024:.1f} MB",
        })
        confidence_boost += 0.15
    # Check if a single process is responsible
    top_growers = ud.get("top_pss_growers", [])
    if top_growers:
        top = top_growers[0]
        evidence.append({
            "source": "userspace_diff",
            "finding": f"Process '{top['name']}' PSS also growing ({top['delta_pss_kb']/1024:.1f} MB)",
        })
        confidence_boost += 0.10
    return {
        "confidence_boost": confidence_boost,
        "evidence": evidence,
        "hypothesis": (
            "A graphics or media subsystem is accumulating GPU/display buffers. "
            "Common causes: surfaceflinger buffer leak, video decoder not releasing frames, "
            "camera HAL holding buffers."
        ),
        "recommended_actions": [
            "Check `cat /sys/kernel/debug/dma_buf/bufinfo` for growing allocators",
            "Monitor KGSL per-process: `cat /sys/class/kgsl/kgsl/proc/*/mem`",
            "Check for unclosed EGL surfaces or unreleased MediaCodec buffers",
        ],
        "severity": "WARNING",
    }


def _check_cma_exhaustion(reports: dict) -> dict | None:
    # Check from comparison report if CMA Used is growing significantly
    comp = reports.get("comparison")
    if not comp:
        return None
    cma_cat = next(
        (c for c in comp.get("categories", []) if c["category"] == "CMA Used"), None
    )
    if not cma_cat or cma_cat.get("trend") != "GROWING":
        return None
    delta_mb = cma_cat["delta_kb"] / 1024
    if delta_mb < 20:
        return None
    return {
        "confidence_boost": 0.30,
        "evidence": [
            {"source": "comparison",
             "finding": f"CMA Used grew by {delta_mb:.1f} MB ({cma_cat['delta_pct']:+.1f}%)"},
        ],
        "hypothesis": (
            "CMA usage is growing, which may exhaust contiguous memory available for "
            "camera, video, and ADSP subsystems."
        ),
        "recommended_actions": [
            "Check `cat /sys/kernel/debug/cma/*/used` for per-region usage",
            "Identify which subsystem is consuming CMA (camera, video, ADSP)",
            "Consider increasing CMA pool size if usage is legitimate",
        ],
        "severity": "WARNING",
    }


def _check_growing_trend(reports: dict) -> dict | None:
    comp = reports.get("comparison")
    if not comp:
        return None
    growers = comp.get("top_growers", [])
    if not growers:
        return None
    top = growers[0]
    delta_mb = top["delta_kb"] / 1024
    if delta_mb < 100:
        return None
    return {
        "confidence_boost": 0.10,
        "evidence": [
            {"source": "comparison",
             "finding": f"Top grower: {top['category']} +{delta_mb:.1f} MB ({top['delta_pct']:+.1f}%)"},
        ],
        "hypothesis": (
            f"Memory category '{top['category']}' has grown significantly since baseline. "
            f"Further investigation is needed to determine the root cause."
        ),
        "recommended_actions": [
            f"Investigate '{top['category']}' growth with the appropriate diff skill",
            "Collect additional snapshots to confirm the trend",
        ],
        "severity": "INFO",
    }


# ---------------------------------------------------------------------------
# RCA engine
# ---------------------------------------------------------------------------

def run_rca(reports: dict) -> list:
    """Run all correlation patterns and return ranked anomalies."""
    anomalies = []
    for i, pattern in enumerate(CORRELATION_PATTERNS):
        result = pattern["check"](reports)
        if result is None:
            continue
        confidence = min(0.99, pattern["base_confidence"] + result["confidence_boost"])
        anomalies.append({
            "id": f"ANO-{i+1:03d}",
            "title": pattern["title"],
            "severity": result.get("severity", "WARNING"),
            "confidence": round(confidence, 2),
            "layer": pattern["layer"],
            "evidence": result["evidence"],
            "hypothesis": result["hypothesis"],
            "recommended_actions": result["recommended_actions"],
        })
    # Sort by severity then confidence
    severity_order = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}
    anomalies.sort(key=lambda x: (severity_order.get(x["severity"], 3), -x["confidence"]))
    return anomalies


def compute_summary(anomalies: list, input_reports: list) -> dict:
    critical = sum(1 for a in anomalies if a["severity"] == "CRITICAL")
    warning = sum(1 for a in anomalies if a["severity"] == "WARNING")
    info = sum(1 for a in anomalies if a["severity"] == "INFO")
    layers = list({a["layer"] for a in anomalies})
    if critical > 0:
        health = "CRITICAL"
    elif warning > 0:
        health = "DEGRADED"
    else:
        health = "HEALTHY"
    return {
        "critical": critical,
        "warning": warning,
        "info": info,
        "layers_affected": layers,
        "overall_health": health,
        "input_reports_count": len(input_reports),
        "mode": "two-snapshot" if any(
            "comparison" in r or "kernel_diff" in r or "userspace_diff" in r
            for r in [input_reports]
        ) else "single-snapshot",
    }


# ---------------------------------------------------------------------------
# Report writers
# ---------------------------------------------------------------------------

def write_json(report: dict, output_dir: str):
    path = os.path.join(output_dir, "rca_report.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(f"[anomaly-rca] JSON  -> {path}")


def write_txt(report: dict, output_dir: str):
    path = os.path.join(output_dir, "rca_report.txt")
    s = report["summary"]
    lines = [
        "Anomaly Correlation & Root Cause Analysis Report",
        "=" * 70,
        f"Overall Health: {s['overall_health']}",
        f"Critical: {s['critical']}  Warning: {s['warning']}  Info: {s['info']}",
        f"Layers affected: {', '.join(s['layers_affected']) or 'none'}",
        f"Mode: {s.get('mode', 'unknown')}",
        "",
    ]
    for a in report["anomalies"]:
        lines += [
            f"[{a['severity']}] {a['id']}: {a['title']}",
            f"  Confidence: {a['confidence']:.0%}  Layer: {a['layer']}",
            "  Evidence:",
        ]
        for e in a["evidence"]:
            lines.append(f"    - [{e['source']}] {e['finding']}")
        lines += [
            f"  Hypothesis: {a['hypothesis']}",
            "  Recommended actions:",
        ]
        for action in a["recommended_actions"]:
            lines.append(f"    {action}")
        lines.append("")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"[anomaly-rca] TXT   -> {path}")


def write_html(report: dict, output_dir: str):
    path = os.path.join(output_dir, "rca_report.html")
    s = report["summary"]
    health_color = {"HEALTHY": "#e0ffe0", "DEGRADED": "#fff8e0", "CRITICAL": "#ffe0e0"}
    badge_color = health_color.get(s["overall_health"], "#f0f0f0")
    cards = ""
    for a in report["anomalies"]:
        sev_color = {"CRITICAL": "#ffe0e0", "WARNING": "#fff8e0", "INFO": "#e8f4fd"}
        card_color = sev_color.get(a["severity"], "#f9f9f9")
        evidence_items = "".join(
            f"<li><b>[{e['source']}]</b> {e['finding']}</li>" for e in a["evidence"]
        )
        actions = "".join(f"<li>{act}</li>" for act in a["recommended_actions"])
        cards += f"""
<div style='border:1px solid #ccc;border-radius:6px;padding:12px;margin:10px 0;background:{card_color}'>
  <h3 style='margin:0'>[{a['severity']}] {a['id']}: {a['title']}</h3>
  <p><b>Confidence:</b> {a['confidence']:.0%} &nbsp; <b>Layer:</b> {a['layer']}</p>
  <p><b>Evidence:</b></p><ul>{evidence_items}</ul>
  <p><b>Hypothesis:</b> {a['hypothesis']}</p>
  <p><b>Recommended actions:</b></p><ol>{actions}</ol>
</div>"""
    html = f"""<!DOCTYPE html>
<html><head><meta charset='utf-8'><title>RCA Report</title>
<style>body{{font-family:sans-serif;margin:20px;max-width:1000px}}</style></head>
<body>
<h1>Anomaly Correlation & Root Cause Analysis</h1>
<div style='background:{badge_color};padding:12px;border-radius:6px;margin-bottom:20px'>
  <b>Overall Health: {s['overall_health']}</b> &nbsp;|&nbsp;
  Critical: {s['critical']} &nbsp; Warning: {s['warning']} &nbsp; Info: {s['info']}<br>
  Layers affected: {', '.join(s['layers_affected']) or 'none'} &nbsp;|&nbsp;
  Mode: {s.get('mode', 'unknown')}
</div>
{cards if cards else '<p>No anomalies detected.</p>'}
</body></html>"""
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"[anomaly-rca] HTML  -> {path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def load_report(path: str | None, label: str) -> dict | None:
    if not path:
        return None
    if not os.path.isfile(path):
        print(f"[anomaly-rca] WARNING: {label} not found at {path} -- skipping")
        return None
    with open(path) as f:
        return json.load(f)


def _snapshot_to_rca_report(snapshot_path: str, output_dir: str) -> dict:
    """
    Single-snapshot mode: build a minimal RCA-compatible report directly
    from a snapshot.json without requiring a full memory-map run.
    Checks absolute thresholds (free memory, slab size, DMA-BUF, etc.)
    """
    with open(snapshot_path) as f:
        snap = json.load(f)

    mem = snap.get("sources", {}).get("meminfo", {})
    parsed = mem.get("parsed", {}) if mem.get("available") else {}
    debugfs = snap.get("sources", {}).get("debugfs", {})
    device = snap.get("device", {})
    label = snap.get("label", "snapshot")

    mem_total_kb  = parsed.get("MemTotal", 0)
    mem_free_kb   = parsed.get("MemFree", 0)
    slab_kb       = parsed.get("Slab", 0)
    anon_kb       = parsed.get("AnonPages", 0)
    dmabuf_kb     = debugfs.get("dmabuf", {}).get("parsed", {}).get("total_kb", 0) \
                    if debugfs.get("dmabuf", {}).get("available") else 0
    kgsl_kb       = debugfs.get("kgsl", {}).get("parsed", {}).get("total_kb", 0) \
                    if debugfs.get("kgsl", {}).get("available") else 0

    anomalies = []

    # Check 1: critically low free memory (< 5% of total)
    if mem_total_kb > 0:
        free_pct = mem_free_kb / mem_total_kb * 100
        if free_pct < 5.0:
            anomalies.append({
                "id": "ANO-LOW-MEM",
                "title": "Critically low free memory",
                "severity": "CRITICAL",
                "layer": "kernel",
                "confidence": 0.95,
                "hypothesis": (
                    f"Free memory is {free_pct:.1f}% of total ({mem_free_kb//1024} MB free of "
                    f"{mem_total_kb//1024} MB). Device is at risk of OOM kills."
                ),
                "evidence": [{"source": "meminfo", "finding": f"MemFree={mem_free_kb//1024} MB ({free_pct:.1f}%)"}],
                "recommended_actions": [
                    "Identify and terminate memory-intensive processes",
                    "Check for memory leaks with userspace-diff skill",
                    "Consider increasing swap/zram",
                ],
            })
        elif free_pct < 15.0:
            anomalies.append({
                "id": "ANO-LOW-MEM-WARN",
                "title": "Low free memory warning",
                "severity": "WARNING",
                "layer": "kernel",
                "confidence": 0.80,
                "hypothesis": (
                    f"Free memory is {free_pct:.1f}% of total ({mem_free_kb//1024} MB free). "
                    f"Memory pressure may cause performance degradation."
                ),
                "evidence": [{"source": "meminfo", "finding": f"MemFree={mem_free_kb//1024} MB ({free_pct:.1f}%)"}],
                "recommended_actions": ["Monitor memory usage", "Check for memory leaks"],
            })

    # Check 2: large slab allocation (> 20% of total)
    if mem_total_kb > 0 and slab_kb / mem_total_kb > 0.20:
        anomalies.append({
            "id": "ANO-SLAB-HIGH",
            "title": "Unusually high kernel slab usage",
            "severity": "WARNING",
            "layer": "kernel",
            "confidence": 0.70,
            "hypothesis": (
                f"Slab allocator is using {slab_kb//1024} MB ({slab_kb/mem_total_kb*100:.1f}% of total). "
                f"This may indicate a kernel memory leak."
            ),
            "evidence": [{"source": "meminfo", "finding": f"Slab={slab_kb//1024} MB"}],
            "recommended_actions": ["Run kernel-diff skill to identify growing slabs"],
        })

    # Check 3: large DMA-BUF allocation (> 200 MB)
    if dmabuf_kb > 200 * 1024:
        anomalies.append({
            "id": "ANO-DMABUF-HIGH",
            "title": "Large DMA-BUF allocation",
            "severity": "INFO",
            "layer": "hardware",
            "confidence": 0.60,
            "hypothesis": (
                f"DMA-BUF buffers total {dmabuf_kb//1024} MB. This is expected if a camera or "
                f"video use-case is active, but may indicate a leak if no use-case is running."
            ),
            "evidence": [{"source": "debugfs/dmabuf", "finding": f"DMA-BUF total={dmabuf_kb//1024} MB"}],
            "recommended_actions": ["Verify a camera/video use-case is intentionally running"],
        })

    if not anomalies:
        anomalies.append({
            "id": "ANO-HEALTHY",
            "title": "No anomalies detected",
            "severity": "INFO",
            "layer": "system",
            "confidence": 1.0,
            "hypothesis": "Memory usage appears normal. No absolute threshold violations detected.",
            "evidence": [{"source": "meminfo", "finding": f"MemFree={mem_free_kb//1024} MB, Slab={slab_kb//1024} MB"}],
            "recommended_actions": [],
        })

    summary = compute_summary(anomalies, [snapshot_path])
    summary["mode"] = "single-snapshot"
    summary["device"] = f"{device.get('model','')} ({device.get('soc_id','')})"
    summary["label"] = label

    return {
        "schema_version": "1.0.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_reports": [snapshot_path],
        "anomalies": anomalies,
        "summary": summary,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Anomaly correlation and root cause analysis."
    )
    parser.add_argument("--snapshot", help="snapshot.json for standalone single-snapshot analysis")
    parser.add_argument("--map-report", help="MemoryMapReport JSON")
    parser.add_argument("--carveout-report", help="CarveoutValidationReport JSON (informational only)")
    parser.add_argument("--comparison-report", help="SnapshotComparisonReport JSON")
    parser.add_argument("--kernel-diff", help="KernelDiffReport JSON")
    parser.add_argument("--userspace-diff", help="UserspaceDiffReport JSON")
    parser.add_argument("--output-dir", default=".", help="Output directory")
    args = parser.parse_args()

    # Single-snapshot standalone mode
    if args.snapshot:
        if not os.path.isfile(args.snapshot):
            print(f"ERROR: snapshot not found: {args.snapshot}")
            sys.exit(1)
        print(f"[anomaly-rca] Running in single-snapshot mode: {args.snapshot}")
        os.makedirs(args.output_dir, exist_ok=True)
        report = _snapshot_to_rca_report(args.snapshot, args.output_dir)
        write_json(report, args.output_dir)
        write_txt(report, args.output_dir)
        write_html(report, args.output_dir)
        s = report["summary"]
        print(f"\n[anomaly-rca] Overall health: {s['overall_health']} -- "
              f"{s['critical']} critical, {s['warning']} warning, {s['info']} info")
        return 0

    # Load available reports
    reports = {}
    input_reports = []

    carveout = load_report(args.carveout_report, "carveout-report")
    if carveout:
        reports["carveout_validation"] = carveout
        input_reports.append(args.carveout_report)

    comparison = load_report(args.comparison_report, "comparison-report")
    if comparison:
        reports["comparison"] = comparison
        input_reports.append(args.comparison_report)

    kernel_diff = load_report(args.kernel_diff, "kernel-diff")
    if kernel_diff:
        reports["kernel_diff"] = kernel_diff
        input_reports.append(args.kernel_diff)

    userspace_diff = load_report(args.userspace_diff, "userspace-diff")
    if userspace_diff:
        reports["userspace_diff"] = userspace_diff
        input_reports.append(args.userspace_diff)

    if not reports:
        print("ERROR: At least one report JSON must be provided.")
        print("Use --map-report, --comparison-report,")
        print("    --kernel-diff, or --userspace-diff")
        sys.exit(1)

    mode = "two-snapshot" if (comparison or kernel_diff or userspace_diff) else "single-snapshot"
    print(f"[anomaly-rca] Running in {mode} mode with {len(reports)} input report(s)...")

    os.makedirs(args.output_dir, exist_ok=True)

    anomalies = run_rca(reports)
    summary = compute_summary(anomalies, input_reports)
    summary["mode"] = mode

    report = {
        "schema_version": "1.0.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_reports": input_reports,
        "anomalies": anomalies,
        "summary": summary,
    }

    write_json(report, args.output_dir)
    write_txt(report, args.output_dir)
    write_html(report, args.output_dir)

    print(f"\n[anomaly-rca] Overall health: {summary['overall_health']} -- "
          f"{summary['critical']} critical, {summary['warning']} warning, "
          f"{summary['info']} info")
    return 0


if __name__ == "__main__":
    sys.exit(main())
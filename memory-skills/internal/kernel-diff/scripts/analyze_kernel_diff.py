#!/usr/bin/env python3
# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause
"""
kernel-diff -- Kernel Memory Difference Analysis
Computes per-slab, vmalloc, module, and buddy fragmentation deltas
between two MemorySnapshot JSON files.

Usage:
    python analyze_kernel_diff.py --current <snapshot.json> --reference <snapshot.json>
                                  [--output-dir <dir>] [--slab-growth-pct 100]
                                  [--slab-growth-mb 50]
"""

import argparse
import json
import math
import os
import sys


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_snapshot(path: str) -> dict:
    if not os.path.isfile(path):
        print(
            f"ERROR: --reference is required for kernel diff analysis.\n"
            f"No baseline snapshot found at: {path}\n\n"
            f"To create a baseline, run:\n"
            f"  python data-collection/scripts/collect.py --output baseline/ --label baseline\n\n"
            f"Then re-run with:\n"
            f"  --current current/snapshot.json --reference baseline/snapshot.json\n\n"
            f"For single-snapshot kernel analysis (no baseline needed), use:\n"
            f"  memory-map  -- shows current slab, vmalloc, module totals\n"
            f"  anomaly-rca -- flags absolute thresholds (e.g. slab > 1 GB)"
        )
        sys.exit(1)
    with open(path) as f:
        return json.load(f)


def get_slabs(snap: dict) -> dict:
    """Return {slab_name: total_kb} from slabinfo."""
    src = snap.get("sources", {}).get("slabinfo", {})
    if not src.get("available"):
        return {}
    return {s["name"]: s.get("total_kb", 0) for s in src.get("parsed", [])}


def get_vmstat(snap: dict) -> dict:
    """Return vmstat dict."""
    src = snap.get("sources", {}).get("vmstat", {})
    if not src.get("available"):
        return {}
    return src.get("parsed", {})


def get_buddyinfo(snap: dict) -> dict:
    """Return buddyinfo dict {zone: {order_N: count}}."""
    src = snap.get("sources", {}).get("buddyinfo", {})
    if not src.get("available"):
        return {}
    return src.get("parsed", {})


def fragmentation_index(buddy: dict) -> float:
    """
    Compute buddy fragmentation index.
    frag_index = 1 - (sum(count * 2^order) / total_free_pages)
    Range: 0.0 (no fragmentation) to 1.0 (fully fragmented).
    """
    total_pages = 0
    weighted_pages = 0
    for zone, orders in buddy.items():
        for order_key, count in orders.items():
            order = int(order_key.split("_")[1])
            pages = count * (2 ** order)
            total_pages += pages
            weighted_pages += pages
    if total_pages == 0:
        return 0.0
    # Fragmentation: proportion of free pages in small orders
    small_pages = 0
    for zone, orders in buddy.items():
        for order_key, count in orders.items():
            order = int(order_key.split("_")[1])
            if order < 4:  # orders 0-3 are "small"
                small_pages += count * (2 ** order)
    return round(small_pages / total_pages, 4) if total_pages > 0 else 0.0


# ---------------------------------------------------------------------------
# Diff computations
# ---------------------------------------------------------------------------

def compute_slab_diff(cur_slabs: dict, ref_slabs: dict,
                      growth_pct: float, growth_mb: float) -> tuple[list, list]:
    """Compute per-slab deltas. Returns (slab_diff, top_growers)."""
    all_names = set(cur_slabs) | set(ref_slabs)
    diffs = []
    for name in sorted(all_names):
        ref_kb = ref_slabs.get(name, 0)
        cur_kb = cur_slabs.get(name, 0)
        delta_kb = cur_kb - ref_kb
        if ref_kb > 0:
            delta_pct = round((delta_kb / ref_kb) * 100, 2)
        else:
            delta_pct = 100.0 if cur_kb > 0 else 0.0
        flagged = (
            (delta_pct > growth_pct and abs(delta_kb) / 1024 >= growth_mb)
            or delta_pct > 500
        )
        diffs.append({
            "name": name,
            "ref_kb": ref_kb,
            "cur_kb": cur_kb,
            "delta_kb": delta_kb,
            "delta_pct": delta_pct,
            "flagged": flagged,
        })
    diffs.sort(key=lambda x: x["delta_kb"], reverse=True)
    top_growers = [
        {"name": d["name"], "delta_kb": d["delta_kb"], "delta_pct": d["delta_pct"]}
        for d in diffs if d["flagged"]
    ][:10]
    return diffs, top_growers


def compute_vmstat_diff(cur_vm: dict, ref_vm: dict) -> dict:
    """Compute vmstat counter deltas for key pressure indicators."""
    PRESSURE_KEYS = [
        "pgalloc_normal", "pgalloc_dma", "pgfree",
        "pgscan_kswapd", "pgscan_direct", "pgsteal_kswapd",
        "oom_kill", "pgmajfault", "pgfault",
        "compact_stall", "compact_fail", "compact_success",
    ]
    result = {}
    for key in PRESSURE_KEYS:
        cur_val = cur_vm.get(key, 0)
        ref_val = ref_vm.get(key, 0)
        delta = cur_val - ref_val
        if delta != 0:
            result[f"{key}_delta"] = delta
    return result


def compute_buddy_diff(cur_buddy: dict, ref_buddy: dict) -> dict:
    """Compute buddy fragmentation index delta."""
    ref_idx = fragmentation_index(ref_buddy)
    cur_idx = fragmentation_index(cur_buddy)
    return {
        "reference_index": ref_idx,
        "current_index": cur_idx,
        "fragmentation_index_delta": round(cur_idx - ref_idx, 4),
    }


def compute_findings(slab_diff: list, vmstat_diff: dict,
                     buddy_diff: dict) -> list:
    """Generate findings from kernel diff analysis."""
    findings = []

    # Flagged slab leaks
    flagged = [s for s in slab_diff if s.get("flagged")]
    for slab in flagged[:5]:
        delta_mb = slab["delta_kb"] / 1024
        findings.append({
            "severity": "WARNING" if delta_mb < 500 else "CRITICAL",
            "message": (
                f"Slab '{slab['name']}' grew by {delta_mb:.1f} MB "
                f"({slab['delta_pct']:+.1f}%) -- possible kernel memory leak"
            ),
        })

    # Memory pressure
    oom = vmstat_diff.get("oom_kill_delta", 0)
    if oom > 0:
        findings.append({
            "severity": "CRITICAL",
            "message": f"OOM killer fired {oom} time(s) between snapshots",
        })
    pgscan = vmstat_diff.get("pgscan_kswapd_delta", 0)
    if pgscan > 10000:
        findings.append({
            "severity": "WARNING",
            "message": f"kswapd scanned {pgscan:,} pages -- active memory pressure",
        })

    # Fragmentation
    frag_delta = buddy_diff.get("fragmentation_index_delta", 0)
    if frag_delta > 0.1:
        findings.append({
            "severity": "WARNING",
            "message": (
                f"Buddy fragmentation index increased by {frag_delta:.3f} "
                f"({buddy_diff['reference_index']:.3f} -> {buddy_diff['current_index']:.3f})"
            ),
        })

    return findings


# ---------------------------------------------------------------------------
# Report writers
# ---------------------------------------------------------------------------

def write_json(report: dict, output_dir: str):
    path = os.path.join(output_dir, "kernel_diff_report.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(f"[kernel-diff] JSON  -> {path}")


def write_txt(report: dict, output_dir: str):
    path = os.path.join(output_dir, "kernel_diff_report.txt")
    lines = [
        "Kernel Memory Diff Report",
        "=" * 70,
        "",
        "TOP SLAB GROWERS (flagged)",
        f"{'Slab Name':<40} {'Ref KB':>10} {'Cur KB':>10} {'Delta KB':>10} {'Delta %':>9}",
        "-" * 80,
    ]
    for s in report["top_slab_growers"]:
        lines.append(
            f"{s['name']:<40} "
            f"{report['slab_diff'][next(i for i,x in enumerate(report['slab_diff']) if x['name']==s['name'])]['ref_kb']:>10} "
            f"{report['slab_diff'][next(i for i,x in enumerate(report['slab_diff']) if x['name']==s['name'])]['cur_kb']:>10} "
            f"{s['delta_kb']:>+10} "
            f"{s['delta_pct']:>+9.1f}%"
        )
    lines += [
        "",
        "BUDDY FRAGMENTATION",
        f"  Reference index: {report['buddy_fragmentation']['reference_index']:.4f}",
        f"  Current index:   {report['buddy_fragmentation']['current_index']:.4f}",
        f"  Delta:           {report['buddy_fragmentation']['fragmentation_index_delta']:+.4f}",
        "",
        "VMSTAT PRESSURE INDICATORS",
    ]
    for k, v in report["vmstat_diff"].items():
        lines.append(f"  {k}: {v:+,}")
    if report["findings"]:
        lines += ["", "FINDINGS", "-" * 40]
        for f in report["findings"]:
            lines.append(f"  [{f['severity']}] {f['message']}")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"[kernel-diff] TXT   -> {path}")


def write_html(report: dict, output_dir: str):
    path = os.path.join(output_dir, "kernel_diff_report.html")
    slab_rows = ""
    for s in report["slab_diff"][:50]:  # top 50 by delta
        color = "background:#ffe0e0" if s.get("flagged") else ""
        slab_rows += (
            f"<tr style='{color}'>"
            f"<td>{s['name']}</td>"
            f"<td style='text-align:right'>{s['ref_kb']}</td>"
            f"<td style='text-align:right'>{s['cur_kb']}</td>"
            f"<td style='text-align:right'>{s['delta_kb']:+}</td>"
            f"<td style='text-align:right'>{s['delta_pct']:+.1f}%</td>"
            f"<td>{'[!]' if s.get('flagged') else ''}</td>"
            f"</tr>\n"
        )
    findings_html = "".join(
        f"<li style='background:{'#ffe0e0' if f['severity']=='CRITICAL' else '#fff8e0'};padding:4px'>"
        f"[{f['severity']}] {f['message']}</li>\n"
        for f in report["findings"]
    )
    bd = report["buddy_fragmentation"]
    html = f"""<!DOCTYPE html>
<html><head><meta charset='utf-8'><title>Kernel Memory Diff</title>
<style>body{{font-family:monospace;margin:20px}}
table{{border-collapse:collapse;width:100%}}
th,td{{border:1px solid #ccc;padding:4px 8px}}th{{background:#f0f0f0}}</style></head>
<body>
<h1>Kernel Memory Diff Report</h1>
<h2>Buddy Fragmentation</h2>
<p>Reference: {bd['reference_index']:.4f} &rarr; Current: {bd['current_index']:.4f}
   (delta: {bd['fragmentation_index_delta']:+.4f})</p>
<h2>Top Slab Changes (top 50 by delta)</h2>
<table><tr><th>Slab</th><th>Ref KB</th><th>Cur KB</th>
<th>Delta KB</th><th>Delta %</th><th>Flag</th></tr>
{slab_rows}</table>
{'<h2>Findings</h2><ul>' + findings_html + '</ul>' if findings_html else ''}
</body></html>"""
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"[kernel-diff] HTML  -> {path}")


def write_xlsx(report: dict, output_dir: str):
    try:
        import openpyxl
        from openpyxl.styles import PatternFill, Font
    except ImportError:
        print("[kernel-diff] openpyxl not installed -- skipping XLSX")
        return
    path = os.path.join(output_dir, "kernel_diff_report.xlsx")
    wb = openpyxl.Workbook()

    # Slab Diff sheet
    ws = wb.active
    ws.title = "Slab Diff"
    ws.append(["Slab Name", "Ref KB", "Cur KB", "Delta KB", "Delta %", "Flagged"])
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for s in report["slab_diff"]:
        ws.append([s["name"], s["ref_kb"], s["cur_kb"], s["delta_kb"],
                   s["delta_pct"], s.get("flagged", False)])
        if s.get("flagged"):
            for cell in ws[ws.max_row]:
                cell.fill = PatternFill("solid", fgColor="FFE0E0")

    # Buddy sheet
    ws2 = wb.create_sheet("Buddy Fragmentation")
    bd = report["buddy_fragmentation"]
    ws2.append(["Metric", "Value"])
    ws2.append(["Reference Index", bd["reference_index"]])
    ws2.append(["Current Index", bd["current_index"]])
    ws2.append(["Delta", bd["fragmentation_index_delta"]])

    # vmstat sheet
    ws3 = wb.create_sheet("vmstat Pressure")
    ws3.append(["Counter", "Delta"])
    for k, v in report["vmstat_diff"].items():
        ws3.append([k, v])

    wb.save(path)
    print(f"[kernel-diff] XLSX  -> {path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Kernel memory diff between two MemorySnapshot files."
    )
    parser.add_argument("--current", required=True, help="Current snapshot.json")
    parser.add_argument("--reference", required=True, help="Reference snapshot.json")
    parser.add_argument("--output-dir", default=".", help="Output directory")
    parser.add_argument("--slab-growth-pct", type=float, default=100.0,
                        help="Slab growth %% threshold for flagging (default: 100)")
    parser.add_argument("--slab-growth-mb", type=float, default=50.0,
                        help="Slab absolute growth MB threshold (default: 50)")
    parser.add_argument("--format", default="json",
                        help="Comma-separated output formats: json,txt,html,xlsx (default: json)")
    args = parser.parse_args()

    cur = load_snapshot(args.current)
    ref = load_snapshot(args.reference)
    os.makedirs(args.output_dir, exist_ok=True)

    cur_slabs = get_slabs(cur)
    ref_slabs = get_slabs(ref)
    cur_vm = get_vmstat(cur)
    ref_vm = get_vmstat(ref)
    cur_buddy = get_buddyinfo(cur)
    ref_buddy = get_buddyinfo(ref)

    slab_diff, top_growers = compute_slab_diff(
        cur_slabs, ref_slabs, args.slab_growth_pct, args.slab_growth_mb
    )
    vmstat_diff = compute_vmstat_diff(cur_vm, ref_vm)
    buddy_diff = compute_buddy_diff(cur_buddy, ref_buddy)
    findings = compute_findings(slab_diff, vmstat_diff, buddy_diff)

    report = {
        "schema_version": "1.0.0",
        "current_snapshot_id": cur.get("snapshot_id", ""),
        "reference_snapshot_id": ref.get("snapshot_id", ""),
        "slab_diff": slab_diff,
        "vmalloc_diff": [],  # populated from vmallocinfo if available
        "module_diff": [],
        "buddy_fragmentation": buddy_diff,
        "vmstat_diff": vmstat_diff,
        "top_slab_growers": top_growers,
        "findings": findings,
    }

    fmts = {f.strip().lower() for f in args.format.split(",")}
    if "json" in fmts:
        write_json(report, args.output_dir)
    if "txt" in fmts:
        write_txt(report, args.output_dir)
    if "html" in fmts:
        write_html(report, args.output_dir)
    if "xlsx" in fmts:
        write_xlsx(report, args.output_dir)

    flagged_count = sum(1 for s in slab_diff if s.get("flagged"))
    print(f"\n[kernel-diff] {flagged_count} flagged slab(s), "
          f"{len(findings)} finding(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
#!/usr/bin/env python3
"""
userspace-diff -- Userspace Memory Difference Analysis
Computes per-process PSS/RSS deltas, DMA-BUF allocator changes,
and KGSL GPU memory changes between two MemorySnapshot JSON files.

Usage:
    python analyze_userspace_diff.py --current <snapshot.json> --reference <snapshot.json>
                                     [--output-dir <dir>] [--pss-growth-pct 50]
                                     [--pss-growth-mb 20]
"""

import argparse
import json
import os
import sys


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_snapshot(path: str) -> dict:
    if not os.path.isfile(path):
        print(
            f"ERROR: --reference is required for userspace diff analysis.\n"
            f"No baseline snapshot found at: {path}\n\n"
            f"To create a baseline, run:\n"
            f"  python data-collection/scripts/collect.py --output baseline/ --label baseline\n\n"
            f"Then re-run with:\n"
            f"  --current current/snapshot.json --reference baseline/snapshot.json\n\n"
            f"For single-snapshot userspace analysis (no baseline needed), use:\n"
            f"  memory-map  -- shows current per-process PSS totals (via procrank sheet)\n"
            f"  anomaly-rca -- flags absolute thresholds (e.g. single process PSS > 500 MB)"
        )
        sys.exit(1)
    with open(path) as f:
        return json.load(f)


def get_processes(snap: dict) -> dict:
    """Return {name: {pss_kb, rss_kb, pid}} from process_stats."""
    src = snap.get("sources", {}).get("process_stats", {})
    if not src.get("available"):
        return {}
    result = {}
    for proc in src.get("parsed", []):
        name = proc.get("name", "unknown")
        result[name] = {
            "pid": proc.get("pid", 0),
            "pss_kb": proc.get("pss_kb", 0),
            "rss_kb": proc.get("rss_kb", 0),
            "vss_kb": proc.get("vss_kb", 0),
        }
    return result


def get_dmabuf(snap: dict) -> dict:
    """Return {allocator: size_kb} from debugfs.dmabuf."""
    src = snap.get("sources", {}).get("debugfs", {}).get("dmabuf", {})
    if not src.get("available"):
        return {}
    parsed = src.get("parsed", {})
    return {
        "total_kb": parsed.get("total_kb", 0),
        "by_allocator": parsed.get("by_allocator", {}),
    }


def get_kgsl(snap: dict) -> dict:
    """Return KGSL info from debugfs.kgsl."""
    src = snap.get("sources", {}).get("debugfs", {}).get("kgsl", {})
    if not src.get("available"):
        return {"total_kb": 0, "by_process": []}
    parsed = src.get("parsed", {})
    return {
        "total_kb": parsed.get("total_kb", 0),
        "by_process": {
            p.get("name", "unknown"): p.get("kb", 0)
            for p in parsed.get("by_process", [])
        },
    }


# ---------------------------------------------------------------------------
# Diff computations
# ---------------------------------------------------------------------------

def compute_process_diff(cur_procs: dict, ref_procs: dict,
                          pss_pct: float, pss_mb: float) -> tuple[list, list, list, list]:
    """
    Compute per-process PSS deltas.
    Returns (process_diff, new_processes, exited_processes, top_growers).
    """
    all_names = set(cur_procs) | set(ref_procs)
    diffs = []
    new_procs = []
    exited_procs = []

    for name in sorted(all_names):
        if name in cur_procs and name in ref_procs:
            ref_pss = ref_procs[name]["pss_kb"]
            cur_pss = cur_procs[name]["pss_kb"]
            delta_pss = cur_pss - ref_pss
            if ref_pss > 0:
                delta_pct = round((delta_pss / ref_pss) * 100, 2)
            else:
                delta_pct = 100.0 if cur_pss > 0 else 0.0
            flagged = (
                delta_pct > pss_pct and abs(delta_pss) / 1024 >= pss_mb
            )
            diffs.append({
                "pid": cur_procs[name]["pid"],
                "name": name,
                "ref_pss_kb": ref_pss,
                "cur_pss_kb": cur_pss,
                "delta_pss_kb": delta_pss,
                "delta_pct": delta_pct,
                "ref_rss_kb": ref_procs[name]["rss_kb"],
                "cur_rss_kb": cur_procs[name]["rss_kb"],
                "flagged": flagged,
            })
        elif name in cur_procs:
            new_procs.append({
                "pid": cur_procs[name]["pid"],
                "name": name,
                "pss_kb": cur_procs[name]["pss_kb"],
            })
        else:
            exited_procs.append({
                "pid": ref_procs[name]["pid"],
                "name": name,
                "pss_kb": ref_procs[name]["pss_kb"],
            })

    diffs.sort(key=lambda x: x["delta_pss_kb"], reverse=True)
    top_growers = [
        {"name": d["name"], "delta_pss_kb": d["delta_pss_kb"], "delta_pct": d["delta_pct"]}
        for d in diffs if d.get("flagged")
    ][:10]
    return diffs, new_procs, exited_procs, top_growers


def compute_dmabuf_diff(cur_dma: dict, ref_dma: dict) -> dict:
    """Compute DMA-BUF allocator deltas."""
    cur_total = cur_dma.get("total_kb", 0)
    ref_total = ref_dma.get("total_kb", 0)
    cur_alloc = cur_dma.get("by_allocator", {})
    ref_alloc = ref_dma.get("by_allocator", {})
    all_allocs = set(cur_alloc) | set(ref_alloc)
    by_allocator = []
    for alloc in sorted(all_allocs):
        ref_kb = ref_alloc.get(alloc, 0)
        cur_kb = cur_alloc.get(alloc, 0)
        by_allocator.append({
            "allocator": alloc,
            "ref_kb": ref_kb,
            "cur_kb": cur_kb,
            "delta_kb": cur_kb - ref_kb,
        })
    by_allocator.sort(key=lambda x: x["delta_kb"], reverse=True)
    return {
        "total_ref_kb": ref_total,
        "total_cur_kb": cur_total,
        "delta_kb": cur_total - ref_total,
        "by_allocator": by_allocator,
    }


def compute_kgsl_diff(cur_kgsl: dict, ref_kgsl: dict) -> dict:
    """Compute KGSL GPU memory deltas."""
    cur_total = cur_kgsl.get("total_kb", 0)
    ref_total = ref_kgsl.get("total_kb", 0)
    cur_procs = cur_kgsl.get("by_process", {})
    ref_procs = ref_kgsl.get("by_process", {})
    all_procs = set(cur_procs) | set(ref_procs)
    by_process = []
    for name in sorted(all_procs):
        ref_kb = ref_procs.get(name, 0)
        cur_kb = cur_procs.get(name, 0)
        by_process.append({
            "name": name,
            "ref_kb": ref_kb,
            "cur_kb": cur_kb,
            "delta_kb": cur_kb - ref_kb,
        })
    by_process.sort(key=lambda x: x["delta_kb"], reverse=True)
    return {
        "total_ref_kb": ref_total,
        "total_cur_kb": cur_total,
        "delta_kb": cur_total - ref_total,
        "by_process": by_process,
    }


def compute_findings(proc_diff: list, dmabuf_diff: dict,
                     kgsl_diff: dict, pss_mb: float) -> list:
    """Generate findings from userspace diff analysis."""
    findings = []

    # Flagged process leaks
    flagged = [p for p in proc_diff if p.get("flagged")]
    for proc in flagged[:5]:
        delta_mb = proc["delta_pss_kb"] / 1024
        findings.append({
            "severity": "WARNING" if delta_mb < 200 else "CRITICAL",
            "message": (
                f"Process '{proc['name']}' PSS grew by {delta_mb:.1f} MB "
                f"({proc['delta_pct']:+.1f}%) -- possible userspace memory leak"
            ),
        })

    # DMA-BUF growth
    dma_delta_mb = dmabuf_diff["delta_kb"] / 1024
    if dma_delta_mb >= pss_mb:
        top_alloc = sorted(
            dmabuf_diff["by_allocator"], key=lambda x: x["delta_kb"], reverse=True
        )
        top_name = top_alloc[0]["allocator"] if top_alloc else "unknown"
        findings.append({
            "severity": "WARNING",
            "message": (
                f"DMA-BUF total grew by {dma_delta_mb:.1f} MB -- "
                f"top allocator: {top_name}"
            ),
        })

    # KGSL growth
    kgsl_delta_mb = kgsl_diff["delta_kb"] / 1024
    if kgsl_delta_mb >= pss_mb:
        top_proc = sorted(
            kgsl_diff["by_process"], key=lambda x: x["delta_kb"], reverse=True
        )
        top_name = top_proc[0]["name"] if top_proc else "unknown"
        findings.append({
            "severity": "WARNING",
            "message": (
                f"KGSL GPU memory grew by {kgsl_delta_mb:.1f} MB -- "
                f"top process: {top_name}"
            ),
        })

    return findings


# ---------------------------------------------------------------------------
# Report writers
# ---------------------------------------------------------------------------

def write_json(report: dict, output_dir: str):
    path = os.path.join(output_dir, "userspace_diff_report.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(f"[userspace-diff] JSON  -> {path}")


def write_txt(report: dict, output_dir: str):
    path = os.path.join(output_dir, "userspace_diff_report.txt")
    lines = [
        "Userspace Memory Diff Report",
        "=" * 70,
        "",
        "TOP PROCESS PSS CHANGES (flagged)",
        f"{'Process':<35} {'Ref PSS MB':>12} {'Cur PSS MB':>12} {'Delta MB':>10} {'Delta %':>9}",
        "-" * 80,
    ]
    for p in report["top_pss_growers"]:
        ref_mb = next(
            (x["ref_pss_kb"] for x in report["process_diff"] if x["name"] == p["name"]), 0
        ) / 1024
        cur_mb = next(
            (x["cur_pss_kb"] for x in report["process_diff"] if x["name"] == p["name"]), 0
        ) / 1024
        lines.append(
            f"{p['name']:<35} {ref_mb:>12.1f} {cur_mb:>12.1f} "
            f"{p['delta_pss_kb']/1024:>+10.1f} {p['delta_pct']:>+9.1f}%"
        )
    dma = report["dmabuf_diff"]
    lines += [
        "",
        "DMA-BUF SUMMARY",
        f"  Reference: {dma['total_ref_kb']/1024:.1f} MB",
        f"  Current:   {dma['total_cur_kb']/1024:.1f} MB",
        f"  Delta:     {dma['delta_kb']/1024:+.1f} MB",
    ]
    kgsl = report["kgsl_diff"]
    lines += [
        "",
        "KGSL GPU MEMORY SUMMARY",
        f"  Reference: {kgsl['total_ref_kb']/1024:.1f} MB",
        f"  Current:   {kgsl['total_cur_kb']/1024:.1f} MB",
        f"  Delta:     {kgsl['delta_kb']/1024:+.1f} MB",
    ]
    if report["findings"]:
        lines += ["", "FINDINGS", "-" * 40]
        for f in report["findings"]:
            lines.append(f"  [{f['severity']}] {f['message']}")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"[userspace-diff] TXT   -> {path}")


def write_html(report: dict, output_dir: str):
    path = os.path.join(output_dir, "userspace_diff_report.html")
    proc_rows = ""
    for p in report["process_diff"][:50]:
        color = "background:#ffe0e0" if p.get("flagged") else ""
        proc_rows += (
            f"<tr style='{color}'>"
            f"<td>{p['name']}</td>"
            f"<td style='text-align:right'>{p['ref_pss_kb']/1024:.1f}</td>"
            f"<td style='text-align:right'>{p['cur_pss_kb']/1024:.1f}</td>"
            f"<td style='text-align:right'>{p['delta_pss_kb']/1024:+.1f}</td>"
            f"<td style='text-align:right'>{p['delta_pct']:+.1f}%</td>"
            f"<td>{'[!]' if p.get('flagged') else ''}</td>"
            f"</tr>\n"
        )
    dma_rows = ""
    for a in report["dmabuf_diff"]["by_allocator"][:20]:
        color = "background:#ffe0e0" if a["delta_kb"] > 0 else ""
        dma_rows += (
            f"<tr style='{color}'>"
            f"<td>{a['allocator']}</td>"
            f"<td style='text-align:right'>{a['ref_kb']/1024:.1f}</td>"
            f"<td style='text-align:right'>{a['cur_kb']/1024:.1f}</td>"
            f"<td style='text-align:right'>{a['delta_kb']/1024:+.1f}</td>"
            f"</tr>\n"
        )
    findings_html = "".join(
        f"<li style='background:{'#ffe0e0' if f['severity']=='CRITICAL' else '#fff8e0'};padding:4px'>"
        f"[{f['severity']}] {f['message']}</li>\n"
        for f in report["findings"]
    )
    html = f"""<!DOCTYPE html>
<html><head><meta charset='utf-8'><title>Userspace Memory Diff</title>
<style>body{{font-family:monospace;margin:20px}}
table{{border-collapse:collapse;width:100%}}
th,td{{border:1px solid #ccc;padding:4px 8px}}th{{background:#f0f0f0}}</style></head>
<body>
<h1>Userspace Memory Diff Report</h1>
<h2>Process PSS Changes (top 50)</h2>
<table><tr><th>Process</th><th>Ref PSS MB</th><th>Cur PSS MB</th>
<th>Delta MB</th><th>Delta %</th><th>Flag</th></tr>
{proc_rows}</table>
<h2>DMA-BUF by Allocator (top 20)</h2>
<table><tr><th>Allocator</th><th>Ref MB</th><th>Cur MB</th><th>Delta MB</th></tr>
{dma_rows}</table>
{'<h2>Findings</h2><ul>' + findings_html + '</ul>' if findings_html else ''}
</body></html>"""
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"[userspace-diff] HTML  -> {path}")


def write_xlsx(report: dict, output_dir: str):
    try:
        import openpyxl
        from openpyxl.styles import PatternFill, Font
    except ImportError:
        print("[userspace-diff] openpyxl not installed -- skipping XLSX")
        return
    path = os.path.join(output_dir, "userspace_diff_report.xlsx")
    wb = openpyxl.Workbook()

    ws = wb.active
    ws.title = "Process Diff"
    ws.append(["Process", "Ref PSS KB", "Cur PSS KB", "Delta PSS KB", "Delta %", "Flagged"])
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for p in report["process_diff"]:
        ws.append([p["name"], p["ref_pss_kb"], p["cur_pss_kb"],
                   p["delta_pss_kb"], p["delta_pct"], p.get("flagged", False)])
        if p.get("flagged"):
            for cell in ws[ws.max_row]:
                cell.fill = PatternFill("solid", fgColor="FFE0E0")

    ws2 = wb.create_sheet("DMA-BUF Diff")
    ws2.append(["Allocator", "Ref KB", "Cur KB", "Delta KB"])
    for a in report["dmabuf_diff"]["by_allocator"]:
        ws2.append([a["allocator"], a["ref_kb"], a["cur_kb"], a["delta_kb"]])

    ws3 = wb.create_sheet("KGSL Diff")
    ws3.append(["Process", "Ref KB", "Cur KB", "Delta KB"])
    for p in report["kgsl_diff"]["by_process"]:
        ws3.append([p["name"], p["ref_kb"], p["cur_kb"], p["delta_kb"]])

    wb.save(path)
    print(f"[userspace-diff] XLSX  -> {path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Userspace memory diff between two MemorySnapshot files."
    )
    parser.add_argument("--current", required=True, help="Current snapshot.json")
    parser.add_argument("--reference", required=True, help="Reference snapshot.json")
    parser.add_argument("--output-dir", default=".", help="Output directory")
    parser.add_argument("--pss-growth-pct", type=float, default=50.0,
                        help="PSS growth %% threshold for flagging (default: 50)")
    parser.add_argument("--pss-growth-mb", type=float, default=20.0,
                        help="PSS absolute growth MB threshold (default: 20)")
    parser.add_argument("--format", default="json",
                        help="Comma-separated output formats: json,txt,html,xlsx (default: json)")
    args = parser.parse_args()

    cur = load_snapshot(args.current)
    ref = load_snapshot(args.reference)
    os.makedirs(args.output_dir, exist_ok=True)

    cur_procs = get_processes(cur)
    ref_procs = get_processes(ref)
    cur_dma = get_dmabuf(cur)
    ref_dma = get_dmabuf(ref)
    cur_kgsl = get_kgsl(cur)
    ref_kgsl = get_kgsl(ref)

    proc_diff, new_procs, exited_procs, top_growers = compute_process_diff(
        cur_procs, ref_procs, args.pss_growth_pct, args.pss_growth_mb
    )
    dmabuf_diff = compute_dmabuf_diff(cur_dma, ref_dma)
    kgsl_diff = compute_kgsl_diff(cur_kgsl, ref_kgsl)
    findings = compute_findings(proc_diff, dmabuf_diff, kgsl_diff, args.pss_growth_mb)

    report = {
        "schema_version": "1.0.0",
        "current_snapshot_id": cur.get("snapshot_id", ""),
        "reference_snapshot_id": ref.get("snapshot_id", ""),
        "process_diff": proc_diff,
        "dmabuf_diff": dmabuf_diff,
        "kgsl_diff": kgsl_diff,
        "new_processes": new_procs,
        "exited_processes": exited_procs,
        "top_pss_growers": top_growers,
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

    flagged_count = sum(1 for p in proc_diff if p.get("flagged"))
    print(f"\n[userspace-diff] {flagged_count} flagged process(es), "
          f"{len(new_procs)} new, {len(exited_procs)} exited, "
          f"{len(findings)} finding(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
#!/usr/bin/env python3
r"""
report.py -- per-device JSON history + regenerated HTML report.

This is the `report` stage of the `bootbench` skill (see the root
`SKILL.md`): standalone JSON/HTML report maintenance (re-render the HTML,
or manually append a run). No device/serial console involved. Only needed
when `capture.py` isn't being run, since `capture.py` already records and
renders its own data as part of collecting it.

Deliberately kept deterministic, unlike capture.py's retry/poll loops
(see its module docstring): this module's own docstring makes
byte-for-byte reproducibility a documented contract --
"bootchart-overview-<slug>.html is ALWAYS fully derived from the JSON by
this script -- never hand-authored. Re-running `render` regenerates it
byte-for-byte from whatever is currently in the JSON." Randomized output
here would silently break that contract (every render of the same JSON
should diff clean against the last) for no benefit -- there is no hardware
race to spread retries across, since no device or network call happens in
this module at all.

Run with the ARM64 Python launcher on this machine (`py -3`), or with a
regular Windows Python install (`python3`):
    py -3 report.py --report-cmd render --target iq-9075-evk
    py -3 report.py --report-cmd add-run --run-json new_run.json --target iq-9075-evk

bootchart-data-<slug>.json is the only file ever hand-edited (by appending a
run). bootchart-overview-<slug>.html is ALWAYS fully derived from the JSON
by this script -- never hand-authored. Re-running `render` regenerates it
byte-for-byte from whatever is currently in the JSON.

Run object schema:
{
  "timestamp": "YYYY-MM-DD HH:MM",
  "metrics": {
    "nhlos":           {"value": "5.035 s", "note": "4.318 s firmware + 0.717 s loader"},
    "kernel":          {"value": "1.573 s", "note": ""},
    "initramfs":       {"value": "0.458 s", "note": "0.092 s -> 0.550 s"},
    "sysinit_svc":     {"value": "2.734 s", "note": "0.550 s -> 3.284 s",
                         "hitters": [{"name": "systemd-tmpfiles-setup.service", "time": "0.057 s"}, ...]},
    "total_sysinit":   {"value": "9.342 s", "note": ""},
    "total_multiuser": {"value": "19.005 s", "note": "~19.79 s incl. graphical.target",
                         "hitters": [{"name": "android-tools-adbd.service", "time": "10.416 s"}, ...]}
  },
  "critical_chain": ["docker.service", "network-online.target", "..."]   // optional, kept for backup/.txt context
}
A metric row's `hitters` list (where present) IS rank -- position 0 is #1, NOT a fixed identity
across runs. NHLOS/kernel/initramfs carry no `hitters` key: there's no per-component timing source
for them today (no initcall_debug on this build, no bootloader trace).

Older entries from before hitters were merged into the metrics table may still carry a flat
top-level "hitters" list instead of a nested one. Rendering falls back to treating that as
total_multiuser's hitters, so no data migration is needed.

Exactly ONE column is rendered per build: the run's single displayed boot (the per-stage
"default-median" boot composed by capture.build_median_boot -- each stage's value/note/hitters
taken from whichever default boot was the median FOR THAT STAGE). Debug boots are never a
displayed column; they are captured only for on-demand deeper investigation when a regression
is seen. A top-level "compare_to" field (a build_path/label) names the single reference build
every other column's delta is measured against; absent/unknown -> the first recorded build is
the baseline.

A per-run "device_info" (sibling of "timestamp"/"build_path"/"boots" within a run entry),
set from capture.collect_device_info() right after login during that run's capture, plus a
"serial" field set separately by capture.py from `adb devices`'s own device id once adb is
up (NOT a sysfs/device-read value -- see capture.py's wait_for_adb_device) -- NOT a
top-level field, since Machine/SoC/OS/Kernel/Serial/Captured genuinely differ build-to-build (a
device reflashed with a new nightly can carry a different kernel/OS version):
{
  "timestamp": "2026-10-01 14:32", "build_path": "...", "boots": [...],
  "device_info": {
    "machine": "Qualcomm Technologies, Inc. Lemans EVK",
    "soc": "QCS9075 rev 2.0",
    "os": "Qualcomm Linux Reference Distro (SELinux-enabled) (OTA-enabled)",
    "kernel": "7.2.0-01462-gd49c33864d06",
    "serial": "0123456789ABCDEF",
    "captured": "2026-10-01 14:32:05"
  }
}
Serial is the device id exactly as printed in `adb devices`' first column (what `adb -s
<serial>` would target) -- not anything read off the device over serial console, since that
id (e.g. a SoC-level serial_number) isn't what adb/fastboot actually address the device by.
The report is a stack of independent collapsible cards (memory-skills style; one column per
captured build/run in each, sharing bcol-<i> column classes so the one compare control filters
them all -- see render_dashboard): Device Information, Boot Time Summary (stage-wise numbers
only -- no high hitters), and one analysis card per boot stage (Firmware + Loader / Kernel /
Initramfs / sysinit / multi-user.target -- each carrying that stage's note and ranked high
hitters). Each card collapses from its navy header bar. Any
device_info field that couldn't be read is "-"; a run with no device_info at all (older entries,
or add-run) shows "-" for every field in its column; if NO run in the whole history carries
device_info, the Device Information card is omitted entirely (the rest still render). A legacy
top-level "device_info" (from an earlier version that stored one snapshot, overwritten every
capture) is migrated onto the latest run on load.

Two-build compare (SINGLE control, in the Boot Time Summary card): when more than two builds are
on record, each build's column header in that card carries a "compare" checkbox. Ticking exactly
two narrows EVERY card to those two build columns and shows their pair-wise delta (the
later-picked build vs the earlier-picked one); clearing the picks restores all builds and the
reference-baseline deltas. This is purely client-side view state (see SCRIPT) -- it never
changes what render_html emits, so the byte-for-byte determinism contract above still holds.
"""

from __future__ import annotations

import argparse
import html
import json
import logging
import re
import sys
from pathlib import Path, PureWindowsPath

# boot_logger.py lives in capture/scripts/ (this folder is git-ignored apart from report.py, so a new file here
# would never be committed). Imported from capture.py that folder is already on sys.path; run directly it is not.
try:
    import boot_logger
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "capture" / "scripts"))
    import boot_logger
from boot_logger import boot_log, say

BASE_DIR = Path(__file__).resolve().parent
BOOT_CHARTS_DIR = BASE_DIR / "Boot-Charts"  # flat: every device's bootchart-data/-overview files land directly here, no per-device subdir
DEFAULT_DATA = BOOT_CHARTS_DIR / "bootchart-data.json"
DEFAULT_HTML = BOOT_CHARTS_DIR / "bootchart-overview.html"
BOOT_LOGS_DIR = BASE_DIR / "Boot-Logs"  # nested Boot-Logs/<target>/<build-folder>/<timestamp>.txt

MAX_RUNS = 30  # bootchart-data.json / .html keep only the most recent N runs;
               # full history lives on in Boot-Logs/*.txt regardless of this cap.

METRIC_ROWS = [
    ("nhlos", "NHLOS (PBL/SBL/XBL firmware + ABL loader)", False),
    ("kernel", "Kernel time", False),
    ("initramfs", "Initramfs (<code>Run /init</code> &rarr; epoch advance)", False),
    ("sysinit_svc", "systemd &rarr; sysinit.target", False),
    ("total_sysinit", "Total time till sysinit.target", True),
    ("total_multiuser", "Total time till multi-user.target", True),
]

# Notes that are identical on every boot (constant text, not derived per-run)
# are shown once under the row's own label instead of being repeated in every
# cell -- see _metric_row_html / _hitters_html.
ROW_CAPTIONS = {
    "initramfs": "dmesg: Run /init → System time advanced to built-in epoch",
    "sysinit_svc": "dmesg epoch advance → journalctl: Reached target System Initialization",
}

DELTA_THRESHOLD = 0.5
TIME_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")


def parse_seconds(value):
    if not value:
        return None
    m = TIME_RE.search(value)
    return float(m.group()) if m else None


def format_delta(prev_value, cur_value):
    """Return (label, css_class) for the delta annotation, or ("", "") if not computable."""
    p, c = parse_seconds(prev_value), parse_seconds(cur_value)
    if p is None or c is None:
        return "", ""
    delta = c - p
    if delta >= DELTA_THRESHOLD:
        cls = "regressed"
    elif delta <= -DELTA_THRESHOLD:
        cls = "improved"
    else:
        cls = "unchanged"
    sign = "+" if delta >= 0 else "−"
    return f"({sign}{abs(delta):.3f} s)", cls


def esc(value):
    return html.escape(str(value), quote=False)


def load_data(data_path):
    if not data_path.exists():
        return {"device": "unknown", "runs": []}
    with open(data_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    # One-time migration: device_info used to be stored once at the top level
    # (overwritten on every capture), which lost the fact that OS/kernel/
    # captured-time genuinely differ build-to-build. It's now stored per-run
    # (see add_run / pull_and_record). Attach any legacy top-level snapshot to
    # the most recent run instead of discarding it, then drop the stale key.
    legacy_device_info = data.pop("device_info", None)
    if legacy_device_info and data.get("runs"):
        data["runs"][-1].setdefault("device_info", legacy_device_info)
        boot_log.info("Moved the legacy top-level device_info of %s onto its most recent run", data_path)
    return data


def save_data(data, data_path):
    data_path.parent.mkdir(parents=True, exist_ok=True)
    with open(data_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    boot_log.info("Saved %d run(s) to %s", len(data.get("runs", [])), data_path)


def _validate_boot(boot):
    required = {"timestamp", "metrics"}
    missing = required - boot.keys()
    if missing:
        raise ValueError(f"boot object missing required keys: {missing}")
    missing_metrics = {k for k, _, _ in METRIC_ROWS} - boot["metrics"].keys()
    if missing_metrics:
        raise ValueError(f"boot.metrics missing required keys: {missing_metrics}")


def add_run(data, run):
    if "boots" in run:
        required_top = {"timestamp", "build_path", "boots"}
        missing = required_top - run.keys()
        if missing:
            raise ValueError(f"multi-boot entry missing required keys: {missing}")
        if not run["boots"]:
            raise ValueError("multi-boot entry has an empty 'boots' list")
        for boot in run["boots"]:
            _validate_boot(boot)
    else:
        _validate_boot(run)
    runs = data.setdefault("runs", [])
    runs.append(run)
    dropped = len(runs) - MAX_RUNS
    del runs[:-MAX_RUNS]  # trim from the front; full history is preserved in Boot-Logs/*.txt
    if dropped > 0:
        boot_log.info("Dropped the %d oldest run(s) from the report data (it keeps the latest %d); they remain in "
                      "Boot-Logs", dropped, MAX_RUNS)
    return data


def _displayed_boot(run):
    """The single boot shown for a run: its default/median boot. Debug-phase
    boots are NEVER displayed -- they exist only for on-demand deeper
    regression debugging (see SKILL.md), not as their own comparable column.
    A run captured by the current capture.py already carries exactly one
    boot (the per-stage `default-median`); a legacy run that stored a debug
    column alongside the default one collapses here to just its default
    column; a legacy flat single-boot entry is itself the displayed boot."""
    boots = run.get("boots") or [run]
    non_debug = [b for b in boots if b.get("phase") != "debug"]
    chosen = non_debug or boots
    return chosen[0]


def _reference_index(runs, compare_to=None):
    """Index of the SINGLE reference build every other column is compared
    against: the run whose build_path == compare_to, else the FIRST recorded
    run (the default baseline -- the user's "compare against the first build,
    not all previous builds" rule). An unknown compare_to falls back to the
    first run. None when there are no runs."""
    if not runs:
        return None
    if compare_to:
        for i, r in enumerate(runs):
            if r.get("build_path") == compare_to:
                return i
    return 0


def _flatten(runs, compare_to=None):
    """One record per run -- the run's single displayed (default/median)
    boot, with debug boots dropped so exactly ONE column is rendered per
    build. Each record: {"boot", "run", "idx", "is_ref"}, where is_ref marks
    the comparison-baseline column. Deltas are measured against that baseline
    column (not the immediately preceding column), so every build's numbers
    read as a regression/improvement relative to the one reference build."""
    ref_idx = _reference_index(runs, compare_to)
    return [
        {"boot": _displayed_boot(run), "run": run, "idx": i, "is_ref": i == ref_idx}
        for i, run in enumerate(runs)
    ]


def _metric_hitters(boot, key):
    """Returns the hitters list for a given metric row, or [] if none.
    Legacy entries (captured before hitters were merged into the metrics
    table) carry a flat top-level "hitters" list -- treated as
    total_multiuser's hitters, since that's what it always meant before."""
    m = boot["metrics"].get(key, {})
    if "hitters" in m:
        return m["hitters"]
    if key == "total_multiuser":
        return boot.get("hitters") or []
    return []


def _format_run_txt(target, run):
    """Human-readable dump of a single run, for the Boot-Logs/ backup -- the
    full-history record that survives bootchart-data.json's MAX_RUNS trim."""
    lines = [
        f"Device: {target}",
        f"Timestamp: {run['timestamp']}",
        f"Build path: {run.get('build_path', '')}",
    ]
    if run.get("phase"):
        lines.append(f"Phase: {run['phase']} (boot {run.get('log_name', '').rsplit('-', 1)[-1]})")
    lines += ["", "Metrics:"]
    for key, label, _ in METRIC_ROWS:
        m = run["metrics"].get(key, {})
        note = f"  ({m['note']})" if m.get("note") else ""
        lines.append(f"  {label}: {m.get('value', '')}{note}")
        for i, h in enumerate(_metric_hitters(run, key)):
            h_note = f"  ({h['note']})" if h.get("note") else ""
            lines.append(f"    #{i + 1}. {h['name']}: {h['time']}{h_note}")

    chain = run.get("critical_chain")
    if chain:
        lines.append("")
        lines.append("Critical chain: " + " -> ".join(chain))

    if run.get("source"):
        lines.append("")
        lines.append("Source: " + run["source"])

    return "\n".join(lines) + "\n"


def boot_logs_run_dir(target, build_path, boot_logs_dir=BOOT_LOGS_DIR):
    """Returns the nested Boot-Logs/<target>/<build-folder-name> directory for
    a given target + build_path, shared by save_run_backup's per-boot .txt
    backups and boot-capture's pulled raw-log folders (Logs-1, Logs-2, ...) so
    both land side-by-side in the same directory."""
    return boot_logs_dir / target / _build_folder_name(build_path) if build_path else boot_logs_dir


def save_run_backup(target, run, boot_logs_dir=BOOT_LOGS_DIR):
    """Writes a permanent per-run backup to
    Boot-Logs/<target>/<build-folder-name>/<timestamp>.txt, since
    bootchart-data.json only retains the most recent MAX_RUNS entries. Adds a
    numeric suffix if a backup for the same minute-granularity timestamp
    already exists (e.g. consecutive boots in a multi-boot entry can finish
    within the same minute), so no boot's backup is silently overwritten.
    Pre-existing flat backups directly under boot_logs_dir (from before this
    nested layout) are left in place -- only new backups go into the nested
    <target>/<build-folder> path."""
    build_path = run.get("build_path", "")
    run_dir = boot_logs_run_dir(target, build_path, boot_logs_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    safe_ts = run["timestamp"].replace(":", "-")
    txt_path = run_dir / f"{safe_ts}.txt"
    n = 2
    while txt_path.exists():
        txt_path = run_dir / f"{safe_ts}_{n}.txt"
        n += 1
    txt_path.write_text(_format_run_txt(target, run), encoding="utf-8")
    return txt_path


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

CSS = """
  :root {
    --bg: #f4f6f9;
    --panel: #ffffff;
    --panel-alt: #eef3fa;
    --border: #c8d8ea;
    --border-soft: #dce7f2;
    --text: #1a2733;
    --muted: #5a6b7d;
    --accent: #2c6fad;
    --navy: #1a3a5c;
    --navy-hover: #22507a;
    --good: #1e7e34;
    --good-bg: #e8f8e8;
    --warn: #8a6d1d;
    --warn-bg: #fef8e0;
    --bad: #b02a37;
    --bad-bg: #fde8e8;
    --zebra: #f6f9fc;
    --row-hover: #eef4fb;
    --mono: "SF Mono", "Cascadia Mono", "Segoe UI Mono", Consolas, monospace;
    --sans: "Segoe UI", -apple-system, system-ui, Roboto, Helvetica, Arial, sans-serif;
  }
  * { box-sizing: border-box; }
  html { color-scheme: light; }
  body {
    margin: 0;
    padding: 0;
    background: var(--bg);
    color: var(--text);
    font-family: var(--sans);
    line-height: 1.55;
    -webkit-font-smoothing: antialiased;
    text-rendering: optimizeLegibility;
  }
  /* Page shell stays a calm, centered column (Linear/Apple-notes restraint);
     only the wide run-by-run tables scroll, inside their own section body. */
  .page { max-width: 1960px; margin: 0 auto; padding: 48px 44px 72px; }

  header.masthead { margin-bottom: 30px; }
  h1 { font-size: 1.7rem; font-weight: 640; letter-spacing: -0.015em; color: var(--navy); margin: 0 0 12px; }
  .subtitle { color: var(--muted); font-size: 0.92rem; line-height: 1.6; margin: 0; max-width: 78ch; }
  .subtitle code { font-family: var(--mono); font-size: 0.84em; background: var(--panel-alt); color: var(--navy); padding: 1.5px 6px; border-radius: 5px; border: 1px solid var(--border); }

  /* Signature memory-skills section card: white panel, soft shadow, with a
     navy header bar that is ALSO the collapse control for that card (clicking
     it hides the card's table body -- see toggleCard in SCRIPT). The dashboard
     is a stack of these cards (Device Information, Boot Time Summary, one per
     boot stage). */
  .section-block { background: var(--panel); border: 1px solid var(--border); border-radius: 12px;
    box-shadow: 0 1px 2px rgba(16,40,70,0.05), 0 12px 28px -18px rgba(16,40,70,0.28);
    overflow: hidden; margin-bottom: 24px; }
  .section-header { display: flex; align-items: center; gap: 11px; background: var(--navy);
    color: #fff; padding: 13px 20px; cursor: pointer; user-select: none; font-weight: 650;
    font-size: 0.9rem; letter-spacing: 0.01em; }
  .section-header:hover { background: var(--navy-hover); }
  .section-header:focus-visible { outline: 2px solid #a9cdf0; outline-offset: -2px; }
  .section-toggle { display: inline-block; width: 16px; text-align: center; font-weight: 600; opacity: 0.85; }
  .section-title { flex: 1; }
  .section-body { overflow-x: auto; }
  .section-body.body-collapsed { display: none; }

  table { border-collapse: collapse; width: 100%; background: var(--panel); font-size: 0.82rem; }
  th, td { text-align: left; padding: 12px 26px; border: 1px solid var(--border-soft); white-space: nowrap; vertical-align: top; }
  th:first-child, td:first-child { width: 280px; white-space: normal; font-weight: 500; }
  th { background: var(--accent); color: #ffffff; font-size: 0.7rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; vertical-align: bottom; }
  th:first-child { background: var(--navy); }
  th.run-col { color: #eaf1fb; text-transform: none; letter-spacing: normal; font-size: 0.82rem; font-weight: 600; min-width: 380px; }
  th.run-col.latest { box-shadow: inset 0 -3px 0 #a9cdf0; }
  tbody tr:not(.total):nth-child(odd) td { background: var(--zebra); }
  tbody tr:not(.total):nth-child(even) td { background: var(--panel); }
  tbody tr:not(.total):hover td { background: var(--row-hover); }
  tr.total td { font-weight: 650; color: var(--navy); background: #e4edf8; }
  tr.total:hover td { background: #dce7f6; }
  td.timing { font-family: var(--mono); font-size: 0.88rem; font-variant-numeric: tabular-nums; }
  td.timing .note { display: block; color: var(--muted); font-size: 0.76rem; font-family: var(--sans); white-space: normal; margin-top: 3px; }
  td.timing .delta { font-size: 0.73rem; margin-left: 7px; padding: 1px 7px; border-radius: 999px; font-family: var(--mono); font-variant-numeric: tabular-nums; }
  .delta.unchanged { color: var(--muted); background: var(--panel-alt); }
  .delta.improved { color: var(--good); background: var(--good-bg); }
  .delta.regressed { color: var(--bad); background: var(--bad-bg); }
  th.entry-start, td.entry-start { border-left: 2px solid var(--accent); }
  th.phase-start, td.phase-start { border-left: 1px dashed var(--accent); }
  td:first-child .row-caption { display: block; font-weight: 400; font-size: 0.73rem; color: var(--muted); margin-top: 3px; white-space: normal; line-height: 1.45; }
  th .row-caption { display: block; font-weight: 400; font-size: 0.72rem; color: #c3d6ea; margin-top: 3px; white-space: normal; text-transform: none; letter-spacing: normal; }
  td.timing ol.hitters { list-style: none; margin: 8px 0 0; padding: 0; white-space: normal; }
  td.timing ol.hitters li { font-size: 0.76rem; font-family: var(--sans); color: var(--muted); margin-top: 3px; line-height: 1.45; }
  td.timing ol.hitters li .hitter-name { font-family: var(--mono); color: var(--navy); }
  td.na, span.na { color: #9aa9b8; text-align: center; }

  /* The leftmost "Stage / Field" label column of every data table gets the
     navy header treatment so the stacked cards read as one consistent grid. */
  th.stage-col { background: var(--navy); }

  /* Build filter: ONE disclosure panel at the very top of the page. Opening it
     reveals the full list of recorded builds; tick any number and press Submit
     to narrow EVERY card to just those builds. col-hidden is toggled by the
     client-side script; the default (no-JS / un-submitted) view shows every
     column, so the report is complete without JavaScript. */
  .col-hidden { display: none; }
  .filter-panel { background: var(--panel); border: 1px solid var(--border); border-radius: 12px;
    box-shadow: 0 1px 2px rgba(16,40,70,0.05), 0 12px 28px -18px rgba(16,40,70,0.28);
    margin-bottom: 24px; overflow: hidden; }
  .filter-panel > summary { display: flex; align-items: center; gap: 11px; background: var(--navy);
    color: #fff; padding: 13px 20px; cursor: pointer; user-select: none; font-weight: 650;
    font-size: 0.9rem; letter-spacing: 0.01em; list-style: none; }
  .filter-panel > summary::-webkit-details-marker { display: none; }
  .filter-panel > summary:hover { background: var(--navy-hover); }
  .filter-panel > summary .filter-caret { display: inline-block; width: 16px; text-align: center;
    font-weight: 600; opacity: 0.85; transition: transform 0.15s ease; }
  .filter-panel[open] > summary .filter-caret { transform: rotate(90deg); }
  .filter-panel > summary .filter-title { flex: 1; }
  .filter-panel > summary #filter-status { font-weight: 500; font-size: 0.8rem; color: #c3d6ea;
    text-transform: none; letter-spacing: normal; }
  .filter-body { padding: 18px 20px 20px; }
  .filter-intro { margin: 0 0 14px; font-size: 0.82rem; color: var(--muted); line-height: 1.55; }
  .filter-list { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
    gap: 10px 40px; margin-bottom: 18px; }
  /* align-items: start + min-width:0 keep a long build name inside its own
     grid cell -- without them a full build path overflows the track and lands
     on top of the next build's checkbox (the reported collision). */
  .filter-list label { display: flex; align-items: start; gap: 11px; font-size: 0.86rem;
    color: var(--text); cursor: pointer; padding: 6px 2px; min-width: 0; }
  .filter-list label:hover { color: var(--navy); }
  .filter-list .build-pick { margin: 2px 0 0; vertical-align: middle; cursor: pointer; flex: none; }
  .filter-list .pick-name { flex: 1; min-width: 0; overflow-wrap: anywhere; font-weight: 500; }
  .filter-list .pick-tag { color: var(--muted); font-weight: 400; }
  .filter-actions { display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
    border-top: 1px solid var(--border-soft); padding-top: 16px; }
  .filter-submit { font-family: var(--sans); font-size: 0.8rem; font-weight: 650; color: #fff;
    background: var(--accent); border: none; border-radius: 6px; padding: 7px 16px; cursor: pointer; }
  .filter-submit:hover { background: var(--navy); }
  .filter-reset { font-family: var(--sans); font-size: 0.8rem; font-weight: 600; color: var(--navy);
    background: var(--panel-alt); border: 1px solid var(--border); border-radius: 6px;
    padding: 7px 14px; cursor: pointer; }
  .filter-reset:hover { background: var(--row-hover); }

  .empty-state { background: var(--panel); border: 1px solid var(--border); border-radius: 12px;
    box-shadow: 0 1px 2px rgba(16,40,70,0.05); padding: 32px; color: var(--muted); font-size: 0.95rem; }
  .empty-state code { font-family: var(--mono); font-size: 0.85em; background: var(--panel-alt); color: var(--navy); padding: 1.5px 6px; border-radius: 5px; border: 1px solid var(--border); }

  footer.page-footer { margin-top: 32px; color: #8697a8; font-size: 0.78rem; }
  footer.page-footer code { font-family: var(--mono); font-size: 0.88em; color: var(--muted); }

  @media (max-width: 720px) {
    .page { padding: 28px 16px 48px; }
    h1 { font-size: 1.45rem; }
  }
"""

# Client-side behaviour for the report. All of it is VIEW-time interaction
# (collapse a card, filter which builds are shown) -- it never changes what
# render_html emits, so the byte-for-byte determinism contract in the module
# docstring still holds: this string is a constant, with no state or randomness.
#
# toggleCard: collapse/expand one dashboard card (Device Information, Boot Time
# Summary, or a per-stage analysis card) by hiding its table body. The card's
# navy header bar is the clickable control.
#
# Build filter: ONE control at the very top of the page (a disclosure panel
# listing every recorded build with a checkbox). Tick ANY number of builds and
# press Submit -- every card (device info, summary, all stage cards; they all
# share bcol-<i> column classes) is narrowed to just those builds. Deltas are
# recomputed against the earliest (leftmost) selected build; "Show all builds"
# clears the filter and restores the reference-baseline deltas. Selecting
# none, or all, is equivalent to showing all.
SCRIPT = r"""
  // Collapse/expand one dashboard card by hiding its table body (body-<id>).
  // The card's navy header bar is the clickable control; its glyph flips
  // between '−' (open) and '+' (collapsed).
  function toggleCard(id) {
    var body = document.getElementById('body-' + id);
    if (!body) { return; }
    var collapsed = body.classList.toggle('body-collapsed');
    var glyph = document.getElementById('ctoggle-' + id);
    if (glyph) { glyph.textContent = collapsed ? '+' : '−'; }
    var card = document.getElementById('card-' + id);
    var header = card ? card.querySelector('.section-header') : null;
    if (header) { header.setAttribute('aria-expanded', collapsed ? 'false' : 'true'); }
  }

  function _setColHidden(sel, hidden) {
    var els = document.querySelectorAll(sel);
    for (var i = 0; i < els.length; i++) {
      if (hidden) { els[i].classList.add('col-hidden'); }
      else { els[i].classList.remove('col-hidden'); }
    }
  }

  function _labelFor(idx) {
    var cb = document.querySelector('.build-pick[data-build="' + idx + '"]');
    return (cb && cb.getAttribute('data-label')) ? cb.getAttribute('data-label') : ('build ' + idx);
  }

  function _writeDefault(slot) {
    var t = slot.getAttribute('data-dtext');
    var c = slot.getAttribute('data-dcls');
    slot.innerHTML = t ? ('<span class="delta ' + c + '">' + t + '</span>') : '';
  }

  function _writeDelta(slot, delta, threshold) {
    var cls = (delta >= threshold) ? 'regressed' : (delta <= -threshold ? 'improved' : 'unchanged');
    var sign = (delta >= 0) ? '+' : '−';
    slot.innerHTML = '<span class="delta ' + cls + '">(' + sign + Math.abs(delta).toFixed(3) + ' s)</span>';
  }

  // Recompute every metric row's delta pills. mode 'all' restores the
  // server-rendered deltas (each build vs the reference baseline). mode
  // 'subset' takes a sorted list of selected build indices, uses the first
  // (leftmost/earliest) as the baseline, and shows each other selected build
  // vs that baseline; non-selected columns are blanked (they're hidden anyway).
  function _recomputeDeltas(mode, picked, threshold) {
    var rows = document.querySelectorAll('tr.metric-row');
    var base = (picked && picked.length) ? picked[0] : null;
    var inSet = {};
    if (picked) { for (var p = 0; p < picked.length; p++) { inSet[picked[p]] = true; } }
    for (var r = 0; r < rows.length; r++) {
      var slots = rows[r].querySelectorAll('.delta-slot');
      if (!slots.length) { continue; }
      if (mode === 'all') {
        for (var s = 0; s < slots.length; s++) { _writeDefault(slots[s]); }
        continue;
      }
      var baseSlot = rows[r].querySelector('.delta-slot[data-build="' + base + '"]');
      var baseSec = baseSlot ? parseFloat(baseSlot.getAttribute('data-seconds')) : NaN;
      for (var k = 0; k < slots.length; k++) {
        var slot = slots[k];
        var bld = slot.getAttribute('data-build');
        if (bld === base || !inSet[bld]) {
          slot.innerHTML = '';  // baseline has no delta vs itself; others are hidden
        } else if (!isNaN(baseSec)) {
          var sec = parseFloat(slot.getAttribute('data-seconds'));
          if (isNaN(sec)) { slot.innerHTML = ''; } else { _writeDelta(slot, sec - baseSec, threshold); }
        } else {
          slot.innerHTML = '';
        }
      }
    }
  }

  // Show every build column across every card, with the server-rendered
  // reference-baseline deltas. The default (un-submitted) view.
  function _showAllBuilds() {
    var boxes = document.querySelectorAll('.build-pick');
    for (var j = 0; j < boxes.length; j++) {
      _setColHidden('.bcol-' + boxes[j].getAttribute('data-build'), false);
    }
    _recomputeDeltas('all', null, 0.5);
  }

  // Submit the build filter: read every ticked checkbox and narrow all cards
  // to just those builds. Ticking none, or every build, is the same as "show
  // all". Deltas are recomputed against the earliest selected build.
  function applyFilter() {
    var table = document.getElementById('summary-table');
    if (!table) { return; }
    var threshold = parseFloat(table.getAttribute('data-delta-threshold')) || 0.5;
    var boxes = document.querySelectorAll('.build-pick');
    var status = document.getElementById('filter-status');

    var picked = [];
    for (var i = 0; i < boxes.length; i++) {
      if (boxes[i].checked) { picked.push(boxes[i].getAttribute('data-build')); }
    }
    picked.sort(function (x, y) { return parseInt(x, 10) - parseInt(y, 10); });

    // No selection, or all builds selected -> no filtering to do.
    if (picked.length === 0 || picked.length === boxes.length) {
      _showAllBuilds();
      if (status) {
        status.textContent = (boxes.length ? 'Showing all ' + boxes.length + ' builds' : '');
      }
      return;
    }

    var inSet = {};
    for (var q = 0; q < picked.length; q++) { inSet[picked[q]] = true; }
    for (var b = 0; b < boxes.length; b++) {
      var idx = boxes[b].getAttribute('data-build');
      _setColHidden('.bcol-' + idx, !inSet[idx]);
    }
    _recomputeDeltas('subset', picked, threshold);

    if (status) {
      var noun = (picked.length === 1) ? 'build' : 'builds';
      status.textContent = 'Showing ' + picked.length + ' of ' + boxes.length + ' ' + noun
        + ' (baseline: ' + _labelFor(picked[0]) + ')';
    }
  }

  // "Show all builds" button: clear every tick and restore the full view.
  function resetFilter() {
    var boxes = document.querySelectorAll('.build-pick');
    for (var i = 0; i < boxes.length; i++) { boxes[i].checked = false; }
    _showAllBuilds();
    var status = document.getElementById('filter-status');
    if (status) { status.textContent = (boxes.length ? 'Showing all ' + boxes.length + ' builds' : ''); }
  }
"""


def _boot_header_label(rec):
    """A build's capture timestamp. Kept only as the fallback build identity
    for the rare run that carries no build label at all (see
    _build_display_name); it is no longer shown as a column header on its own."""
    return rec["run"].get("timestamp") or rec["boot"]["timestamp"]


def _build_display_name(rec):
    """How a build is NAMED everywhere the reader tracks it -- the per-build
    column headers of every table and the top-of-page filter list. It's the
    build's own label (the 'Build-<N>' name, or a legacy path with the implied
    '\\performance' tail stripped), which is what a regression is tracked by.
    Falls back to the capture timestamp only for a run with no build label at
    all (older add-run-only JSON)."""
    bp = rec["run"].get("build_path", "")
    return _strip_performance_suffix(bp) if bp else _boot_header_label(rec)


def _boot_header_subtitle(rec, multi):
    """Small subtitle under a column header. With more than one build on
    record, the reference-baseline column (the one every other column's
    deltas are measured against) is labelled so it's obvious which build is
    the comparison point. None otherwise."""
    if multi and rec["is_ref"]:
        return "baseline — compared against"
    return None


def _col_extra_class(flat, i, rec):
    """Every column is now a distinct build (one displayed boot per run), so
    every column after the first gets the thicker accent border that
    separates captured runs."""
    return " entry-start" if i > 0 else ""


def _build_header_cells(flat):
    """Per-build column headers, shared by every card's table (Device
    Information, Boot Time Summary, each stage card). Each
    carries a stable bcol-<i> class (so the SAME column hides/shows together
    across ALL cards when the top-of-page build filter narrows the view),
    data-build for the script, and data-ref on the reference baseline column.
    The filter control itself lives in the top-of-page panel, not here."""
    multi = len(flat) > 1
    n = len(flat)
    cells = []
    for i, rec in enumerate(flat):
        subtitle = _boot_header_subtitle(rec, multi)
        sub_html = f'<span class="row-caption">{esc(subtitle)}</span>' if subtitle else ""
        latest = " latest" if i == n - 1 else ""
        ref_attr = ' data-ref="1"' if rec["is_ref"] else ""
        cells.append(
            f'<th class="run-col bcol-{i}{latest}{_col_extra_class(flat, i, rec)}" '
            f'data-build="{i}"{ref_attr}>{esc(_build_display_name(rec))}{sub_html}</th>'
        )
    return "".join(cells)


def _strip_performance_suffix(build_path):
    """Legacy builds were recorded as a path ending in '...\\performance';
    that segment was implied and dropped from display/paths. Current builds
    are plain auto-incrementing labels ("Build-1", "Build-2", ...) with no
    such suffix, so this is a no-op for them -- kept only so older recorded
    runs still render/path correctly."""
    p = PureWindowsPath(build_path)
    if p.name.lower() == "performance":
        p = p.parent
    return str(p)


def _build_folder_name(build_path):
    return PureWindowsPath(_strip_performance_suffix(build_path)).name or "unknown-build"


def _hitters_html(hitters):
    """Ranked sub-list rendered inside a metric's value cell. Each hitter's
    "note" (e.g. "largest single cost", "critical path"/"off critical path")
    is precomputed at capture time in capture.build_run, not here."""
    if not hitters:
        return ""
    items = []
    for i, h in enumerate(hitters):
        note = h.get("note", "")
        note_html = f" &middot; {esc(note)}" if note else ""
        items.append(
            f'<li class="rank-{i + 1}">#{i + 1} <span class="hitter-name">{esc(h["name"])}</span> '
            f'&mdash; {esc(h["time"])}{note_html}</li>'
        )
    return f'<ol class="hitters">{"".join(items)}</ol>'


DEVICE_INFO_FIELDS = [
    ("machine", "Machine"),
    ("soc", "SoC"),
    ("os", "OS"),
    ("kernel", "Kernel"),
    ("serial", "Serial / IP Address"),
    ("captured", "Captured"),
]


def render_device_table(flat):
    """The 'Device Information' card body -- one row per device_info field
    (Machine/SoC/OS/Serial-or-IP/Kernel/Captured), one cell per build, sharing
    the SAME bcol-<i> column classes as every other card so the single compare
    control filters it too. Returns "" when NO run carries device_info at all
    (older entries, or add-run-only JSON), so render_dashboard simply omits the
    Device Information card in that case. A run missing device_info in a mixed
    history shows '–' in its own column."""
    if not any(rec["run"].get("device_info") for rec in flat):
        return ""
    head = f'<thead><tr><th class="stage-col">Field</th>{_build_header_cells(flat)}</tr></thead>'
    rows = []
    for key, label in DEVICE_INFO_FIELDS:
        cells = "".join(
            f'<td class="timing bcol-{i}{_col_extra_class(flat, i, rec)}" data-build="{i}">'
            f'{esc((rec["run"].get("device_info") or {}).get(key) or "–")}</td>'
            for i, rec in enumerate(flat)
        )
        rows.append(f'<tr><td>{esc(label)}</td>{cells}</tr>')
    return f'<table>{head}<tbody>{"".join(rows)}</tbody></table>'


def _delta_slot_html(i, key, value, ref_value, is_ref):
    """One build cell's delta pill, wrapped in a .delta-slot the client-side
    two-build filter can rewrite. The slot carries data-seconds (this build's
    parsed stage time) plus the server-rendered default delta (data-dtext /
    data-dcls -- this build vs the reference baseline), so the script can both
    recompute a pair-wise delta on demand and restore the default when the
    filter is cleared, without re-parsing any text."""
    seconds = parse_seconds(value)
    sec_attr = f"{seconds:.6f}" if seconds is not None else ""
    dtext, dcls = ("", "") if is_ref else format_delta(ref_value, value)
    inner = f'<span class="delta {dcls}">{esc(dtext)}</span>' if dtext else ""
    return (
        f'<span class="delta-slot" data-build="{i}" data-key="{esc(key)}" '
        f'data-seconds="{sec_attr}" data-dtext="{esc(dtext)}" data-dcls="{dcls}">{inner}</span>'
    )


def _filter_panel(flat):
    """The SINGLE build-filter control, rendered once at the very top of the
    page (above every card) when there's more than one build to choose between.
    A collapsed <details> disclosure: its summary bar opens to reveal the full
    list of recorded builds, each with a checkbox. Ticking any number of builds
    and pressing Submit narrows EVERY card to just those builds (the script
    reads the ticks on Submit -- see applyFilter). "Show all builds" clears it.

    data-build ties each checkbox to its bcol-<i> columns; data-label is the
    build's own name so the status line and baseline note can name it."""
    n = len(flat)
    if n <= 1:
        return ""
    items = []
    for i, rec in enumerate(flat):
        label = _build_display_name(rec)
        tag = " (latest)" if i == n - 1 else (" (baseline)" if rec["is_ref"] else "")
        items.append(
            '<label>'
            f'<input type="checkbox" class="build-pick" data-build="{i}" data-label="{esc(label)}">'
            f'<span class="pick-name">{esc(label)}<span class="pick-tag">{esc(tag)}</span></span>'
            '</label>'
        )
    return (
        '\n  <details class="filter-panel">'
        '<summary><span class="filter-caret" aria-hidden="true">&#9656;</span>'
        '<span class="filter-title">Filter builds</span>'
        '<span id="filter-status"></span></summary>'
        '<div class="filter-body">'
        f'<p class="filter-intro">Pick any number of the {n} recorded builds and press '
        '<strong>Submit</strong> to show only those across every table below. Deltas are '
        'measured against the earliest build you select.</p>'
        f'<div class="filter-list">{"".join(items)}</div>'
        '<div class="filter-actions">'
        '<button type="button" class="filter-submit" onclick="applyFilter()">Submit</button>'
        '<button type="button" class="filter-reset" onclick="resetFilter()">Show all builds</button>'
        '</div></div></details>'
    )


# The per-stage analysis cards: each is one collapsible card whose table holds
# the metric row(s) for that boot stage -- the stage timing + delta and that
# stage's ranked high hitters.
# (card_id, card title, [metric keys from METRIC_ROWS shown in this card]).
# Boot Time Summary shows ALL stage numbers; these cards carry the detail the
# summary deliberately omits (hitters, notes).
STAGE_CARDS = [
    ("firmware", "Firmware + Loader Analysis", ["nhlos"]),
    ("kernel", "Kernel Analysis", ["kernel"]),
    ("initramfs", "Initramfs Analysis", ["initramfs"]),
    ("sysinit", "sysinit Analysis", ["sysinit_svc", "total_sysinit"]),
    ("multiuser", "multi-user.target Analysis", ["total_multiuser"]),
]

_METRIC_META = {key: (label, is_total) for key, label, is_total in METRIC_ROWS}


def _render_card(card_id, title, body_html, collapsed=False):
    """One collapsible dashboard card (memory-skills style): a navy header bar
    that is itself the collapse control (toggleCard hides body-<card_id>),
    wrapping the card's table. collapsed=True renders it minimised ('+' glyph,
    body hidden) so the dashboard can open with only the core cards (Device
    Information, Boot Time Summary) expanded and the rest tucked away -- readers
    expand a detail card only when they need it. Collapse state is purely a
    view default baked into the static HTML; toggleCard flips it at view time
    and never changes the emitted file."""
    glyph = "+" if collapsed else "−"
    body_cls = " body-collapsed" if collapsed else ""
    expanded = "false" if collapsed else "true"
    return (
        f'\n  <section class="section-block" id="card-{card_id}">'
        f'<header class="section-header" onclick="toggleCard(\'{card_id}\')" '
        f'role="button" tabindex="0" aria-controls="body-{card_id}" aria-expanded="{expanded}">'
        f'<span class="section-toggle" id="ctoggle-{card_id}" aria-hidden="true">{glyph}</span>'
        f'<span class="section-title">{esc(title)}</span></header>'
        f'<div class="section-body{body_cls}" id="body-{card_id}">{body_html}</div>'
        f'</section>'
    )


def _metric_row_html(flat, ref_i, key, with_hitters, with_notes):
    """One stage's row: label (+ caption when with_notes) in the first column,
    then each build's value with its delta pill (always, so the compare filter
    can recompute them), optionally the stage note and ranked high hitters."""
    label, is_total = _METRIC_META[key]
    caption = ROW_CAPTIONS.get(key)
    label_html = f'{label}<span class="row-caption">{esc(caption)}</span>' if (with_notes and caption) else label
    ref_value = flat[ref_i]["boot"]["metrics"].get(key, {}).get("value", "") if flat else ""
    cells = []
    for i, rec in enumerate(flat):
        boot = rec["boot"]
        m = boot["metrics"].get(key, {})
        value, note = m.get("value", ""), m.get("note", "")
        delta_slot = _delta_slot_html(i, key, value, ref_value, rec["is_ref"])
        note_html = f'<span class="note">{esc(note)}</span>' if (with_notes and note and note != caption) else ""
        hitters_html = _hitters_html(_metric_hitters(boot, key)) if with_hitters else ""
        cls = f"timing bcol-{i}" + _col_extra_class(flat, i, rec)
        cells.append(f'<td class="{cls}" data-build="{i}">{esc(value)}{delta_slot}{note_html}{hitters_html}</td>')
    row_class = "metric-row total" if is_total else "metric-row"
    return f'<tr class="{row_class}"><td>{label_html}</td>{"".join(cells)}</tr>'


def render_summary_table(flat, ref_i):
    """The Boot Time Summary table -- stage-wise boot numbers only: every
    METRIC_ROWS stage (value + delta), with NO high hitters or notes. Each
    column is headed by the build's own name (see _build_display_name), so
    no separate 'Build' identity row is needed. It carries the
    data-delta-threshold attribute the client-side filter reads (from the
    top-of-page panel) before re-filtering every card."""
    head = f'<thead><tr><th class="stage-col">Stage</th>{_build_header_cells(flat)}</tr></thead>'
    body = []
    for key, _label, _is_total in METRIC_ROWS:
        body.append(_metric_row_html(flat, ref_i, key, with_hitters=False, with_notes=False))
    return (
        f'<table id="summary-table" '
        f'data-delta-threshold="{DELTA_THRESHOLD}">{head}'
        f'<tbody>{"".join(body)}</tbody></table>'
    )


def render_stage_table(flat, ref_i, stage_keys):
    """One per-stage analysis table: the stage's metric row(s) with value +
    delta + stage note + ranked high hitters."""
    head = f'<thead><tr><th class="stage-col">Stage</th>{_build_header_cells(flat)}</tr></thead>'
    body = []
    for key in stage_keys:
        body.append(_metric_row_html(flat, ref_i, key, with_hitters=True, with_notes=True))
    return f'<table>{head}<tbody>{"".join(body)}</tbody></table>'


def render_dashboard(runs, compare_to=None):
    """The full dashboard: a single top-of-page build-filter panel followed by a
    stack of independent collapsible cards (memory-skills style) -- Device
    Information, Boot Time Summary (stage numbers only), and one analysis card
    per boot stage (Firmware+Loader / Kernel / Initramfs / sysinit / multi-user,
    each with its hitters).

    All cards share bcol-<i> column classes, so submitting a build selection in
    the top panel re-filters EVERY card at once. Deltas are measured against the
    single reference baseline (or, under a filter, the earliest selected build).
    Purely view-time interaction never changes this emitted HTML, so the
    module's byte-for-byte determinism contract still holds."""
    flat = _flatten(runs, compare_to)
    ref_i = next((i for i, rec in enumerate(flat) if rec["is_ref"]), 0) if flat else 0

    cards = []
    filter_panel = _filter_panel(flat)
    if filter_panel:
        cards.append(filter_panel)

    # Default view: open with only the two core cards (Device Information, Boot
    # Time Summary) expanded; every detail card (per-stage analysis) starts
    # minimised so readers land on the core numbers and expand a detail card
    # only when they need it. toggleCard flips any card at view time -- this is
    # only the starting state baked into the HTML.
    device_body = render_device_table(flat)
    if device_body:
        cards.append(_render_card("device", "Device Information", device_body))

    cards.append(_render_card("summary", "Boot Time Summary", render_summary_table(flat, ref_i)))

    for card_id, title, stage_keys in STAGE_CARDS:
        table = render_stage_table(flat, ref_i, stage_keys)
        cards.append(_render_card(card_id, title, table, collapsed=True))

    return "".join(cards)


def render_html(data):
    runs = data.get("runs", [])
    device = esc(data.get("device", "unknown device"))

    if not runs:
        sections = (
            '\n  <div class="empty-state">No runs collected yet. Run '
            '<code>report.py --report-cmd add-run --run-json &lt;run.json&gt;</code> '
            'to add the first one.</div>\n'
        )
    else:
        # A stack of collapsible cards (memory-skills style): Device Information,
        # Boot Time Summary (stage numbers only + the single compare control),
        # and one analysis card per boot stage. See render_dashboard.
        sections = render_dashboard(runs, data.get("compare_to"))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Boot Time Analysis &mdash; {device}</title>
<style>{CSS}</style>
</head>
<body>
<div class="page">

  <header class="masthead">
    <h1>Boot Time Analysis</h1>
    <p class="subtitle">Device <code>{device}</code> &mdash; history of collected boot runs. Data source: <code>bootchart-data.json</code>, generated by <code>report.py</code>. Each card collapses from its header; the Boot Time Summary card gives stage-wise numbers, and each per-stage analysis card ranks that stage's high hitters (where measurable).</p>
  </header>
{sections}
  <footer class="page-footer">Generated by <code>bootbench</code> &middot; regenerate anytime with <code>report.py --report-cmd render</code>.</footer>

</div>
<script>{SCRIPT}</script>
</body>
</html>
"""


def render(data_path=DEFAULT_DATA, html_path=DEFAULT_HTML):
    data = load_data(data_path)
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(render_html(data), encoding="utf-8")
    say(f"Rendered {html_path} from {data_path} ({len(data.get('runs', []))} run(s)).")


def _slugify(target: str) -> str:
    return target.replace("-", "").replace("_", "")


def _data_html_paths(target: str):
    slug = _slugify(target)
    base = BOOT_CHARTS_DIR
    return base / f"bootchart-data-{slug}.json", base / f"bootchart-overview-{slug}.html"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def add_report_args(parser):
    """Adds report.py's own-specific flags (not --target, which capture.py
    and report.py each define directly, since both need it standalone) to
    an existing parser."""
    report_group = parser.add_argument_group("report")
    report_group.add_argument("--report-cmd", choices=["render", "add-run"], default="render", help="'render' (default) just regenerates the HTML from the existing JSON; 'add-run' appends --run-json first")
    report_group.add_argument("--run-json", help="Path to a run JSON to append (or '-' for stdin), used with --report-cmd add-run")
    report_group.add_argument("--compare-to", help='Build label of the SINGLE reference build this report is compared against (its timing deltas), e.g. "Build-1". Persisted into the data file so subsequent renders reuse it. Defaults to the first recorded build. Can be set on its own with --report-cmd render to re-baseline an existing report.')
    return parser


def cmd_report(args):
    """Standalone report maintenance: (optionally) append a run JSON or set
    agent-authored analysis text on a boot, then re-render the HTML from the
    JSON. No device involved."""
    boot_log.set_phase("collect")
    if not args.target:
        say("report.py requires --target.", logging.ERROR)
        sys.exit(1)

    data_path, html_path = _data_html_paths(args.target)
    boot_log.info("report.py %s for target %s", args.report_cmd, args.target)

    # --compare-to re-baselines the whole report's timing deltas against a
    # single reference build and is persisted so later renders reuse it.
    # Handled up front so it applies regardless of --report-cmd (including a
    # plain `render` whose only job is to re-baseline).
    if args.compare_to:
        data = load_data(data_path)
        data["compare_to"] = args.compare_to
        save_data(data, data_path)
        say(f"Set comparison baseline to {args.compare_to!r} -> {data_path}")

    if args.report_cmd == "add-run":
        if not args.run_json:
            say("--report-cmd add-run requires --run-json <path|->", logging.ERROR)
            sys.exit(1)
        raw = sys.stdin.read() if args.run_json == "-" else Path(args.run_json).read_text(encoding="utf-8")
        run = json.loads(raw)
        data = load_data(data_path)
        add_run(data, run)
        save_data(data, data_path)
        say(f"Appended run -> {data_path}")

    render(data_path, html_path)
    say(f"Report regenerated -> {html_path}")


def build_parser():
    parser = argparse.ArgumentParser(
        prog="report.py", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--target", help="Target name (e.g. iq-9075-evk), used to resolve bootchart-data-<slug>.json / bootchart-overview-<slug>.html. Required.")
    add_report_args(parser)
    boot_logger.add_log_level_argument(parser)
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    with boot_logger.logged_run(args.log_level, sys.argv):
        cmd_report(args)


if __name__ == "__main__":
    main()

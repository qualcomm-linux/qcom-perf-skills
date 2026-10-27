# Qualcomm Linux Bootbench Skill

AI-powered boot-time capture / report pipeline for Qualcomm Linux SoCs.
Designed to be used through natural language prompts to an AI agent (Cline, Cursor, etc.).
Runs entirely from the **host machine** against a physically-connected target device.

This skill does **not** flash devices. It assumes the target already has
the build under test on it, and only boots/collects boot-time data from it.

**Supported devices:** Qualcomm Linux (QLI) target devices (e.g. `iq-9075-evk`)

**Supported transports:**
- Serial console (COM) + Alpaca TAC (power-cycle) + ADB (log pull) — default
- SSH (`--host`) + soft reboot (power-cycle) + SFTP (log pull) — no TAC/adb needed

**Supported host platforms:** Windows (ARM64 or x64)

---

## Quick Start (2 Minutes)

### Prerequisites
```bash
py -3 -m pip install pyserial comtypes
```
- `pyserial` — serial console login / command execution / COM-port auto-detection (serial mode)
- `comtypes` — Alpaca TAC COM automation, used only to power-cycle the device between boots (serial mode)
- `adb` must be on `PATH` — used to enable adb on-device and pull logs off it (serial mode)
- `paramiko` (`pip install paramiko`) — only needed for SSH mode (`--host`); not required for serial-mode capture

No flashing tool (PCAT, EDL, fastboot, etc.) and no network build share are
required by this skill.

### Your First Run
```bash
# Step 1: Physically connect the already-flashed device (USB serial + Alpaca TAC + adb cable)

# Step 2: Tell the agent
"Capture boot logs from the device and give me a summary"

# Step 3: View report
# Open report/Boot-Charts/bootchart-overview-<target>.html
```

### Common Tasks

| Task | Prompt |
|------|--------|
| Capture boot logs | `"Capture boot logs and give me a summary"` |
| Capture with a custom build label | `"Capture boot logs and record them under Build-7"` |
| More boots per phase | `"Run 5 boots per phase and record them in the report"` |
| Regenerate the HTML report | `"Regenerate the boot report from the existing JSON"` |
| Append a run JSON manually | `"Append this run JSON to the boot report"` |
| Resume a failed pull | `"The last capture failed during adb pull, resume it"` |
| Compare against a specific baseline build | `"Capture boot logs and compare against Build-1"` (default baseline is the first recorded build) |

See [Stages](#stages) below for detailed instructions.

---

## Repository Structure

```
bootbench/                        ← this skill's root (installed at .claude/skills/bootbench/)
├── SKILL.md                        (agent-discoverable; the ONLY SKILL.md in this tree)
├── README.md                       (this file)
├── capture/                        ← Stage: boot an already-flashed device, collect boot-time data
│   └── scripts/
│       ├── capture.py                 ← entry point; serial console + adb + Build-N labeling
│       └── boot_logger.py             ← file logger used by capture.py and report.py (see "Logging")
├── report/                         ← Stage: regenerate/maintain the HTML report, no device involved
│   ├── report.py
│   └── Boot-Charts/, Boot-Logs/      (generated output, created once capture/report has run)
├── tests/
│   └── test_boot_logger.py         ← logger unit tests; no device needed
└── logging/                        ← run logs, one folder per invocation (generated, git-ignored)
```

Only `bootbench/SKILL.md` is agent-discoverable — it's what gets listed
and invoked as the `bootbench` skill, and it contains the full
documentation for both stages. This README is a human-facing overview;
`SKILL.md` is the source of truth for inputs/workflow/outputs.

---

## Stages

**Skill:** `SKILL.md`

Two stages — the agent picks the right one (or both) from what you ask for.

### Stage 1: capture
Boot an already-flashed device N times (default: 3) under the default kernel
cmdline, then N more with debug cmdline params (**reverted afterwards**),
pull the logs via adb, parse them into metrics, and hand the result to
`report.py` to record and render — **no flashing involved.**

```
Device (already flashed) → Boot N × default + N × debug → revert debug params → adb pull → Parse → report.py
```

**Example prompts:**
```
"Capture boot logs and give me a summary"
"Run 5 boots per phase and record them in the report"
```

Each capture produces 6 boots (3 default-cmdline + 3 debug-cmdline). The
report shows **one column per build**: the per-stage **median across the
default boots** (each stage's value/note/high-hitters taken from the boot
that is the median *for that stage*). The debug boots are **not** a
displayed column — they are captured for on-demand deeper investigation
only, opened manually if a regression is suspected.

The debug cmdline params this run added are **reverted** once the debug
boots are captured, returning the build to its base position so the
device's next boot is a clean default boot.

Each capture that doesn't get an explicit `--build-path` is labeled with
an auto-incrementing `Build-<N>` tag (`Build-1`, `Build-2`, ...) per
target — there is no nightly-build-share lookup. **When the user names a
build, pass that name through to `--build-path` verbatim and in full**
(e.g. `--build-path "\\swayam\QLI_Builds\Yocto\41554716269_Nightly_Build_master_877"`)
— never shorten it to a trailing segment like `master_877`; the report
derives its own display/folder name from the complete value.

Full stage docs: `SKILL.md` ("Capture stage" section)

---

### Stage 2: report
Maintains `bootchart-data-<slug>.json` (the only hand-edited file) and
regenerates `bootchart-overview-<slug>.html` from it. No device required.

```
Existing JSON history (+ optional run JSON) → report.py → bootchart-overview-<slug>.html
```

**Example prompts:**
```
"Regenerate the boot report HTML from the existing JSON"
"Append this run JSON to the boot report"
```

Two `--report-cmd` modes:
- **`render`** — regenerate the HTML from the existing JSON (no side effects beyond the `.html`)
- **`add-run`** — append a run from `--run-json`, then render

`--compare-to` re-baselines the report's timing deltas against a single
reference build, and can be used with either mode.

Full stage docs: `SKILL.md` ("Report stage" section)

---

## Tell the agent

Connect your device (USB serial + Alpaca TAC + adb cable, or just network
reachability for SSH mode) and describe the task in plain English. The agent
reads `SKILL.md` and routes between capture and report:

- Want fresh boot numbers (device already flashed) → **capture**
- No device, just regenerate / append to the report → **report**

### What the AI agent will ask you

If information is missing, the agent will ask:
- **"Which target?"** (if `uname -n` can't be auto-detected over the active connection)
- **"Serial console or SSH?"** (if it's not clear from context which transport to use)
- **"Which COM port?"** (serial mode, if no live serial console is found on any port)
- **"Which Alpaca TAC port?"** (serial mode, if multiple TAC devices are visible)
- **"Which host, and what user/credentials?"** (SSH mode, if `--host` is implied but connection info is missing)

---

## What the report shows

The HTML report (`bootchart-overview-<target>.html`) is always fully
derived from `bootchart-data-<target>.json` — never hand-authored. Each
recorded run contributes **one displayed column** — the per-stage median
of that build's default boots (`default-median`). The report is a **stack of
collapsible cards** (memory-skills style), all sharing the same per-build
columns, each column headed by the build's own **`Build-<N>` name** (not a
timestamp) so a build is easy to track across cards. Every card has a navy
header bar that is itself the **collapse/expand control** — click it to
minimise that card. Above the cards sits a single **build filter** (below)
that re-filters every card at once. The cards, in order:

### Build filter (top of page) — single control, all cards
One **Filter builds** disclosure bar at the very top of the page, above every
card. Opening it lists all recorded builds with checkboxes; tick **any
number** and press **Submit** to narrow **every card** to just those builds.
Deltas are recomputed against the **earliest** selected build (named in the
status line); **Show all builds** clears it, and ticking none/all shows
everything. The panel is omitted when only one build is on record. This is a
client-side view toggle only — the recorded JSON and the generated HTML file
are unchanged (the determinism contract holds).

### Device Information (collapsible card)
```
Machine:            Qualcomm Technologies, Inc. Lemans EVK
SoC:                QCS9075 rev 2.0
OS:                 Qualcomm Linux Reference Distro
Kernel:             7.2.0-...
Serial / IP Address: <adb device id>  (or user@host in SSH mode)
Captured:           <timestamp>
```
Omitted entirely if no run carries device info.

### Boot Time Summary (collapsible card) — stage numbers only
Per-stage median timing (NHLOS, kernel, initramfs, sysinit_svc,
total_sysinit, total_multiuser) from `systemd-analyze blame` /
`critical-chain` and `systemctl` failed units — all parsed into structured
JSON, one column per build (headed by its `Build-<N>` name), each as a value +
delta pill. **No high hitters here** — just the numbers. Each non-baseline
column's delta is measured against the reference build (first build, or
`--compare-to`), not the preceding column. Use the top-of-page build filter to
narrow this (and every other) card to a chosen subset of builds.

### Per-stage analysis cards
**Firmware + Loader Analysis** (nhlos), **Kernel Analysis** (kernel),
**Initramfs Analysis** (initramfs), **sysinit Analysis** (sysinit_svc +
total_sysinit), and **multi-user.target Analysis** (total_multiuser). Each
carries that stage's timing + delta, its note, and its ranked **high
hitters** (where measurable).

---

## Stage Pipeline (underlying scripts)

| Stage / Component | Purpose | Script |
|---|---|---|
| **capture** | Boot N×default + N×debug, pull logs, parse, record | `capture/scripts/capture.py` |
| **boot_logger** | Run log shared by capture and report (see [Logging](#logging)) | `capture/scripts/boot_logger.py` |
| **report** | Maintain JSON history, render HTML | `report/report.py` |

### Cross-module imports

`capture.py` has no report-rendering logic of its own — it imports
`report/report.py` directly (two directories up:
`.../capture/scripts/capture.py` → `.../report/report.py`) and delegates
to it for every JSON/HTML update. `boot_logger.py` is co-located in the
same `capture/scripts/` folder, so no path shimming is needed to import it.

`report.py` does not import `capture.py` and needs no device, but it does
import `boot_logger.py` from `capture/scripts/` (it adds that folder to
`sys.path` itself when run directly). `boot_logger.py` sits under `capture/`
rather than `report/` because the repository's `.gitignore` excludes the
generated `report/` folder, so a new file there would never be committed.

---

## Logging

Both scripts write a log file for every invocation, next to their normal
console output. The console itself is untouched — same text, same order,
same exit codes — because the logger writes to files only.

```
logging/<YYYYmmdd_HHMMSS>/
├── log-<YYYYmmdd_HHMMSS>.log   everything, all phases
├── setup.log                   connect, detect target, device info, debug-cmdline provisioning
├── boot.log                    the boot loop: default-N, then debug-N
└── collect.log                 pull logs, parse, record + render the report
```

- **Level.** `--log-level DEBUG|INFO|WARNING|ERROR` on both `capture.py` and
  `report.py`; the default is `INFO`. `DEBUG` also records every command sent
  to the device, every file pulled and what `adb devices` reported while
  waiting for the device to appear.
- **Secrets.** The `--password` value, a password typed at the prompt and
  the console login password are replaced by `********` in every record,
  tracebacks included.
- **Size.** A single message or traceback is capped at 8000 characters
  (head and tail kept) so one huge dmesg cannot flood the file; the console
  still prints it in full.
- **Not the device logs.** `report/Boot-Logs/` is what was pulled from the
  device; `logging/` is what the script did. After a failed capture, read the
  central `log-<ts>.log` first.
- **Housekeeping.** `logging/` is git-ignored and never pruned
  automatically. Two invocations started in the same second share a folder.

Quick checks: `tail -f logging/*/log-*.log` follows a running capture, and
`python3 -m unittest discover -s tests` (from the `bootbench/` folder) runs
the logger tests with no device attached.

---

## Data Collection

Files pulled from device per boot (by `capture.py`, over adb in serial mode or SFTP in SSH mode):

| File | Source | Used for |
|---|---|---|
| `blame_systemd.txt` | `systemd-analyze blame` | Per-unit activation durations |
| `systemd-analyze_critical_chain.txt` / `..._sysinit.txt` | `systemd-analyze critical-chain` | Boot-critical dependency chain, per-stage hitters |
| `blame_systemdsystemctl.txt` | `systemctl` | Failed-unit extraction (`parse_failed_units`) |
| `dmesg.txt` | `dmesg` | Kernel-probe hitters (debug boots only) |
| `journalctl.log` | `journalctl -b` | Userspace milestone timing |
| `systemd_analyze.txt` | `systemd-analyze` | Top-level firmware/loader/kernel/userspace timing |

---

## Requirements & Compatibility

### Host Machine

| Requirement | Notes |
|---|---|
| **Python 3** | Run with ARM64 `py -3` or regular Windows `python3` |
| **pyserial** | `pip install pyserial` — serial console login/commands (serial mode) |
| **comtypes** | `pip install comtypes` — Alpaca TAC power-cycle automation (serial mode) |
| **adb** | Required on `PATH` — used to enable adb on-device and pull logs (serial mode) |
| **paramiko** | `pip install paramiko` — SSH login/commands/reboot/SFTP (SSH mode, `--host`, only) |
| **OS** | Windows only (comtypes dependency applies to serial mode only; SSH mode has no OS-specific dependency) |

### Device

| Requirement | Notes |
|---|---|
| **Platform** | Qualcomm Linux target device (e.g. `iq-9075-evk`), already flashed with the build under test |
| **Connections (serial mode)** | Serial (COM) console, Alpaca TAC debug board, adb cable |
| **Connections (SSH mode)** | Network reachability to the device's SSH server — no serial, TAC, or adb cabling needed |

### Qualcomm-Specific Features

- Alpaca TAC power-cycle automation (Qualcomm-only), used only to force a
  clean reboot between boots
- `bootctl`-based debug kernel cmdline injection (Boot Loader
  Specification Type #1 devices only; skipped with a notice on Type #2)

---

## Quick Commands

```bash
# Capture only (device already flashed), auto-detecting target/port/build label
py -3 capture/scripts/capture.py

# Capture with explicit target/COM port and more boots per phase
py -3 capture/scripts/capture.py --target iq-9075-evk --com-port COM5 --num-boots 5

# Capture under an explicit build label instead of the auto-incrementing one
py -3 capture/scripts/capture.py --build-path "Build-7"

# Resume a capture that failed partway through adb pull
py -3 capture/scripts/capture.py --resume-pull --target iq-9075-evk --build-path Build-3

# Capture over SSH instead of serial console (no TAC/adb needed)
py -3 capture/scripts/capture.py --host 192.168.1.50 --user root --num-boots 5

# Compare this build against a specific reference build (default baseline is
# the FIRST recorded build; pass any earlier label to re-baseline)
py -3 capture/scripts/capture.py --compare-to Build-1

# Capture with DEBUG detail in the run log (only when you want it; the console output is the same)
py -3 capture/scripts/capture.py --host 192.168.1.50 --user root --log-level DEBUG

# Regenerate the HTML report from existing JSON
py -3 report/report.py --report-cmd render --target iq-9075-evk

# Append a run JSON
py -3 report/report.py --report-cmd add-run --run-json new_run.json --target iq-9075-evk

# Re-baseline an existing report against a specific reference build
py -3 report/report.py --report-cmd render --target iq-9075-evk --compare-to Build-1
```

---

## Documentation

| File | Description |
|---|---|
| `README.md` | This file — overview, quick-start, and compatibility |
| `SKILL.md` | Agent-discoverable skill root; full capture + report docs, logging |
| `tests/test_boot_logger.py` | Unit tests for the logger and the `--log-level` wiring |

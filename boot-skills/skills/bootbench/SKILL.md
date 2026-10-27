---
name: bootbench
description: Boot an already-flashed Qualcomm Linux target device N times over a serial console or SSH, pull and parse boot-time logs via adb or SFTP, and maintain a per-device JSON history + HTML boot-time report. Use when the user asks to capture/collect boot logs or boot times from a target device, summarize boot performance, or regenerate/update the boot-time HTML report.
license: Proprietary
metadata:
  domain: embedded-linux-boot-benchmarking
---

# Bootbench — Capture / Report

Automates boot-time benchmarking on an **already-flashed** Qualcomm Linux
target device: boot the device N times under the default kernel cmdline,
then N more times with debug cmdline params added (which are **reverted
afterwards**, returning the build to its base position), pull all
collected logs off the device, parse them into structured boot-time
metrics, and record + render an HTML report.

**One column per build.** Each build is represented by a **single**
displayed column — the **per-stage median across all N default boots**
(not the first boot, and there is no separate debug column). For each
stage (NHLOS, kernel, initramfs, …) the value, note and high-hitters come
from whichever default boot was the *median for that stage* — so if the
3rd boot's kernel time is the median kernel time, the kernel row shows the
3rd boot's kernel high-hitters. The N debug boots are captured for
**on-demand deeper investigation only** — their logs (with
`initcall_debug` / `systemd.log_level=debug` detail) are there for a human
or agent to open manually if a regression is suspected against the
compared build.

**Comparison baseline.** A build is compared against **one** reference
build — by default the **first** recorded build for the target — not
against all previous builds. The user can re-baseline to any earlier build
with `--compare-to <Build-N>`; every stage's timing delta in the report is
measured against that baseline.

Two transports are supported for reaching the device, chosen by which
flags are passed to `capture.py`:

- **Serial console** (default) — login over a serial (COM) console, an
  Alpaca TAC board power-cycles the device between boots, and `adb` pulls
  the collected logs.
- **SSH** (`--host`) — login over SSH instead, a soft `reboot` over SSH
  power-cycles the device between boots (no TAC needed), and SFTP pulls
  the collected logs (no `adb` needed).

These are mutually exclusive — pass `--host` for SSH, or `--com-port` (or
nothing, for auto-detection) for serial.

This skill has **no flashing capability**. It assumes the device already
has the build under test on it. There is no PCAT/EDL step and no nightly-
build-share lookup — each capture simply labels the build it ran against
with an auto-incrementing `Build-<N>` tag (`Build-1`, `Build-2`, ...), per
target, unless the caller supplies an explicit label.

The pipeline has two stages, both implemented in this one skill:

- **capture** — boot the device, collect raw logs, parse them into
  metrics, and record + render the report.
- **report** — regenerate/maintain the HTML report from the JSON history
  with no device involved at all (re-render, or manually append a run).

---

## Repository Structure

```
bootbench/                        ← this skill's root (installed at .claude/skills/bootbench/)
├── SKILL.md                        (agent-discoverable; this file — the ONLY SKILL.md in this tree)
├── capture/                        ← capture stage: boot the device, collect boot-time data
│   └── scripts/
│       ├── capture.py                 ← entry point; serial console or SSH + adb/SFTP + Build-N labeling
│       └── boot_logger.py             ← file logger shared by capture.py and report.py (see "Logging")
├── report/                         ← report stage: regenerate/maintain the HTML report
│   ├── report.py                      ← entry point
│   └── Boot-Charts/, Boot-Logs/        (generated output, created once capture/report has run)
├── tests/
│   └── test_boot_logger.py            ← unit tests for the logger and the --log-level wiring (no device needed)
└── logging/                        ← run logs, one folder per invocation (generated, git-ignored)
```

`capture/scripts/capture.py` imports `report/report.py` directly (two
directories up: `.../capture/scripts/capture.py` → `.../report/report.py`)
and `capture/scripts/boot_logger.py` (co-located in the same `scripts/`
folder, so no path shimming is needed for it). `report.py` has no
dependency on `capture.py` and needs no device, but it does require
`capture/scripts/boot_logger.py` (it adds that folder to `sys.path` itself
when run directly), so `report.py` can no longer be copied somewhere on
its own.

`boot_logger.py` lives under `capture/scripts/` and not under `report/` on
purpose: the repository's `.gitignore` excludes the whole `report/` folder
except what is already tracked, so a new file there would never be
committed.

---

## Capture stage

**Use when:** the device is already flashed with the build under test
and the user wants boot-time data collected from it.

**Entry point:** `py -3 capture/scripts/capture.py [options]`

### Inputs

| Flag | Required | Description |
|---|---|---|
| `--target` | No | Target name (e.g. `iq-9075-evk`). Auto-detected via `uname -n` over the active connection if omitted — unless `--resume-pull` is given, which requires it explicitly (no connection is opened to auto-detect). |
| `--com-port` | No | Serial console COM port. Auto-detected by probing all enumerated ports if omitted. Mutually exclusive with `--host`. |
| `--boot-timeout` | No | Seconds to wait for a login prompt (serial) or for the device to come back (SSH), on first login and after each reboot. Default `480`. |
| `--tac-port` | No | Alpaca TAC COM port name (e.g. `VTP8`), used only to power-cycle the device between boots in **serial mode**. Auto-detected if exactly one TAC device is connected. Mutually exclusive with `--host`. |
| `--build-path` | No | Build label to record this capture under (e.g. `Build-7`). Defaults to the next auto-incrementing `Build-<N>` label for this target (see "Build labeling" below) — unless `--resume-pull` is given, which requires it explicitly. |
| `--num-boots` | No | Boots to capture **per phase** (default + debug). Default `3` → 6 total boots. Values `< 1` fall back to `3`. |
| `--compare-to` | No | Build label of the **single** reference build this run's timing deltas are compared against (e.g. `Build-1`). Defaults to the **first** recorded build for this target (the default baseline). Pass any earlier label to re-baseline; an unknown/not-yet-recorded label falls back to the first recorded build. Persisted into the data file so later `report.py` renders reuse the same baseline. |
| `--resume-pull` | No | Skip login and the boot loop entirely — adb is already enabled (serial) or the device is already reachable (SSH), and all boots' logs are already on the device from a prior run that failed partway through the pull. Just pulls logs and (re)builds the report. Requires `--target` and `--build-path`. |
| `--host` | No | SSH hostname/IP of the device. **Presence selects SSH mode** instead of serial console — power-cycling between boots becomes a soft `reboot` over SSH (no TAC), and logs are pulled via SFTP (no adb). Mutually exclusive with `--com-port`/`--tac-port`. Requires `paramiko` (`pip install paramiko`). |
| `--user` | No | SSH username. Default `root`. |
| `--password` | No | SSH password. If omitted and `--key` isn't given, prompted interactively when `--host` is used. |
| `--key` | No | Path to an SSH private key file, used instead of a password. |
| `--ssh-port` | No | SSH port. Default `22`. |
| `--log-level` | No | Verbosity of the run log under `logging/` (see "Logging"): `DEBUG`, `INFO`, `WARNING` or `ERROR`, case-insensitive. Default `INFO`. Add `DEBUG` **only when the user explicitly asks for verbose/debug logging — never infer it.** Does not change what is printed. |

### Build labeling

There is no nightly-build-share lookup. If `--build-path` isn't given,
`capture.py` scans this target's existing `bootchart-data-<slug>.json`
for the highest `Build-<N>` label already recorded and uses `Build-<N+1>`
(starting at `Build-1` if none exist yet). This label is what's recorded
in the JSON and shown as each column's header in the HTML report — it is
not a build artifact path of any kind.

**When the user names the build, pass that name through VERBATIM and in
FULL as `--build-path` — never abbreviate, truncate, or keep only a
trailing segment of it.** If the user says "capture for the build
`\\swayam\QLI_Builds\Yocto\41554716269_Nightly_Build_master_877`", run
`--build-path "\\swayam\QLI_Builds\Yocto\41554716269_Nightly_Build_master_877"`
(quote the whole value) — NOT `--build-path master_877` and NOT
`41554716269_...` shortened in any way. The full string the user gave is
the build's identity; the report derives its own display/folder name from
it, so you lose nothing by passing it complete and you corrupt the record
by shortening it. Only fall back to the auto `Build-<N>` label when the
user gave no build name at all.

### Workflow

1. Connect to the device: if `--host` is given, open an SSH connection;
   otherwise open the serial console (auto-detecting the port if not
   given) and log in.
2. If `--target` wasn't given, detect it via `uname -n`.
3. If `--build-path` wasn't given, compute the next `Build-<N>` label for
   this target.
4. Collect device info (machine/SoC/OS/kernel) over the active
   connection.
5. Boot loop: `--num-boots` default-cmdline boots, power-cycling between
   boots (Alpaca TAC in serial mode, a soft `reboot` over SSH polled
   until the device comes back in SSH mode), collecting logs on-device
   after each; then, before the first debug boot, inject debug kernel
   cmdline params (`initcall_debug`, `systemd.log_level=debug`,
   `log_buf_len=4M`) into the device's current bootloader entry; then
   `--num-boots` more boots under that debug cmdline, collecting logs
   the same way.
6. **Revert the debug cmdline params** once the debug boots are captured,
   restoring the bootloader entry to exactly its pre-capture content
   (only the params *this run* added are removed — pre-existing ones are
   left untouched). The build is returned to its base position so the
   device's next boot is a clean default boot, not a debug one.
7. Serial mode: enable `adb` on the device, then pull all collected logs
   via `adb pull`. SSH mode: pull all collected logs via SFTP (no adb
   involved). **Once every log folder is successfully pulled to the host,
   remove the on-device capture artifacts** — the collect script
   (`/data/collect_boot_logs.sh`) and every `/data/Logs-*` folder (see
   `capture.cleanup_device_logs`) — so the device is left exactly as it was
   before the capture. This runs only on a fully successful pull; a partial
   pull leaves the device intact so `--resume-pull` can still re-pull.
8. Parse every boot's logs into structured metrics (`capture.build_run`),
   then compose the **single displayed column** for this build with
   `capture.build_median_boot`: the per-stage median across all default
   boots (each stage's value/note/high-hitters taken from the boot that
   is the median *for that stage*; the two total rows are independent
   medians). The debug boots are **not** a displayed column — but every
   boot (default and debug) is pulled, parsed, and permanently backed up
   as a `.txt` file under `report/Boot-Logs/`, so the debug logs are on
   hand for manual deeper investigation.
9. Hand off to `report.py` (`add_run` → `save_data` → `render`) to update
   the JSON history and regenerate the HTML, persisting `--compare-to`
   (when given) so later renders reuse the same baseline.

### Outputs

- `report/Boot-Charts/bootchart-data-<slug>.json` — updated with the new
  run.
- `report/Boot-Charts/bootchart-overview-<slug>.html` — regenerated from
  that JSON.
- `report/Boot-Logs/<target>/<build-folder>/Logs-<log_name>/*.txt` — raw
  pulled logs for every boot captured (not just the displayed ones).
- `report/Boot-Logs/<target>/<build-folder>/<timestamp>.txt` — permanent
  per-captured-boot backup, one per default and debug boot (JSON only
  keeps the most recent 30 runs and only the median column; these backups
  don't expire, so the debug boots stay available for manual investigation).
- `logging/<YYYYmmdd_HHMMSS>/` — the run log: what the script did, with the
  detail the console omits (see "Logging"). This is `capture.py`'s own
  record, **not** the device logs above.

### Error handling

- No login/shell prompt within `--boot-timeout` (serial mode) → raises
  with the partial console buffer; check the device is powered on and
  the console port is correct.
- SSH connect failure (`--host`) → raises with the underlying paramiko
  error; check the host/user/credentials and that the device is
  reachable on `--ssh-port`.
- SSH soft reboot doesn't come back within `--boot-timeout` → raises;
  the device may have failed to reboot cleanly or isn't coming back up
  on the network — check it manually (there's no TAC to force a power
  cycle in SSH mode).
- `--host` given together with `--com-port`/`--tac-port` → exits
  immediately with an error; these transports are mutually exclusive.
- `bootctl` reports Boot Loader Specification Type #2 (or unrecognized)
  → debug cmdline injection is skipped with a printed notice; capture
  continues (debug boots simply won't carry kernel-probe timing).
  `capture.py` detects this from `metrics.kernel.hitters` being absent at
  render time, not from a threaded flag.
- A failed pull partway through (`adb pull` or SFTP) → rerun with
  `--resume-pull --target <target> --build-path <same label>` (add
  `--host`/`--user`/etc. if it was an SSH-mode capture) once the
  device-side issue is fixed, instead of repeating the whole boot loop.

---

## Report stage

**Use when:** no device is involved — just regenerate the HTML from
existing JSON, or manually append a run JSON.

**Entry point:** `py -3 report/report.py --target <target> [options]`

`--target` is always required (used to resolve
`bootchart-data-<slug>.json` / `bootchart-overview-<slug>.html`).

### `--report-cmd` modes

| Mode | Description |
|---|---|
| `render` (default) | Just regenerates the HTML from the existing JSON. No other flags needed besides `--target`. |
| `add-run` | Appends a run from `--run-json <path\|->` (a path, or `-` for stdin) to the JSON, then renders. |

### Inputs

| Flag | Used with | Description |
|---|---|---|
| `--target` | always | Target name, required for every mode. |
| `--run-json` | `add-run` | Path to a run JSON, or `-` for stdin. |
| `--compare-to` | any | Build label of the single reference build the report's timing deltas are measured against (e.g. `Build-1`). Persisted into the data file; defaults to the first recorded build. Can be set on its own with `--report-cmd render` to re-baseline an existing report. |
| `--log-level` | always | `DEBUG`, `INFO` (default), `WARNING` or `ERROR` for the run log under `logging/` (see "Logging"). Add `DEBUG` only when the user explicitly asks for it. |

### The JSON/HTML contract

`bootchart-data-<slug>.json` is the only file ever hand-edited (by
appending a run). `bootchart-overview-<slug>.html` is **always** fully
derived from that JSON by `report.py` — never hand-authored, never edited
directly. Re-running `render` regenerates it byte-for-byte from whatever
is currently in the JSON.

### Outputs

- `report/Boot-Charts/bootchart-data-<slug>.json`
- `report/Boot-Charts/bootchart-overview-<slug>.html`
- A `.bak.txt`-style backup is not produced by `report.py` itself — permanent
  per-boot backups are written by `capture.py` (`save_run_backup`) at
  capture time, not by `report.py`.

### Error handling

- `--report-cmd add-run` without `--run-json` → prints the missing
  requirement and exits non-zero before touching the JSON.

---

## Logging

Both `capture.py` and `report.py` keep a log file next to their normal
output. A capture takes the better part of an hour and its console output
is easy to lose (a backgrounded run, a closed terminal); the log is what to
read afterwards, and what to tail while a long capture is running.

Every invocation creates one folder, named by its start time:

```
logging/<YYYYmmdd_HHMMSS>/
├── log-<YYYYmmdd_HHMMSS>.log   everything, all phases (paramiko's own INFO+ records land here too)
├── setup.log                   connect, detect target, device info, debug-cmdline provisioning
├── boot.log                    the boot loop: default-N, then debug-N, including each reboot and reconnect
└── collect.log                 pull the logs, parse each boot, record + render the report
```

A phase file only exists if the run reached that phase (`report.py` runs
entirely in `collect`). Lines look like
`2026-11-05 16:47:18 [INFO] Rebooting fakehost over SSH ...`. Every record is
flushed as it is written, so `tail -f` on the central log follows a running
capture.

- **What is in it.** Everything the script prints, at its natural level
  (usage errors are `ERROR`, retries and fallbacks are `WARNING`), plus what
  the console leaves out: the exact failure with its traceback, why an `adb
  root` or SSH reconnect was retried, the optional commands that failed and
  were skipped, per-boot parse results, and how the run ended (`Finished`,
  `Exiting with status N`, `Interrupted by the user`, or the unhandled
  exception).
- **`--log-level`.** `INFO` by default. `DEBUG` additionally records every
  command sent to the device (with its exit status and duration), every SFTP
  file pulled and what `adb devices` reported while waiting for the device
  to appear. paramiko's packet-level
  debugging is deliberately kept out even at `DEBUG`. Use `DEBUG` only when
  the user asks for it; do not add it on your own.
- **The console is unchanged.** Output, ordering and exit codes are exactly
  what they were before logging existed; the logger has no console handler,
  so nothing is added to stdout or stderr (the one exception is a single
  `WARNING: bootbench file logging is disabled ...` line on stderr if the log
  folder cannot be created — the capture then carries on without a log).
- **Secrets are masked.** The `--password` value (also in its abbreviated
  and `--password=...` forms), a password typed at the prompt, and the
  console login password are replaced by `********` in every record,
  including tracebacks.
- **Records are bounded.** A message or traceback longer than 8000
  characters keeps its first and last parts with an "N characters omitted"
  marker between them (a failed dmesg parse puts the whole dmesg into the
  exception text; the console still prints it in full).
- **Not the device logs.** `report/Boot-Logs/` holds what was pulled *from
  the device*; `logging/` holds what the *script* did. After a failed
  capture read the central log first — the last `ERROR` and its traceback
  name the failing step.
- **Housekeeping.** `logging/` is git-ignored and is not pruned
  automatically. Two invocations started within the same second share one
  folder (their records are appended, never overwritten).

---

## What the report shows

The report is a **stack of collapsible cards** (memory-skills style), one
column per captured build. Every card's columns are headed by the build's
own **`Build-<N>` name** (not a timestamp), so a build is easy to track
across cards. Every card has a navy header bar that is itself the **collapse
/ expand control** — click it to minimise that card. All cards share the same
build columns, so the single build filter (below) re-filters every card at
once.

- **Build filter** — one control at the **very top of the page**, above
  every card: a **Filter builds** disclosure bar. Open it to reveal the full
  list of recorded builds, each with a checkbox; tick **any number** of them
  and press **Submit** to narrow **every card** to just those builds. Deltas
  are recomputed against the **earliest** build you select, and the status
  line names the baseline. **Show all builds** clears the selection; ticking
  none (or all) is the same as showing everything. This is a client-side view
  toggle only — it doesn't change the recorded data or the generated file.
  The panel is omitted when only one build is on record (nothing to filter).
- **Device Information** card — Machine / SoC / OS / Kernel / Serial / IP
  Address / Captured, one column per captured build. The **Serial / IP
  Address** field is the device's adb id in serial-console mode (`adb
  devices`' own device id) and `user@host` (the SSH endpoint) in SSH mode —
  matching the transport the logs were pulled over, not a value read off the
  device over the serial console. Omitted entirely if no run carries
  device info.
- **Boot Time Summary** card — **stage-wise boot numbers only** (no high
  hitters): one column per build (headed by its `Build-<N>` name; the
  reference baseline column is marked "baseline — compared against", each the
  per-stage median of that build's default boots), with rows NHLOS, kernel,
  initramfs, sysinit_svc, total_sysinit, total_multiuser, each as a value +
  delta pill measured against the reference build. Use the top-of-page
  **build filter** to narrow this (and every other) card to a chosen subset
  of builds.
- **Per-stage analysis cards** — **Firmware + Loader Analysis** (nhlos),
  **Kernel Analysis** (kernel), **Initramfs Analysis** (initramfs),
  **sysinit Analysis** (sysinit_svc + total_sysinit), and **multi-user.target
  Analysis** (total_multiuser). Each carries that stage's timing + delta, its
  note, and its ranked **high hitters** (where measurable, drawn from the
  boot that is the median for that stage).

## Prerequisites

```
py -3 -m pip install pyserial comtypes
```

or

```
python3 -m pip install pyserial comtypes
```

- `pyserial` — serial console login, command execution, port
  auto-detection (capture stage, serial mode only).
- `comtypes` — Alpaca TAC COM automation, used only to power-cycle the
  device between boots in serial mode (capture stage only).
- `adb` must be on `PATH` — used by capture in serial mode to enable adb
  on-device and pull logs.
- `paramiko` (`pip install paramiko`) — only needed for SSH mode
  (`--host`): login, command execution, soft reboot, and SFTP log pull.
  Not required for serial-mode capture.
- No flashing tool (PCAT, EDL, fastboot, etc.) is required or used by this
  skill.

Run with this machine's ARM64 Python launcher (`py -3 ...`), or a regular
Windows Python install (`python3 ...`).

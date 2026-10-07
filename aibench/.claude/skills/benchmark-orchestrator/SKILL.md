---
name: benchmark-orchestrator
description: Root dispatcher for all on-device benchmark campaigns (CoreMark, CoreMark-Pro, Sysbench, TIOBench, Hackbench, UnixBench, RAMSpeed, OSBench, bw_mem, lat_mem_rd, GLMark2, Geekbench). Parses natural-language benchmark requests, resolves working directory automatically, and routes to the correct leaf skill.
category: Performance Benchmarking
---

# Skill: Benchmark Orchestrator
**Author:** Sarbojit Ganguly <sarbgang@qti.qualcomm.com>

Coordinates the discovery and sequential execution of all on-device benchmark campaigns (CoreMark, CoreMark-Pro, Sysbench, TIOBench, Hackbench, UnixBench, RAMSpeed, OSBench, bw_mem, lat_mem_rd, GLMark2, Geekbench).

This is the **ROOT / dispatcher skill** for the `aibench/` project. It is the entry point an LLM/agent should read first for *any* benchmark-related request. It tells you (a) how to resolve the working directory automatically, (b) how to parse the user's natural-language request into structured parameters, and (c) which leaf-node skill folder to open next. **Do not explore the repository structure or run discovery commands (e.g. `python main.py --help`, `ls`, `find`) before consulting this file and the target `run-<benchmark>/SKILL.md` — everything you need is already documented here and in the leaf skill.**

## Skill Hierarchy (3-Tier)

```
aibench/.claude/skills/benchmark-orchestrator/SKILL.md   <- YOU ARE HERE (Root dispatcher/router)
    │  parses natural-language intent, resolves working directory,
    │  identifies target benchmark(s), decides parameters
    ▼
aibench/.claude/skills/run-<benchmark>/SKILL.md   <- Leaf-node skill (one per benchmark)
    │  knows benchmark-specific test names, default params, output schema
    │  builds the final structured `python main.py ...` command
    ▼
aibench/main.py                               <- Python unified benchmark engine
       executes the command against the target device (ADB/Serial or SSH)
```

**Rule for the LLM:** After reading this file and determining the target benchmark(s), open the corresponding `aibench/.claude/skills/run-<benchmark>/SKILL.md` (e.g. `run-tiobench/SKILL.md`, `run-sysbench/SKILL.md`, `run-all-benchmarks/SKILL.md`) to get the exact parameter names, defaults, and output-parsing instructions for that benchmark, then execute. Do not skip the leaf skill — it contains benchmark-specific knowledge (valid sub-test names, output units, "higher/lower is better" direction, etc.) that this root file intentionally does not duplicate.

## ⚠️ Invocation Order — Always Start Here, Never Invoke a Leaf Skill Directly

This file (`benchmark-orchestrator`) is the **single required entry point** for every benchmark-related request, regardless of what the user's exact wording is or which specific benchmark they name.

* **Do NOT invoke `Skill(run-tiobench)`, `Skill(run-sysbench)`, `Skill(run-coremark)`, or any other `run-<benchmark>` skill directly**, even if the user's prompt names that benchmark explicitly (e.g. "run tiobench..."). Naming a specific benchmark in the prompt does **not** mean the leaf skill should be invoked first.
* Always consult this file **first**. Try `Skill(benchmark-orchestrator)`; if that call fails (e.g. `Unknown skill` — happens when `aibench/` is nested inside a larger repo/workspace, so `aibench/.claude/skills/` is never scanned), immediately fall back to reading this file directly (`aibench/.claude/skills/benchmark-orchestrator/SKILL.md`) with the Read tool instead — do not retry the Skill() call or treat the failure as blocking. Either way, this file performs the Intent Parsing and Working Directory resolution described below, and only *after* that should the corresponding leaf skill (`run-<benchmark>/SKILL.md`) be opened — purely as a **read-only reference** to confirm benchmark-specific parameter names/defaults — before composing and executing the final `python main.py ...` command directly from here.
* The leaf skill is documentation to be read, not a separate execution entry point. Reading it does not require re-parsing intent, re-resolving the working directory, or re-deciding the command prefix — all of that is already done once, at this level.

## ⚠️ Working Directory — Assume You Are Already Inside `aibench/`, Do Not Explore

`main.py` **must** execute with `aibench/` as the current working directory (it self-checks `Path.cwd().name == "aibench"` and exits fatally otherwise, using the directory's **name**, not its full path — so this check works regardless of where the repo is cloned on disk).

**Default assumption: the agent/user session is already running with `aibench/` as the current working directory.** This is the common case — most sessions invoking this skill are started from inside `aibench/`. Under this default assumption, run the command as-is, with **no `cd` prefix at all**:
```
python main.py -b <benchmark> [options]
```

Only add a `cd aibench; ` prefix in the specific case where you have **explicit, reliable evidence from the session/task context** that the current working directory is the parent repo root (e.g. `skills-lab/`) or another ancestor of `aibench/` — for example, if the session/task metadata explicitly states the starting directory, or a previous step in this same conversation already showed the cwd. Do **not** run `pwd`, `Get-Location`, `ls`, or any other command purely to check the directory — that is exploration and is forbidden (see the `⛔ CRITICAL` section below). If you are not otherwise informed of the cwd, default to assuming you are already inside `aibench/` and omit the `cd` prefix, since this is the more common invocation pattern and an incorrect omission fails fast and cheaply (see Error Handling) versus a redundant `cd` which produces no error but wastes a step.

| Working directory (only act on this if reliably known from context) | What the LLM must do |
|---|---|
| No explicit evidence otherwise (default) | Assume already inside `aibench/`. Run the command as-is — **no `cd` needed.** |
| Explicit evidence that cwd is the parent repo root or an ancestor of `aibench/` | Prefix the command with `cd aibench; ` before calling `python main.py ...`. |
| Explicit evidence that cwd is already `aibench/` | Run the command as-is — **no `cd` needed.** (Do not add a redundant `cd aibench;` — running `cd aibench` from inside `aibench/` itself would fail, since there is no nested `aibench/aibench/` directory.) |

### ⚠️ Cross-Platform Command Chaining — Use `;` Not `&&`

**All commands in this skill use the semicolon (`;`) as the command separator, never `&&`.**

| Separator | Bash / Zsh (Linux, macOS) | PowerShell (Windows) | Windows CMD |
|---|---|---|---|
| `&&` (conditional) | ✅ Works | ❌ **Fails** (invalid syntax pre-PS7, unreliable even in PS7 for this pattern) | ✅ Works |
| `;` (sequential) | ✅ Works | ✅ Works | ✅ Works |

Whenever a `cd aibench; ` prefix *is* warranted (per the table above — i.e. you have explicit evidence the cwd is the parent repo root or an ancestor), **always emit `cd aibench; python main.py ...`** (semicolon, with a space after it) instead of `cd aibench && python main.py ...`. The trade-off (the `;` form runs `python main.py` even if `cd` fails) is acceptable here because `main.py` immediately fails fast with a clear "must be executed from within the aibench/ directory" error if the `cd` didn't land correctly — this is cheap to diagnose and does not require any additional exploration.

**Do not** run exploratory commands (`pwd`, `ls`, `find . -name main.py`, `Get-Location`, etc.) to "figure out" the working directory — per the Working Directory section above, the default assumption (no `cd` prefix) applies unless you already have reliable evidence otherwise from context.

### ⚠️ Windows / PowerShell Sessions — Do Not Invoke Git Bash, WSL, or Other Shell Wrappers

If the agent's execution shell is detected as **Windows PowerShell or CMD** (i.e. the session/harness is running natively on Windows, not inside WSL or a Linux/macOS container):

* **Execute the command directly in that same PowerShell/CMD shell.** Do **not** attempt to switch to, spawn, or route the command through Git Bash, WSL, MSYS2, Cygwin, or any other POSIX-shell wrapper "to be safe" — none of that is necessary or desired.
* The `cd aibench; python main.py ...` command (using `;`) is **already fully native PowerShell/CMD syntax** and requires no translation, wrapping, or compatibility shims.
* Attempting to invoke Git Bash or a similar wrapper on a machine where it is not installed, or where its profile is misconfigured (e.g. missing `/usr/local/etc/profile.global`), will cause a spurious shell-initialization failure that has **nothing to do with this skill or `main.py`** — it is purely an artifact of unnecessarily invoking a foreign shell. Do not attempt to diagnose or fix such errors; simply run the command in the native shell instead.
* If the harness itself cannot execute shell commands directly (a harness-level limitation), state the exact command to the user for manual execution rather than attempting alternate shells as a workaround.

## ⛔ CRITICAL: Never Run `--help`, `ls`, or Other Discovery Commands First

This is a **hard rule, not a suggestion**. Every piece of information needed to compose the correct `python main.py ...` command is already documented in this file (Quick Reference, Intent Parser, Prompt Examples, Common Patterns) and in the target leaf skill's `SKILL.md`. Running `python main.py --help`, `ls`, `find`, `cat`, or any other discovery/exploration command **before** composing and executing the final benchmark command is:
* **Unnecessary** — the CLI surface is fully documented below and in each leaf skill.
* **Wasteful** — it burns tokens/turns and delays the user's actual request.
* **Explicitly forbidden** by this skill's Execution Flow (step 5: "Execute it via the shell tool directly").

If you find yourself about to run `--help` or any exploratory listing command to "confirm" something, **stop** — re-read the Quick Reference and Intent Parser sections below instead. They already contain the answer.

## Rationale
To guarantee statistically clean results and prevent CPU/Storage thermal throttling, the orchestrator coordinates the sequential execution of individual benchmark skills while strictly enforcing a 5-minute minimum cooling period between runs.

## 🔌 Device Connection Management

AIBench automatically maintains a history of recently used devices (up to 10) with their IP addresses and details. This allows you to reference devices by their model name instead of remembering IP addresses.

### Device History File

Device information is stored in `config/device_history.yaml` with the following structure:

```yaml
devices:
  - ip_address: "10.92.197.120"
    device_model: "lemans"
    build_id: "ABC123"
    os_pretty_name: "Linux 5.15"
    kernel: "5.15.0-qualcomm"
    added_timestamp: "2026-10-04T14:35:00"
    last_used: "2026-10-04T14:35:00"
```

### Using Device History

**First Time - Provide IP Address:**
```bash
# Connect to a new device by IP address
python main.py --host 10.92.197.120 --ssh-connection

# Note: --ssh-connection is automatically added if --host is provided
python main.py --host 10.92.197.120
```

**Subsequent Times - Use Device Model Name:**
```bash
# Connect using device model name (e.g., "lemans", "kodiak")
python main.py --host lemans

# AIBench will:
# 1. Look up "lemans" in device history
# 2. Find the stored IP address
# 3. Verify the device is reachable
# 4. Connect automatically
```

### Exception Handling

**1. Invalid or Unreachable IP Address:**
- AIBench checks reachability before attempting connection
- If unreachable, displays list of reachable devices (model names only)
- User must provide a valid IP address

Example error output:
```
ERROR: Target host 10.92.197.120 is not reachable (SSH port 22 not responding).
INFO: Available reachable devices:
  - lemans (last used: 2026-10-04T14:30:00)
  - kodiak (last used: 2026-10-03T10:15:00)
```

**2. Device Not Found in History:**
- If device model name is not in history, AIBench prompts for IP
- Shows list of known devices for reference

Example error output:
```
ERROR: Device 'lemans' not found in history.
INFO: Known devices: kodiak, pineapple
ERROR: Please provide the IP address using --host <ip-address>
```

**3. Auto-Adding SSH Flag:**
- If `--host` is provided without `--ssh-connection`, SSH mode is automatically enabled
- No need to remember to add `--ssh-connection` flag

### Device Model Name Detection

Device model names are automatically extracted from:
1. `/etc/os-release` NAME field (e.g., "lemans", "kodiak")
2. Fallback to `active_device` in `config/benchmarks.yaml`
3. Stored in lowercase for consistency

### Default Host Resolution (No `--host` Provided)

When the user's prompt implies "default host" / "default target" (no explicit IP address, no device model name), `main.py` resolves the target in this order:
1. `--host <ip-or-model>` on the command line (if provided — not the case here, by definition).
2. Device model name lookup in `config/device_history.yaml` (only applies if `--host` was a model name).
3. **`ssh.host` in `config/credentials.yaml`** — the default device IP/credentials for SSH mode. This is the fallback actually used for a bare "run on default host" request.
4. If none of the above resolve to a host, `main.py` exits with an error (no silent/blank connection attempt).

**Pre-flight check (do this before composing/running the command):** if the user's prompt implies the default host, read `config/credentials.yaml` first and check whether `ssh.host` is present and non-empty.
- If it is set, proceed normally — just compose and run `python main.py ... --ssh-connection` as usual; `main.py` will pick up `ssh.host` automatically.
- If `config/credentials.yaml` is missing, or its `ssh.host` field is missing/empty, **do not run `main.py`**. Instead, tell the user they asked to run on the default host but no default host is configured yet, and ask them to either pass an explicit `--host <ip-address>` or populate `ssh.host` in `config/credentials.yaml` (see `credentials.yaml.example`). Do not read or print the rest of `credentials.yaml`'s contents (it holds plaintext credentials) — only check whether `ssh.host` is present.

## ⚠️ Automatic Regression Detection & Root Cause Analysis (RCA)

**No action needed from the LLM for this — it is fully automatic.** The initial/baseline suite run executes with NO telemetry collection (clean baseline) unless `--collect-telemetry` is explicitly passed. After every single suite run completes, the `regression-detection-and-rca` skill (see `aibench/.claude/skills/regression-detection-and-rca/SKILL.md`) automatically:
1. Detects regressions (3-tier: run, build, and baseline comparisons).
2. **If regressed:** Automatically re-runs ONLY regressed benchmarks with Tier 1 telemetry (vmstat, dmesg, thermal, cpufreq).
3. **If Tier 1 inconclusive:** Automatically re-runs with Tier 2 telemetry (includes ftrace).
4. Writes `<run_dir>/rca_report.json` with findings and confidence scores.

This is the **Smart RCA** workflow (default). To force RCA on ALL benchmarks instead (legacy behavior), use `--full-rca`.

The only user-controllable pieces are:
- `--store-baseline` — explicitly saves this run's build statistics as a named baseline (see below), for use in future "compare with baseline" requests.
- `--baseline-tag <name>` — names the baseline slot (defaults to `"default"` if omitted). Use the same tag on both the storing run and the comparing run.

*Note: The RCA feature itself currently has limited regression detection capabilities in this repository version. Do not search for additional RCA scripts if they fail.*

## ⚠️ Logging & Progress Monitoring (CRITICAL RULE)

During benchmark execution, progress is automatically logged to the following centralized location:
`aibench/logging/log-<date>_<timestamp>.log`

**CRITICAL RULE FOR THE LLM: DO NOT INVESTIGATE LOGGING.**
- Do **NOT** search the codebase (`main.py`, `src/utils/logger.py`, etc.) for logging patterns or `.log` files to figure out how logging works.
- The logging mechanism is fully automatic and requires no configuration on your part.
- If asked to monitor progress or show logs, start the benchmark process in the background and tail the generated log file (e.g., `tail -f aibench/logging/log-*.log`).

**Example flow (user explicitly wants a golden-build comparison):**
```
User: "run all benchmarks in the current build and store it as a baseline"
  -> python main.py --store-baseline --ssh-connection

(device is reflashed with a new build)

User: "new build is now flashed, run all benchmarks, compare with previously stored baseline,
       detect regression if any, perform root cause analysis for all regressions detected"
  -> python main.py --ssh-connection
     (baseline comparison + RCA happens automatically since a baseline is already stored)
```

If the user gives the baseline a name (e.g. "store as baseline 'pre-fix'"), pass `--baseline-tag pre-fix` on both the storing and comparing invocations.

## ⚠️ Understanding `-r` (Runs) vs `--iterations` — Two Independent, Nested Loops

These two flags are frequently confused, so parse them carefully during Intent Parsing (see below):

- **`-r` / `--runs`** — the **outer loop**, implemented in `main.py`. Controls how many times the **entire benchmark suite** (one full lifecycle execution) runs. Each suite run produces its own timestamped output directory/report. Default: **1**.
- **`--iterations`** — the **inner loop**, implemented inside each benchmark engine (`src/benchmark/<name>.py`). Controls how many times **each individual sub-test** repeats *within a single suite run*. Default varies per benchmark (typically 3; see `config/benchmarks.yaml`'s per-benchmark `iterations:` key or the leaf skill).

**They multiply:** `Total sub-test executions = runs × iterations`.

**Worked example — "run sysbench 3 times and its fileio test 4 times":**
```
python main.py -b sysbench -t sysbench_fileio_random_mixed_test -r 3 --iterations 4 --ssh-connection
```
This runs the sysbench suite 3 times (`-r 3`), and within each of those 3 runs the fileio test executes 4 times (`--iterations 4`) — **12 total fileio executions**, not 3 or 4 alone. Apply this same `-r N --iterations M` mapping whenever a user gives two distinct repeat counts (one for the overall suite/benchmark, one for a specific sub-test).

**Known exception:** GLMark2 currently ignores `--iterations` entirely (hardcoded to 1 iteration per flavor per suite run in `src/benchmark/glmark2.py`) — see `run-glmark2/SKILL.md` for details. Only `-r` has any effect on GLMark2's repeat count today.

## Quick Reference — All Benchmarks (For LLM)

| Benchmark name (`-b` value) | Leaf skill | Category | Metric direction |
|---|---|---|---|
| `coremark` | `run-coremark/SKILL.md` | CPU | higher is better |
| `coremark_pro` | `run-coremark-pro/SKILL.md` | CPU | higher is better |
| `sysbench` | `run-sysbench/SKILL.md` | CPU/Memory/Threads/Mutex/FileIO | mixed (see leaf skill) |
| `tiobench` | `run-tiobench/SKILL.md` | Storage | higher is better |
| `hackbench` | `run-hackbench/SKILL.md` | CPU/Scheduler | lower is better |
| `unixbench` | `run-unixbench/SKILL.md` | OS/Kernel/Scheduler | higher is better |
| `ramspeed` | `run-ramspeed/SKILL.md` | DDR | higher is better |
| `osbench` | `run-osbench/SKILL.md` | OS microbenchmarks | lower is better |
| `bw_mem` | `run-bw-mem/SKILL.md` | Memory bandwidth | higher is better |
| `lat_mem_rd` | `run-lat-mem-rd/SKILL.md` | Memory latency | lower is better |
| `geekbench` | `run-geekbench/SKILL.md` | CPU | higher is better |
| `glmark2_default` / `glmark2_1920x1080` / `glmark2_offscreen` / `glmark2_offscreen_1920x1080` | `run-glmark2/SKILL.md` | GPU | higher is better |
| *(all of the above, sequentially)* | `run-all-benchmarks/SKILL.md` | — | — |

All leaf skills live under `aibench/.claude/skills/run-<benchmark>/SKILL.md`.

If the user names a benchmark that isn't in this table, treat it as unsupported — do not guess a `-b` value; instead check `aibench/config/benchmarks.yaml`'s `active_benchmarks`/`benchmarks` keys only if the leaf skill list above doesn't resolve it.

## Intent Parser (For LLM)

Parse the user's request into these structured fields before opening the leaf skill:

1. **benchmark** — one name from the Quick Reference table, a comma-separated list of names, or "all"/omitted → route to `run-all-benchmarks/SKILL.md`.
2. **runs** (`-r`/`--runs`) — integer number of full suite repetitions. Default 1 if unspecified.
3. **iterations** (`--iterations`) — integer number of internal sub-test repetitions. Only include if the user explicitly asks for it; otherwise let the leaf skill's benchmark-specific default apply.
4. **connection** — `--ssh-connection` if the user says "over ssh"/"via ssh"/"ssh"; otherwise omit (defaults to Serial/ADB). Note `--default-connection` and `--ssh-connection` are mutually exclusive.
5. **tests** (`-t`/`--tests`) — space-separated specific sub-test names, only when the user asks to run "only X test(s)" / "just the X category". Resolve the category → concrete sub-test name(s) using the leaf skill's test list (e.g. "cpu tests of sysbench" → `sysbench_cpu_prime_single_test sysbench_cpu_prime_multi_test`, per `run-sysbench/SKILL.md` / `config/benchmarks.yaml`).
6. **skip** (`--skip`) — comma-separated benchmarks to exclude, when the user says "all benchmarks except X".
7. **bypass_gap** (`--bypass-gap`) — only if the user explicitly asks to skip the cooldown; do not add this by default (it changes measurement validity).
8. **build_id** (`-i`/`--build-id`) — only if explicitly given by the user; otherwise omit (auto-detected).

After extracting these fields, open the leaf skill named in the Quick Reference table to confirm benchmark-specific defaults, valid test names, and expected output shape, then emit the final command.

## Execution Flow

1. Parse user intent using the Intent Parser above (no filesystem exploration).
2. Determine the `cd aibench; ` prefix requirement per the Working Directory section — **default to omitting it** (assume already inside `aibench/`) unless you have explicit, reliable evidence from context that the cwd is the parent repo root or an ancestor (based on session context, not probing).
3. Open the matching `run-<benchmark>/SKILL.md` (or `run-all-benchmarks/SKILL.md`) to confirm parameter names/defaults specific to that benchmark.
4. Compose the final command: `python main.py [-b <benchmark(s)>] [-r <runs>] [--iterations <n>] [--ssh-connection] [-t <tests...>] [--skip <list>] [--bypass-gap] [--build-id <id>]` — only prepend `cd aibench; ` (using `;` as separator, never `&&`) if step 2 determined it's needed.
5. Execute it via the shell tool directly — do not run `--help`, `ls`, or other discovery commands first.
6. After completion, follow the leaf skill's "Implementation Example" / "Expected Output Format" to parse `results.json` / `build_analysis.json` and present results to the user.

## Prompt Examples (For LLM — Match These Patterns)

These examples assume the **default case**: the session is already inside `aibench/` (no `cd` prefix). If you have explicit evidence the cwd is the parent repo root instead, prepend `cd aibench; ` to any of these commands.

| User Prompt | Resulting Command (default: already inside `aibench/`) |
|---|---|
| "run tiobench for 4 times over ssh" | `python main.py -b tiobench -r 4 --ssh-connection` |
| "run sysbench with default params over ssh" | `python main.py -b sysbench --ssh-connection` |
| "run tiobench with default parameters over ssh" | `python main.py -b tiobench --ssh-connection` |
| "run sysbench over ssh" | `python main.py -b sysbench --ssh-connection` |
| "run all benchmarks over ssh" | `python main.py --ssh-connection` |
| "run only cpu tests of sysbench over ssh" | `python main.py -b sysbench -t sysbench_cpu_prime_single_test sysbench_cpu_prime_multi_test --ssh-connection` |
| "run coremark for 5 times with 10 iterations over ssh" | `python main.py -b coremark -r 5 --iterations 10 --ssh-connection` |
| "run sysbench and coremark for 3 times over ssh" | `python main.py -b sysbench,coremark -r 3 --ssh-connection` |
| "run all benchmarks except unixbench over ssh" | `python main.py --skip unixbench --ssh-connection` |
| "run tiobench for 2 times" (no ssh mentioned) | `python main.py -b tiobench -r 2` |
| "run hackbench" (no runs/connection mentioned) | `python main.py -b hackbench` |

**Note:** Only add a `cd aibench; ` prefix in front of any command above if you have explicit, reliable evidence from context that the cwd is the parent repo root or an ancestor of `aibench/` (see Working Directory section). Do not add it "just in case."

## Pattern Recognition Guide (For LLM)

| User phrase contains... | Extract | CLI flag |
|---|---|---|
| "run X" | benchmark name(s) | `-b X` (comma-separated if multiple) |
| "for N times" | run count | `-r N` |
| "with N iterations" | iteration count | `--iterations N` |
| "over ssh" / "via ssh" | connection type | `--ssh-connection` |
| "only <category> tests of X" | test filter | `-t <resolved test names>` (see leaf skill) |
| "all benchmarks" / benchmark omitted | run every active benchmark | omit `-b`, use `run-all-benchmarks/SKILL.md` |
| "except X" / "excluding X" | skip list | `--skip X` |
| "default params" / "default parameters" / "with defaults" | no overrides | omit `-r`/`--iterations` |
| "bypass/skip the cooldown/gap" | gap bypass | `--bypass-gap` (only if explicitly requested) |
| "trend analysis" / "all historical runs" | deep RCA | `--rca-all-runs` (triggers Tier 4 trend detection) |
| "all iterations" (for RCA) | deep iteration RCA | `--rca-all-iterations` |
| "report mode" / "report only" | run without RCA | `--report-mode` (deprecated) |
| "with rca" / "perform rca" / "rca on all" | run RCA on ALL benchmarks | `--full-rca` (or legacy `--rca-mode`) |
| "rca on regressed" / "smart rca" / "if regressed" | run 2-tier RCA ONLY on regressed | omit flag (default `--smart-rca`) |
| "collect telemetry" / "get stats" / "record stats" | optional telemetry collection | `--collect-telemetry` |

## Common Patterns (Copy-Paste Ready — Cross-Platform Safe)

Shown here in their **default form** (session already inside `aibench/`, no `cd` prefix). Only add a `cd aibench; ` prefix (using `;`, never `&&`, so it stays cross-platform safe on Windows PowerShell/CMD, Linux Bash, and macOS Zsh/Bash) if you have explicit evidence the cwd is the parent repo root or an ancestor.

```bash
# Single benchmark, default params, Serial/ADB
python main.py -b <benchmark>

# Single benchmark, N runs
python main.py -b <benchmark> -r <N>

# Single benchmark over SSH
python main.py -b <benchmark> --ssh-connection

# Single benchmark, N runs, over SSH
python main.py -b <benchmark> -r <N> --ssh-connection

# All active benchmarks (Serial/ADB)
python main.py

# All active benchmarks over SSH
python main.py --ssh-connection

# Specific sub-tests only
python main.py -b <benchmark> -t <test1> <test2> --ssh-connection

# Skip specific benchmarks from the active set
python main.py --skip <benchmark1>,<benchmark2> --ssh-connection

# Custom sub-test iteration count
python main.py -b <benchmark> --iterations <N> --ssh-connection

# Multiple named benchmarks
python main.py -b <benchmark1>,<benchmark2> -r <N> --ssh-connection
```

## Parameters (Full CLI Reference)
* `--smart-rca`: (Default) Perform regression detection, then 2-tier RCA ONLY on regressed benchmarks. No flag needed — this is automatic.
* `--full-rca`: Run benchmarks, perform regression detection, and run RCA on ALL benchmarks (legacy `--rca-mode` replacement).
* `--report-mode`: (Deprecated) Run benchmarks and perform regression detection without root-cause analysis (RCA).
* `--rca-mode`: (Deprecated) Use `--full-rca` instead.
* `--collect-telemetry`: Enable device telemetry collection during benchmarks. Optional in `--full-rca`, automatically handled internally by `--smart-rca`.
* `--benchmark`, `-b`: Name of a single benchmark (e.g. `sysbench`) or a comma-separated list of benchmarks (e.g. `sysbench,hackbench,coremark`). If omitted, runs all active benchmarks defined in the config.
* `--config`, `-c`: Path to the config file (defaults to `config/benchmarks.yaml` relative to the aibench folder).
* `--build-id`, `-i`: Identifier for the build being tested. Auto-detected from device via ADB if omitted.
* `--runs`, `-r`: Overrides the number of overall suite runs (default: 1).
* `--iterations`: Overrides the number of iterations for each individual sub-benchmark test (default: 3, unless the leaf skill states a different benchmark-specific default).
* `--bypass-gap`: Skips the 5-minute sequential execution gap constraint.
* `--default-connection`: Activate default mode (logs/telemetry via ADB, benchmarks over Serial). Mutually exclusive with `--ssh-connection`.
* `--ssh-connection`: Activate SSH mode (performs all activities via SSH instead of ADB/Serial).
* `--tests`, `-t`: Space-separated list of individual sub-tests or test types to execute.
* `--skip`: Name of a benchmark to skip, or a comma-separated list of multiple benchmarks to skip.
* `--store-baseline`: After this run completes, stores its aggregated build statistics as the regression-detection-and-rca baseline (see `--baseline-tag`). Only add this when the user explicitly asks to save/store the current build as a baseline/reference.
* `--baseline-tag`: Named baseline slot to store to (with `--store-baseline`) or compare against. Defaults to `"default"` if omitted — only specify this if the user gives the baseline an explicit name.
* `--rca-all-runs`: Overrides default RCA limit (last 3 runs) to compare the target run against *all* previous runs. Enables Tier 4 Trend Detection if ≥4 runs exist.
* `--rca-all-iterations`: Overrides default RCA limit (last 3 iterations) to compare against *all* iterations within the run.

## Examples
Run all benchmarks with automatic Smart RCA (2-tier RCA on regressed only):
```bash
python main.py --ssh-connection --bypass-gap
```

Run all active benchmarks in legacy report mode (no RCA):
```bash
python main.py --report-mode
```

Run a single benchmark over SSH forcing RCA on all runs (even clean ones):
```bash
python main.py -b sysbench --ssh-connection --full-rca
```

Run a benchmark, force telemetry, and perform full RCA:
```bash
python main.py -b coremark --full-rca --collect-telemetry
```

Run multiple benchmarks using a comma-separated list:
```bash
python main.py -b hackbench,sysbench,coremark --ssh-connection
```

Run multiple benchmarks with a custom number of iterations and bypassing the cooling gap:
```bash
python main.py -b hackbench,sysbench --iterations=5 --bypass-gap
```

Run a benchmark and trigger deep multi-run trend analysis (requires ≥4 historical runs):
```bash
python main.py -b sysbench --rca-all-runs
```

Run specific tests for a benchmark:
```bash
python main.py -b sysbench -t sysbench_cpu_prime_single_test sysbench_memory_random_read
```

(Only prepend `cd aibench; ` to any of the above if you have explicit evidence the cwd is the parent repo root or an ancestor of `aibench/`.)

## Flow (Harness-Level Detail)
1. Working directory is resolved per the "Working Directory" section above (no exploration).
2. Check terminal connectivity and ADB readiness (or SSH if specified).
3. Scan active benchmarks configured in `config/benchmarks.yaml` or parse the comma-separated list provided via `-b`.
4. Sequentially trigger individual benchmark skills, validating the 5-minute cooldown between them.
5. Auto-aggregate metrics and generate the unified comparison dashboard reports.

## Outputs & Reporting

All results are saved to `aibench/output/`.
*   Raw results: `output/<benchmark>/build_<id>/run_<run>/results.json`
*   RCA findings: `output/<benchmark>/build_<id>/run_<run>/rca_report.json`
*   Tier 1 diagnostic re-run (if triggered): `output/<benchmark>/build_<id>/run_<run>.1/`
*   HTML Dashboard: `output/reports/index.html`
*   **Excel Report (auto-generated)**: `output/reports/benchmark_report_<build_id>_<YYYYMMDD>_<HHMMSS>.xlsx`

### Excel Report

The Excel report is **automatically generated** alongside the HTML dashboard after every benchmark run — no extra flags or user intervention required.

**What it contains:**
- One tab per device (e.g. `IQ-9075`, `SA8775P`) matching the `QA_Data_Template.xlsx` template
- Only rows for benchmarks that actually ran are populated
- Each populated row shows: **Mean, Min, Max, StdDev, CV(%)** across all runs
- Rows for benchmarks that did not run are filled with `N/A`
- Template formatting and structure are preserved

**File naming:** `benchmark_report_<build_id>_<YYYYMMDD>_<HHMMSS>.xlsx`

**To generate the Excel report standalone** (without re-running benchmarks):
```bash
cd aibench
python -m src.reporting.generate_excel_report
# or with explicit paths:
python -m src.reporting.generate_excel_report --build-history output/reports/build_history.json --device IQ-9075
```

**Prerequisite:** `pip install openpyxl` (if not already installed)

## Error Handling
* **Wrong Directory:** If executed outside the `aibench/` directory, the script will throw a fatal error (`Fatal: main.py must be executed from within the aibench/ directory`). This is expected/cheap to hit if the `cd aibench; ` prefix was omitted or the `cd` silently failed (e.g. typo) — simply retry with the correct prefix rather than exploring the filesystem.
* **Invalid Benchmark Name:** If a benchmark name provided in the comma-separated list does not exist in the config, it will be skipped with a warning, and execution will continue with the valid benchmarks. The skipped benchmarks will be reported in the HTML dashboard.
* **Missing Config:** If the specified config file is not found, the script will throw a fatal error.
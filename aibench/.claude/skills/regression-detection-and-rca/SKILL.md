---
name: regression-detection-and-rca
description: Automatically detects performance regressions (iteration-level, run-level, build-level, and against an explicitly-stored baseline) after every benchmark run, and performs root-cause analysis (RCA) by correlating regressions with telemetry anomalies (thermal, cpufreq, dmesg/OOM, vmstat, top, ftrace).
category: Performance Benchmarking / Root Cause Analysis
---

# Skill: Regression Detection and Root Cause Analysis (RCA)
**Author:** Sarbojit Ganguly <sarbgang@qti.qualcomm.com>

Automatically triggered by `main.py` after **every** benchmark suite run — no explicit invocation is needed. Detects statistically-significant performance regressions and explains *why* they happened using on-device telemetry.

## Why This Skill Exists

Detecting a metric dropped by X% is only half the job. This skill answers the harder question: **"why did it drop?"** by correlating the regression with telemetry anomalies collected during the same run (thermal throttling, CPU frequency drops, OOM kills, memory pressure, I/O wait, scheduler contention/latency, background process interference).

## Automatic Invocation — Driven by Modes

This skill runs automatically after every single suite run completes, but its behavior is governed by the orchestrator mode:
- **`--smart-rca` (default):** Performs regression detection, then 2-tier RCA **only on regressed benchmarks** (Tier 1 lightweight telemetry, Tier 2 conditional ftrace).
- **`--report-mode` (deprecated):** Performs regression detection only, no telemetry.
- **`--rca-mode` (deprecated):** Performs full regression detection + RCA on ALL benchmarks with telemetry. Use `--full-rca` instead.

## Three-Tier Regression & Trend Detection (Iteration-level removed)

| Tier | Trigger Condition | Compares |
|---|---|---|
| **1. Run-level** | ≥2 suite runs exist on disk for this build | previous run (brN-1) vs current run (brN) |
| **2. Build-level** | ≥2 builds exist on disk for this benchmark | same run-index N in the previous build vs the current build (b(N-1)rX vs bNrX) |
| **3. Trend-level** | ≥4 runs exist on disk for this build | multi-run history (CUSUM, Mann-Kendall) vs target run |

*(Note: Iteration-level comparison has been completely removed to reduce noise. Outlier detection is still handled internally by the benchmarks.)*

All applicable tiers fire on every invocation (they are not mutually exclusive) — e.g. a benchmark on its 5th run, on its 2nd build, will get Tier 1 + Tier 2 + Tier 3 comparisons, each with its own regression/RCA verdict.

## Consensus-Based Statistical Detection

Instead of brittle single-method checks (like simple Z-scores), the engine uses a robust multi-method consensus approach:
- **Primary:** Median-based delta + Mann-Whitney U test (non-parametric)
- **Secondary:** Cohen's d effect size + 25th percentile quantile comparison
- **Trend (Tier 4):** CUSUM (Cumulative Sum Control Chart) for sustained shifts + Mann-Kendall test for monotonic downward trends
- **Confidence Scoring:** 95% for primary consensus, 75% for partial matches.

By default this consensus logic runs as deterministic Python (`src/reporting/regression_detector.py`). Passing `--rca-use-ai` routes regression detection (and RCA, below) through the same Chain-of-Thought logic instead, executed directly against the raw per-iteration data by the local `claude` CLI (see `scripts/ai_skill_client.py`), with automatic fallback to the Python engine if the AI call fails, times out, or returns a result that doesn't match the expected schema — the pipeline never blocks on AI availability.

## Agent Override Flags

By default, the engine bounds its analysis to the last 3 runs to save compute. AI agents can override this when deeper historical context is requested by the user:
- `--rca-all-runs`: Compares the target run against *all* previous runs on disk (enables Trend Analysis if ≥4 runs exist).

## Quick Reference for AI Agents

**Do NOT explore `main.py --help` — this skill documentation is complete and authoritative.** Use the exact commands below based on user intent:

### Mode Selection (Always Explicit)

**Default behavior:** Smart RCA is now the default. Use `--smart-rca` explicitly or omit both flags.

| User Intent | Exact Command | Mode |
|---|---|---|
| Run all benchmarks with defaults over SSH | `python main.py --ssh-connection` | Smart RCA (default) |
| Run all benchmarks over SSH and bypass validation gaps | `python main.py --ssh-connection --bypass-gap` | Smart RCA (default) |
| Run all benchmarks and perform RCA on regressed only | `python main.py --ssh-connection --smart-rca` | Smart RCA (explicit) |
| Run all benchmarks and perform RCA on ALL (legacy) | `python main.py --ssh-connection --full-rca --collect-telemetry` | Full RCA |
| Run all benchmarks, regression detection only (legacy) | `python main.py --ssh-connection --report-mode` | Report (deprecated) |
| Run all benchmarks and analyze trends across all runs | `python main.py --ssh-connection --rca-all-runs` | Smart RCA (default) |
| Store current run as baseline for future comparisons | `python main.py --ssh-connection --store-baseline` | Smart RCA (default) |

**Key flags:**
- `--smart-rca`: Perform regression detection, then collect telemetry and run RCA ONLY on regressed benchmarks. **(Default behavior)**
- `--full-rca`: Collect telemetry and run RCA on ALL benchmarks regardless of regression status.
- `--report-mode`: Regression detection only. No telemetry or RCA. **(Deprecated)**
- `--rca-mode`: Same as `--full-rca`. **(Deprecated)**
- `--ssh-connection`: Execute benchmarks over SSH (default is ADB/Serial)
- `--bypass-gap`: Skip validation gaps (not `--bypass-gaps`)
- `--rca-all-runs`: Compare target run against all previous runs (enables Trend Analysis if ≥4 runs exist)
- `--rca-use-ai`: Route regression detection and RCA through the AI-driven Chain-of-Thought skills (via the local `claude` CLI) before falling back to the deterministic Python engine on any failure. **(Default: Python engine only)**

**Elapsed time reporting:** Automatically logged in the run output and dashboard. No special flag needed.

**Decision Tree for Mode Selection:**
1. In almost all cases, use the default (no mode flag or `--smart-rca`).
2. Only use `--full-rca` if the user explicitly demands telemetry for *all* benchmarks, even those that didn't regress.

## Smart RCA Workflow (2-Tier Telemetry)

### Tier 1: Lightweight Telemetry
- **Tools:** vmstat (1 sec), dmesg (continuous), thermal (5 sec), cpufreq (500 ms)
- **Overhead:** <2%
- **Detects:** Thermal throttle, OOM, I/O pressure, CPU frequency drops (DVFS)
- **Re-run storage:** Stored separately as `run_X.1` (e.g. `run_20260914_001.1`)

### Tier 2: Lightweight ftrace (Conditional)
- **Tools:** Tier 1 + ftrace (nop tracer, sched events: sched_wakeup, sched_switch, sched_migrate_task)
- **Duration:** 5-10 seconds
- **Overhead:** 3-4%
- **Detects:** Wake-up latency, task migration, scheduler load
- **Trigger:** Only executed if Tier 1 findings are inconclusive
- **Re-run storage:** Stored separately as `run_X.2`

### Workflow
1. Run benchmarks with NO telemetry (clean baseline)
2. Detect regressions
3. **If regressed:** Re-run ONLY regressed benchmarks with Tier 1 telemetry
4. Analyze Tier 1 telemetry
5. **If clear cause found:** Report RCA, DONE
6. **If cause unclear:** Re-run with Tier 2 telemetry (includes ftrace)
7. Analyze Tier 2 telemetry and report final RCA

## Error Handling

- **Device offline during re-run:** Skip RCA for that benchmark, log warning, continue
- **Telemetry collection fails:** Use partial telemetry, log warning, continue
- **ftrace unavailable (e.g. debugfs locked):** Skip Tier 2, report Tier 1 findings, log warning
- **Re-run doesn't reproduce regression:** Reported as transient, lower confidence score

**If a user request is ambiguous or uses non-standard phrasing (e.g., "bypass any gaps"), map it to the closest intent above and execute the corresponding command. Do not run exploratory commands like `--help`.**

## Explicit Baseline Comparison (User-Controlled)

There is **no automatic "golden build"**. A baseline is only established when the user explicitly says so:

```
"run all benchmarks in the current build and store it as a baseline"
  -> python main.py --store-baseline --ssh-connection
```

A later invocation compares against that stored baseline automatically (in addition to the tiers above):

```
"new build is now flashed, run all benchmarks, compare with previously stored baseline,
 detect regression if any, perform root cause analysis for all regressions detected."
  -> python main.py --ssh-connection --rca-mode
     (baseline comparison happens automatically if a baseline was previously stored)
```

Multiple named baselines are supported via `--baseline-tag <name>` (both when storing and when comparing). Omitting it always uses the `default` tag.

## Dashboard Visualization (`output/reports/index.html`)

The aggregated summary dashboard (rendered by `render_dashboard()` in `main.py` from `config/templates/summary_dashboard.html`) automatically highlights regressions **for the latest run/build column of each benchmark section**, using the same `regressions` dict already computed by the dashboard's existing history-comparison loop (no extra computation, no new Python logic):

- **Regressed benchmark sections are sorted to the top** of the table (stable sort — relative order is otherwise unchanged).
- **Regressed rows** get a red background tint (`.row-regressed`).
- **The regressed metric's latest-column cell** is bold red with a red left border (`.cell-regressed`).
- **A healthy (non-regressed) latest-column cell** — i.e. a comparison was performed and came back clean — is colored green (`.cell-healthy-latest`).
- Older/historical columns and single-run benchmarks (where no run/build comparison was possible yet) are **never colored**, since no regression verdict exists for them.

This is a purely additive, presentation-layer enhancement to the existing dashboard template — it does not change `main.py`'s aggregation logic, the `RegressionDetector`/`RCADetector` APIs, or any JSON output schema. See `aibench/tests/test_summary_dashboard_template.py` for the full behavior contract (8 tests covering empty state, single-run/no-comparison, regressed, healthy, sort order, and multi-column rendering).

## Output

Every run writes `<run_dir>/rca_report.json` containing:
- `comparisons[]` — one entry per tier/baseline comparison that had matching metrics, each with:
  - `label` — human-readable description of what was compared
  - `regression_detected` — bool
  - `regressions` — per-metric `RegressionDetector` / `TrendDetector` output (Consensus flags, Mann-Whitney p-value, Cohen's d, CUSUM drift, delta %)
  - `rca` — per-regressed-metric `RCADetector` output (`cause`, `confidence`, `confidence_basis`, `evidence[]`, `recommendation`)
- `telemetry_warnings[]` — any missing telemetry file (e.g. `vmstat_metrics_*.log not found`) is recorded here as a **warning**, never a fatal error. Partial analysis continues with whatever telemetry IS available.
- `used_fallback_thresholds` — true if the device codename in `config/benchmarks.yaml`'s `active_device` wasn't found under `telemetry_thresholds.devices`, meaning generic fallback thresholds were used instead of device-tuned ones.

## Telemetry Sources Used for RCA

| Source | File Pattern | What It Detects |
|---|---|---|
| cpufreq | `cpufreq_metrics_*.log` | CPU frequency drops >threshold (DVFS) |
| dmesg | `dmesg_metrics_*.log` | Thermal throttle events, OOM kills |
| thermal | `thermal_metrics_*.csv` | CPU/DDR temperature spikes |
| vmstat | `vmstat_metrics_*.log` | Context-switch spikes, page-fault spikes, I/O wait spikes, low free memory |
| top | `top_metrics_*.log` | Per-process CPU% anomalies, RSS growth (leak proxy), zombie processes |
| ftrace | `ftrace_metrics_*.log` | Scheduler wake-up latency spikes, excessive task migration (nop tracer, `sched_wakeup`/`sched_switch`/`sched_migrate_task` events only, for minimal overhead) |

ftrace is **optional telemetry** — if `/sys/kernel/debug/tracing` is unavailable on the device (debugfs not mounted, locked-down build), `start_telemetry_device.sh` logs a warning and continues; RCA simply skips scheduler-latency-based causes for that run and falls back to other evidence categories.

## Device-Specific Thresholds

All anomaly thresholds (thermal limits, frequency-drop %, vmstat spike thresholds, etc.) are sourced from `config/benchmarks.yaml`'s `telemetry_thresholds.devices.<codename>` section — **not hardcoded in Python**. The active device is selected via the `active_device` key. Phase 1 ships generic, conservative values for `IQ-9075` (codename "Lemans"); these are meant to be tuned with real hardware-characterized data later without any code changes.

## RCA Confidence Methodology

Confidence percentages are **not statistically calibrated probabilities** — they are fixed, documented weights per decision-tree branch based on how directly the available telemetry evidence explains the regression (90-95% = direct kernel-logged evidence; 65-79% = single-signal circumstantial evidence; <65% = no corroborating evidence, cause genuinely ambiguous). See the `confidence_basis` field in every RCA entry, and the module docstring in `src/reporting/rca_detector.py`, for the full explanation. This same decision tree, confidence weights, and `confidence_basis` wording are mirrored in `scripts/rca_detector.md` for the AI-driven path (`--rca-use-ai`), so a given anomaly pattern is explained identically regardless of which path produced the verdict.

## Files

```
aibench/.claude/skills/regression-detection-and-rca/
├── SKILL.md                    (this file)
├── default/
│   └── SKILL.md                (Phase 1's only variant; future variants like
│                                 "lightweight" or "deep-analysis" can be added
│                                 without restructuring)
└── scripts/
    ├── run_rca.py               Main orchestrator (3-tier + baseline comparison)
    ├── ai_skill_client.py       Shells out to the local `claude` CLI to run
    │                            regression_detector.md / rca_detector.md
    │                            directly against raw data (--rca-use-ai path)
    ├── regression_detector.md   Chain-of-Thought spec mirroring RegressionDetector
    ├── rca_detector.md          Chain-of-Thought spec mirroring RCADetector
    ├── benchmark_knowledge.md   Per-benchmark/per-metric direction reference
    ├── telemetry_thresholds.py  Device-threshold config loader
    ├── baseline_manager.py      Explicit baseline store/load/list/delete
    └── metrics_extractor.py     Per-benchmark iteration-level metric extraction
```

Core regression/RCA/telemetry-parsing logic lives in `src/reporting/regression_detector.py`, `src/reporting/rca_detector.py`, and `src/reporting/telemetry_parser.py` (enhanced in place, not duplicated) so the existing dashboard rendering pipeline (`main.py`'s `render_dashboard()`) and this skill share the exact same, single-source-of-truth detection logic.

## Related Bug Fix

`src/utils/telemetry/stop_telemetry_device.sh` previously reported false-positive "some processes still running" warnings because its process-cleanup verification matched kernel IRQ worker threads (e.g. `[irq/222-c251000.thermal-sensor]`) shown in brackets by `ps aux`, which are unrelated to the actual user-space telemetry collectors it starts/stops. This is fixed by excluding bracketed kernel-thread lines from the verification grep.
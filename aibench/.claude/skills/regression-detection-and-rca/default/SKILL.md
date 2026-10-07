---
name: regression-detection-and-rca-default
description: Default (Phase 1) variant of the regression-detection-and-rca skill — generic, threshold-based regression detection and root-cause analysis using all available telemetry (cpufreq, dmesg, thermal, vmstat, top, ftrace).
category: Performance Benchmarking / Root Cause Analysis
---

# Skill Variant: Default RCA (Phase 1)
**Author:** Sarbojit Ganguly <sarbgang@qti.qualcomm.com>

This is the **only variant** implemented in Phase 1 of the `regression-detection-and-rca` skill (see the parent `../SKILL.md` for full details). It is invoked automatically — there is no manual selection needed.

## Scope of This Variant

- Generic, threshold-based anomaly detection (no device-specific ML/statistical models yet — see parent skill's "Device-Specific Thresholds" section).
- Uses **all** available telemetry sources every time: cpufreq, dmesg, thermal, vmstat, top, ftrace. No selective/lightweight telemetry mode yet.
- Runs the full 3-tier comparison (iteration/run/build) plus any explicitly-stored baseline comparison, every single time, with no way to disable individual tiers.

## Future Variants (Not Yet Implemented)

The `default/` folder structure exists so that future phases can add sibling variants without restructuring the skill, for example:
- `lightweight/` — skip ftrace/vmstat/top parsing for faster CI/CD feedback loops, using only cpufreq+dmesg+thermal.
- `deep-analysis/` — add `perf record`/`perf sched` integration for deeper profiling when the default variant's RCA confidence is <65% ("Ambiguous" causes).

Until those are built, this `default/` variant is the entire implementation, and it is what `main.py` always invokes.

## Entry Point

`main.py` imports `run_rca_for_run` directly from `../scripts/run_rca.py` — this variant folder currently only exists for documentation/discoverability purposes (consistent with the `run-glmark2/default/` pattern elsewhere in this skills library) and does not have its own separate script path in Phase 1.
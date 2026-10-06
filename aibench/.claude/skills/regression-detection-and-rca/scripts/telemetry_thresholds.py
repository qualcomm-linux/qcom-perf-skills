"""
telemetry_thresholds.py - Loads device/SoC-specific telemetry & regression
thresholds from config/benchmarks.yaml's `telemetry_thresholds` section.

Part of the regression-detection-and-rca skill's scripts/ folder.

Design rationale (Phase 1 / generic threshold-based approach):
- Thresholds are intentionally NOT hardcoded in Python. They live in
  aibench/config/benchmarks.yaml under `telemetry_thresholds.devices.<codename>`
  so they can be tuned per-SoC without touching code.
- If the config is missing the section entirely, or the requested device
  codename isn't found, this module falls back to conservative generic
  defaults (mirroring the historical hardcoded values that used to live in
  regression_detector.py/telemetry_parser.py) so the RCA pipeline degrades
  gracefully rather than crashing.

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

from typing import Any, Dict, Optional

# Conservative, hardcoded fallback defaults used ONLY if benchmarks.yaml is
# missing the telemetry_thresholds section entirely, or the requested
# device codename isn't found there. This guarantees the RCA pipeline never
# crashes due to a missing/misconfigured threshold section -- it degrades
# to sane generic defaults instead (a warning should be surfaced by the
# caller when this fallback path is taken).
FALLBACK_THRESHOLDS: Dict[str, Any] = {
    "codename": "generic-fallback",
    "thermal": {
        "cpu_high_temp_c": 85,
        "ddr_high_temp_c": 75,
        "cpu_throttle_temp_c": 95,
    },
    "cpu_frequency": {
        "drop_threshold_percent": 20,
    },
    "regression": {
        "throughput_threshold_percent": -5,
        "latency_threshold_percent": 10,
        "latency_absolute_warn_ms": 500,
        "latency_absolute_fail_ms": 2000,
        "stability_gate_cv_percent": 10,
        "use_median_for_comparison": True,
        "use_mann_whitney": True,
        "use_cohens_d": True,
        "use_quantile": True,
        "consensus_threshold": 2,
        "cohens_d_threshold": 0.5,
    },
    "vmstat": {
        "context_switch_spike_per_sec": 50000,
        "page_fault_spike_per_sec": 100000,
        "io_wait_spike_percent": 30,
        "free_memory_low_mb": 50,
    },
    "top": {
        "single_process_cpu_percent_high": 90,
        "rss_growth_leak_percent": 50,
    },
    "ftrace": {
        "sched_wakeup_latency_us_high": 5000,
        "migration_count_high": 500,
    },
    "memory": {
        "oom_kill_threshold": 1,
    },
}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merges `override` onto `base`, with `override` values winning."""
    result = dict(base)
    for key, val in override.items():
        if isinstance(val, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def load_thresholds(config: Dict[str, Any], device_override: Optional[str] = None) -> Dict[str, Any]:
    """
    Resolves the telemetry_thresholds block for the active (or overridden)
    device from an already-loaded benchmarks.yaml config dict.

    Args:
        config: The full benchmarks.yaml dict (as returned by
            src.utils.config_loader.load_yaml_config).
        device_override: Optional explicit device codename to use instead
            of config["active_device"]. Primarily for testing / manual
            override scenarios.

    Returns:
        A dict with the same shape as FALLBACK_THRESHOLDS. Any sub-keys
        missing from the resolved device's config are backfilled from
        FALLBACK_THRESHOLDS, so downstream code can always safely index
        into every expected key without KeyError.
    """
    device_name = device_override or config.get("active_device")
    devices = config.get("telemetry_thresholds", {}).get("devices", {})

    resolved: Dict[str, Any] = {}
    used_fallback = True
    if device_name and device_name in devices:
        resolved = devices[device_name]
        used_fallback = False
    elif devices:
        # No matching device_name -- fall back to the first defined device
        # rather than the hardcoded generic defaults, since a
        # partially-correct device profile is still better than none.
        first_key = next(iter(devices))
        resolved = devices[first_key]
        used_fallback = False

    merged = _deep_merge(FALLBACK_THRESHOLDS, resolved)
    merged["_used_fallback"] = used_fallback
    merged["_resolved_device_name"] = device_name if not used_fallback else None
    return merged
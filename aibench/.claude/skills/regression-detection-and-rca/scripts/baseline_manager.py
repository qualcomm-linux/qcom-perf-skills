"""
baseline_manager.py - Explicit baseline storage/retrieval for regression comparison.

Per project requirements, there is no automatic "golden build" -- a baseline
is only established when the user explicitly requests it (e.g. "run all
benchmarks in the current build and store it as a baseline"). A later
invocation ("new build is now flashed, run all benchmarks, compare with
previously stored baseline...") retrieves that stored baseline and diffs
against the new build's results.

Baselines are stored as JSON under:
    aibench/output/.baselines/<benchmark_name>__<baseline_tag>.json

`baseline_tag` defaults to "default" if the user doesn't give it an explicit
name, so "store as baseline" / "compare with baseline" (unqualified) always
resolve to the same slot. Multiple named baselines are supported for users
who want to keep more than one reference point (e.g. "store as baseline
'pre-regression-fix'").

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

BASELINE_SUBDIR = ".baselines"
DEFAULT_TAG = "default"


def _baseline_dir(output_dir: Path) -> Path:
    d = Path(output_dir) / BASELINE_SUBDIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _baseline_path(output_dir: Path, benchmark_name: str, tag: str = DEFAULT_TAG) -> Path:
    safe_tag = tag.replace("/", "_").replace("\\", "_")
    return _baseline_dir(output_dir) / f"{benchmark_name}__{safe_tag}.json"


def store_baseline(output_dir: Path, benchmark_name: str, build_id: str,
                    statistics: Dict[str, Any], tag: str = DEFAULT_TAG) -> Path:
    """
    Persists the given `statistics` dict (same shape as build_analysis.json's
    "statistics" key -- i.e. {metric_name: {"mean":..., "stddev":..., ...}})
    as the named baseline for `benchmark_name`.

    Returns the path the baseline was written to.
    """
    payload = {
        "metadata": {
            "benchmark_name": benchmark_name,
            "build_id": build_id,
            "baseline_tag": tag,
            "stored_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        },
        "statistics": statistics,
    }
    path = _baseline_path(output_dir, benchmark_name, tag)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return path


def load_baseline(output_dir: Path, benchmark_name: str, tag: str = DEFAULT_TAG) -> Optional[Dict[str, Any]]:
    """
    Loads a previously-stored baseline for `benchmark_name`/`tag`.
    Returns None if no such baseline exists (caller must handle this as a
    "no baseline available" case -- e.g. skip comparison, warn the user).
    """
    path = _baseline_path(output_dir, benchmark_name, tag)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def list_baselines(output_dir: Path) -> Dict[str, Dict[str, Any]]:
    """
    Returns {baseline_filename_stem: metadata_dict} for all stored baselines,
    useful for a "what baselines do I have?" query.
    """
    result = {}
    d = _baseline_dir(output_dir)
    if not d.exists():
        return result
    for f in d.glob("*.json"):
        try:
            with open(f, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            result[f.stem] = data.get("metadata", {})
        except Exception:
            continue
    return result


def delete_baseline(output_dir: Path, benchmark_name: str, tag: str = DEFAULT_TAG) -> bool:
    """Deletes a stored baseline. Returns True if a file was actually removed."""
    path = _baseline_path(output_dir, benchmark_name, tag)
    if path.exists():
        path.unlink()
        return True
    return False
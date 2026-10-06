"""
lifecycle.py - Manage global run constraints like sequential gap enforcement.

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import time
from pathlib import Path
from src.utils.logger import phase_logger

class GapValidationError(Exception):
    """Raised when the 5-minute gap between benchmark executions is violated."""

def validate_and_enforce_gap(output_dir: Path, bypass_gap: bool = False) -> None:
    """
    Validates that at least 5 minutes (300 seconds) have elapsed since the completion
    of the most recent benchmark run.
    
    If violated:
    - If bypass_gap is True: logs a warning and proceeds.
    - If bypass_gap is False: raises GapValidationError.
    """
    if bypass_gap:
        phase_logger.warning("Bypassing the 5-minute sequential execution gap check.")
        return

    output_path = Path(output_dir)
    if not output_path.exists():
        return

    # Find the most recently modified results.json or log files
    last_mtime = 0.0
    for results_file in output_path.glob("**/results.json"):
        mtime = results_file.stat().st_mtime
        if mtime > last_mtime:
            last_mtime = mtime

    # Also check dmesg or other logs if results.json isn't present yet
    for log_file in output_path.glob("**/*.log"):
        mtime = log_file.stat().st_mtime
        if mtime > last_mtime:
            last_mtime = mtime

    if last_mtime == 0.0:
        # No previous runs found, gap is valid
        return

    elapsed = time.time() - last_mtime
    required_gap = 300.0  # 5 minutes
    
    if elapsed < required_gap:
        remaining = required_gap - elapsed
        msg = (
            f"Gap violation! Only {elapsed:.1f}s have elapsed since the last run. "
            f"A minimum 5-minute (300s) gap is required to prevent thermal skewing. "
            f"Please wait another {remaining:.1f}s, or run with --bypass-gap."
        )
        phase_logger.error(msg)
        raise GapValidationError(msg)
    
    phase_logger.info(f"Gap validation successful. {elapsed:.1f}s elapsed since last run.")
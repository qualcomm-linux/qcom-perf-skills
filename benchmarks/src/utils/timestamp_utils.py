"""
timestamp_utils.py - Generate collision-proof, sorted run names
Implements run_YYYYMMDD_HHMMSS_sequence with filesystem-backed collision check.

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import re
from datetime import datetime
from pathlib import Path

def generate_run_name(output_dir: Path, benchmark_name: str, build_id: str, base_timestamp: str = None) -> str:
    """
    Generates a unique, timestamp-sorted run name in the format:
        run_YYYYMMDD_HHMMSS_sequence (e.g., run_20260820_143022_001)

    Actively checks the filesystem under:
        output_dir / benchmark_name / build_<build_id> /
    and increments the sequence suffix if a directory with the same second-level
    timestamp already exists.
    """
    if base_timestamp is None:
        now = datetime.now()
        timestamp = now.strftime("%Y%m%d_%H%M%S")
    else:
        timestamp = base_timestamp
        
    parent_dir = Path(output_dir) / benchmark_name / f"build_{build_id}"
    
    sequence = 1
    if parent_dir.exists():
        pattern = re.compile(rf"^run_{timestamp}_(\d{{3}})$")
        existing_sequences = []
        for path in parent_dir.iterdir():
            if path.is_dir():
                match = pattern.match(path.name)
                if match:
                    existing_sequences.append(int(match.group(1)))
                    
        if existing_sequences:
            sequence = max(existing_sequences) + 1
            
    return f"run_{timestamp}_{sequence:03d}"
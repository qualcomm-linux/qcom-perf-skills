"""
factory.py - Factory for loading benchmarks dynamically
Delegates to the plugin-based BenchmarkRegistry.

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

from pathlib import Path
from typing import Any, Dict
from src.benchmark.registry import BenchmarkRegistry

def get_benchmark(name: str, config: Dict[str, Any], run_dir: Path):
    """
    Looks up a benchmark by name from the registry, instantiates it with 
    its config and output directory, and returns the instance.
    """
    name_lower = name.lower().strip()
    benchmark_class = BenchmarkRegistry.get(name_lower)
    
    if not benchmark_class:
        registered = list(BenchmarkRegistry.list_all().keys())
        raise ValueError(
            f"Benchmark '{name}' is not supported. "
            f"Registered benchmarks: {registered}"
        )
        
    return benchmark_class(name_lower, config, run_dir)
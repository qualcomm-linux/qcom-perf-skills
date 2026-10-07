"""
outlier_registry.py - Registry for benchmark-specific outlier detectors.
Auto-discovers detector modules.

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import importlib
from pathlib import Path
from typing import Type, Dict
import logging

logger = logging.getLogger(__name__)

class OutlierDetectorRegistry:
    _registry: Dict[str, Type] = {}
    
    @classmethod
    def register(cls, benchmark_name: str, detector_class: Type):
        """Manually register an outlier detector"""
        cls._registry[benchmark_name] = detector_class
        
    @classmethod
    def auto_discover(cls):
        """Auto-discover all outlier_detector_*.py modules"""
        reporting_dir = Path(__file__).parent
        for module_file in reporting_dir.glob("outlier_detector_*.py"):
            if module_file.name == "outlier_detector_base.py" or module_file.name.startswith("_"):
                continue
            
            benchmark_name = module_file.stem.replace("outlier_detector_", "")
            try:
                module = importlib.import_module(f"src.reporting.{module_file.stem}")
                if hasattr(module, "OutlierDetector"):
                    cls.register(benchmark_name, module.OutlierDetector)
            except Exception as e:
                logger.warning(f"Failed to load outlier detector for {benchmark_name}: {e}")
    
    @classmethod
    def get(cls, benchmark_name: str):
        """Get outlier detector instance for a benchmark"""
        if not cls._registry:
            cls.auto_discover()
            
        detector_class = cls._registry.get(benchmark_name)
        if not detector_class:
            raise ValueError(
                f"No outlier detector found for benchmark: {benchmark_name}. "
                f"Registered: {list(cls._registry.keys())}"
            )
            
        return detector_class()
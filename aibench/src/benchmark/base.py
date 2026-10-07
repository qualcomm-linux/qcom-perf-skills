"""
base.py - Abstract Base Class for all benchmarks
Defines the lifecycle and state properties.

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict
from src.utils.logger import phase_logger

class BenchmarkBase(ABC):
    """
    Abstract Base Class outlining the unified lifecycle of a benchmark.
    Provides standard hooks for setup, run, and teardown, integrated with the PhaseLogger.
    """
    def __init__(self, name: str, config: Dict[str, Any], run_dir: Path):
        self.name = name
        self.config = config
        self.run_dir = Path(run_dir)
        
    def execute_lifecycle(self, serial_executor, adb_manager) -> Dict[str, Any]:
        """
        Executes the entire lifecycle of the benchmark, switching log files
        and handling errors gracefully.
        """
        phase_logger.configure_run_dir(self.run_dir)
        results = {}
        
        try:
            # 1. Setup Phase
            phase_logger.set_phase("setup")
            self.setup(serial_executor, adb_manager)
            
            # 2. Run Phase
            phase_logger.set_phase("benchmark")
            results = self.run(serial_executor, adb_manager)
            
        except Exception as exc:
            phase_logger.error(f"Error during lifecycle execution of {self.name}: {exc}")
            raise exc
            
        finally:
            # 3. Teardown Phase
            phase_logger.set_phase("teardown")
            try:
                self.teardown(serial_executor, adb_manager)
            except Exception as teardown_exc:
                phase_logger.error(f"Error during teardown of {self.name}: {teardown_exc}")
            phase_logger.end_phase()
            
        return results

    @abstractmethod
    def setup(self, serial_executor, adb_manager) -> None:
        """
        Performs on-device and host setup required before the benchmark runs.
        E.g., pre-conditioning storage, starting telemetry, pushing assets.
        """
        pass

    @abstractmethod
    def run(self, serial_executor, adb_manager) -> Dict[str, Any]:
        """
        Executes the main benchmark command(s) and parses the results.
        Returns a dictionary of metrics.
        """
        pass

    @abstractmethod
    def teardown(self, serial_executor, adb_manager) -> None:
        """
        Cleans up the device state after the benchmark runs.
        E.g., stopping telemetry, pulling logs/results, deleting temporary files.
        """
        pass
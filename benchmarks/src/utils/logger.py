"""
logger.py - Centralized logging with dynamic phase switching
Produces setup.log, benchmark.log, and teardown.log in the run directory.

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import os
import sys
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("benchmarks")

class PhaseLogger:
    """
    A logger that dynamically routes messages to setup.log, benchmark.log,
    and teardown.log depending on the active benchmark lifecycle phase.
    """
    def __init__(self, name: str = "benchmarks"):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.INFO)
        
        # Prevent messages from propagating to the root logger. Without this,
        # any other module that configures the root logger (e.g. via
        # logging.basicConfig()) would cause every message emitted here to
        # be duplicated (once via this logger's own handlers, once via the
        # root logger's handlers through propagation).
        self.logger.propagate = False
        
        # Avoid duplicating handlers if logger is re-initialized
        self.logger.handlers.clear()
        
        # Always attach console handler
        self.console_handler = logging.StreamHandler(sys.stdout)
        self.console_formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        self.console_handler.setFormatter(self.console_formatter)
        self.logger.addHandler(self.console_handler)
        
        self.current_phase_handler: Optional[logging.FileHandler] = None
        self.centralized_handler: Optional[logging.FileHandler] = None
        self.run_dir: Optional[Path] = None

    def add_centralized_handler(self, log_dir: Path, timestamp: str):
        """
        Adds a centralized file handler that captures all logs across all phases.
        Filename matches format: log-<timestamp>.log
        """
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        
        log_file = log_dir / f"log-{timestamp}.log"
        
        # Remove existing centralized handler if any
        if self.centralized_handler:
            self.logger.removeHandler(self.centralized_handler)
            self.centralized_handler.close()
            
        handler = logging.FileHandler(log_file, mode="a", encoding="utf-8")
        handler.setLevel(logging.INFO)
        handler.setFormatter(self.console_formatter)  # Include same formatting as console
        
        self.logger.addHandler(handler)
        self.centralized_handler = handler

    def configure_run_dir(self, run_dir: Path):
        """Configure the destination directory for phase-specific logs."""
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)

    def set_phase(self, phase_name: str):
        """
        Transition to a new phase (e.g. 'setup', 'benchmark', 'teardown').
        Closes the previous file handler and opens a new one named <phase_name>.log.
        """
        self.end_phase()
        
        if not self.run_dir:
            # Fallback to console-only if run directory is not yet set
            return
            
        log_file = self.run_dir / f"{phase_name}.log"
        handler = logging.FileHandler(log_file, mode="a", encoding="utf-8")
        handler.setLevel(logging.INFO)
        
        # Simple formatter for file logs (just message, since these are phase-isolated logs)
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        handler.setFormatter(formatter)
        
        self.logger.addHandler(handler)
        self.current_phase_handler = handler
        self.logger.info(f"=== Started Lifecycle Phase: {phase_name} ===")

    def end_phase(self):
        """Close and remove the current phase file handler."""
        if self.current_phase_handler:
            self.logger.info("=== Ended Lifecycle Phase ===")
            self.current_phase_handler.close()
            self.logger.removeHandler(self.current_phase_handler)
            self.current_phase_handler = None

    def info(self, msg: str, *args, **kwargs):
        self.logger.info(msg, *args, **kwargs)

    def warning(self, msg: str, *args, **kwargs):
        self.logger.warning(msg, *args, **kwargs)

    def error(self, msg: str, *args, **kwargs):
        self.logger.error(msg, *args, **kwargs)

    def debug(self, msg: str, *args, **kwargs):
        self.logger.debug(msg, *args, **kwargs)

# Global phase logger instance
phase_logger = PhaseLogger()
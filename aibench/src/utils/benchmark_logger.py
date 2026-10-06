#!/usr/bin/env python3
"""
benchmark_logger.py - Common structured logging utility for benchmark harnesses.

Purpose
-------
Provides a single, lightweight, stdlib-only logging facility that any
benchmark harness (sysbench, tiobench, or future additions) can adopt for
consistent, structured, machine-readable logging.

This module is standalone - it is NOT currently wired into any existing
harness or into outlier_detector.py. It is provided so harnesses can adopt
it incrementally, on their own schedule, without requiring a coordinated
migration.

Design Notes
------------
- Stdlib only: logging, json, datetime, pathlib, typing. No third-party
  dependencies.
- Each BenchmarkLogger instance wraps a standard `logging.Logger` obtained
  via `logging.getLogger(name)`, so it composes cleanly with any existing
  logging configuration (handlers, formatters, root logger settings) the
  calling process may already have in place.
- Structured events are emitted as a single JSON object per log line
  (JSONL-friendly), making them easy to grep, tail, or parse offline.
- File logging is optional and opt-in; console logging (via the standard
  logging framework) is always active through the wrapped logger.

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

__all__ = ["BenchmarkLogger"]


# --------------------------------------------------------------------------
# Predefined event type constants (optional convenience; any string may be
# passed as event_type - these are not enforced).
# --------------------------------------------------------------------------

class Events:
    """Predefined event-type string constants for common benchmark
    lifecycle occurrences. Purely a convenience - `BenchmarkLogger.event()`
    accepts any string."""

    # Benchmark lifecycle
    BENCHMARK_START = "BENCHMARK_START"
    BENCHMARK_END = "BENCHMARK_END"
    BENCHMARK_ERROR = "BENCHMARK_ERROR"

    # Iteration lifecycle
    ITERATION_START = "ITERATION_START"
    ITERATION_END = "ITERATION_END"

    # Outlier detection
    OUTLIER_DETECTED = "OUTLIER_DETECTED"
    OUTLIER_SKIPPED = "OUTLIER_SKIPPED"
    OUTLIER_DISCARDED = "OUTLIER_DISCARDED"

    # Device / system
    DEVICE_STATE = "DEVICE_STATE"
    TELEMETRY_START = "TELEMETRY_START"
    TELEMETRY_STOP = "TELEMETRY_STOP"

    # Generic
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    DEBUG = "DEBUG"


_LEVEL_MAP = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}


class BenchmarkLogger:
    """
    Structured logger for a single benchmark harness run.

    Wraps a standard `logging.Logger` and emits structured JSON payloads
    for both discrete "events" (`event()`) and simple text messages
    (`info()`, `warning()`, `error()`, `debug()`).

    Instances are created via the `create()` factory method, not by
    calling the constructor directly.
    """

    def __init__(
        self,
        logger: logging.Logger,
        harness_name: str,
        run_id: str,
    ) -> None:
        self._logger = logger
        self._harness_name = harness_name
        self._run_id = run_id

    # ----------------------------------------------------------------
    # Factory
    # ----------------------------------------------------------------

    @classmethod
    def create(
        cls,
        harness_name: str,
        run_id: str = "",
        log_level: str = "INFO",
        enable_file_logging: bool = False,
        log_dir: Optional[str] = None,
    ) -> "BenchmarkLogger":
        """
        Create and configure a BenchmarkLogger instance for a harness.

        Parameters
        ----------
        harness_name:
            Identifier for the harness (e.g. "sysbench", "tiobench").
            Used both as the underlying logger name and embedded in every
            structured payload.
        run_id:
            Free-form campaign/run identifier for traceability. Embedded
            in every structured payload. Defaults to "" if not supplied.
        log_level:
            One of "DEBUG", "INFO", "WARNING", "ERROR" (default "INFO").
            Unrecognized values fall back to "INFO".
        enable_file_logging:
            If True, also attach a file handler that writes JSONL-format
            structured logs to disk (default False; console-only via the
            standard logging framework otherwise).
        log_dir:
            Directory for the log file when `enable_file_logging=True`.
            Defaults to `results/{harness_name}/{timestamp}/` (relative to
            the current working directory) if not supplied.

        Returns
        -------
        BenchmarkLogger
        """
        level = _LEVEL_MAP.get(log_level.upper(), logging.INFO)

        logger = logging.getLogger(f"benchmark.{harness_name}")
        logger.setLevel(level)

        if enable_file_logging:
            if log_dir is None:
                timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                log_dir = str(Path("results") / harness_name / timestamp)

            log_path = Path(log_dir)
            log_path.mkdir(parents=True, exist_ok=True)

            file_handler = logging.FileHandler(
                log_path / "benchmark.log", encoding="utf-8"
            )
            file_handler.setLevel(level)
            # Bare message formatter: event()/info()/etc. already produce
            # a complete JSON string as the log message, so no additional
            # prefix/timestamp is added here (JSONL - one JSON object per
            # line, no wrapping).
            file_handler.setFormatter(logging.Formatter("%(message)s"))
            logger.addHandler(file_handler)

        return cls(logger, harness_name, run_id)

    # ----------------------------------------------------------------
    # Core structured event logging
    # ----------------------------------------------------------------

    def event(
        self,
        event_type: str,
        details: Optional[Dict[str, Any]] = None,
        level: str = "INFO",
    ) -> None:
        """
        Log a structured event with metadata.

        Parameters
        ----------
        event_type:
            Type of event (e.g. "BENCHMARK_START", "OUTLIER_SKIPPED"). Any
            string is accepted; see `Events` for common predefined values.
        details:
            Event-specific data (optional). Must be JSON-serializable.
        level:
            Log level for this event: "DEBUG", "INFO", "WARNING", or
            "ERROR" (default "INFO").
        """
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "harness": self._harness_name,
            "run_id": self._run_id,
            "details": details or {},
        }
        log_level = _LEVEL_MAP.get(level.upper(), logging.INFO)
        self._logger.log(log_level, json.dumps(payload))

    # ----------------------------------------------------------------
    # Convenience text-message methods
    # ----------------------------------------------------------------

    def debug(self, message: str, **kwargs: Any) -> None:
        """Log a simple text message at DEBUG level with optional context."""
        self._log_message("DEBUG", message, kwargs)

    def info(self, message: str, **kwargs: Any) -> None:
        """Log a simple text message at INFO level with optional context."""
        self._log_message("INFO", message, kwargs)

    def warning(self, message: str, **kwargs: Any) -> None:
        """Log a simple text message at WARNING level with optional context."""
        self._log_message("WARNING", message, kwargs)

    def error(self, message: str, **kwargs: Any) -> None:
        """Log a simple text message at ERROR level with optional context."""
        self._log_message("ERROR", message, kwargs)

    def _log_message(self, level: str, message: str, details: Dict[str, Any]) -> None:
        self.event(event_type=level, details={"message": message, **details}, level=level)


# --------------------------------------------------------------------------
# Self-test (manual sanity check; not a substitute for a real test suite)
# --------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(message)s")

    logger = BenchmarkLogger.create("sysbench", run_id="self_test", log_level="DEBUG")

    logger.event(Events.BENCHMARK_START, {"variant": "cpu_1t", "iterations": 3})
    logger.event(Events.OUTLIER_SKIPPED, {"metric": "cpu_events_per_sec", "reason": "zero_iqr"})
    logger.info("Device connected", port="COM7", baud=115200)
    logger.warning("Cache drop failed", device="target", error="permission_denied")
    logger.event(Events.BENCHMARK_END, {"status": "CLEAN"})
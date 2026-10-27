"""
boot_logger.py - File logging for the bootbench skill (capture.py and report.py).

bootbench prints its progress to stdout; once a run is over (or a background run's stdout is buffered) that is all
there is, and most failures are reduced to a one-line message. This module keeps a durable record next to it:

    boot-skills/skills/bootbench/logging/<YYYYmmdd_HHMMSS>/
        log-<YYYYmmdd_HHMMSS>.log   everything, all phases (also paramiko's own INFO+ records)
        setup.log                   connect, detect, device info, debug-cmdline provisioning
        boot.log                    the boot loop (default-N, then debug-N)
        collect.log                 pull logs, parse, analyze, record and render the report

The folder is deliberately not report/Boot-Logs/..., which holds the logs pulled from the device.

Nothing here changes what the scripts print: say() calls print() exactly as before and then writes the same text to
the log file. The logger has no console handler, and every record is flushed as it is written, so a monitor can
follow a long background run through the files.

Adapted from benchmark-skills/src/utils/logger.py (PhaseLogger). bootbench is deliberately standalone and imports
nothing from the other skills, so this is a copy, kept to the same conventions (INFO default, one switch for the
level, setup/benchmark/teardown-style phase files) with two additions the benchmark harness does not need yet:

* Secrets are masked in every record, including tracebacks (add_secret() / redact_argv()).
* A single record is capped (a failed parse puts the whole dmesg into an exception message).

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import logging
import platform
import shlex
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional, Union

#: bootbench/logging, next to capture/ and report/ (this file is bootbench/capture/scripts/boot_logger.py)
LOG_ROOT = Path(__file__).resolve().parents[2] / "logging"

#: The levels accepted by --log-level.
LEVELS = {"DEBUG": logging.DEBUG, "INFO": logging.INFO, "WARNING": logging.WARNING, "ERROR": logging.ERROR}

#: The phase files a run writes.
PHASES = ("setup", "boot", "collect")

#: Third-party loggers held at INFO or above even when the run is at DEBUG: paramiko logs every transport packet at
#: DEBUG and comtypes logs its COM plumbing, which would bury bootbench's own records.
_CAPPED_LOGGERS = ("paramiko", "comtypes")

#: What a masked secret is replaced with.
REDACTED = "********"

#: The longest message (and, separately, the longest traceback) written to a log, in characters. Longer text keeps
#: its head and its tail, which is where a traceback names the exception.
MAX_PART_CHARS = 8000

_secrets: set = set()


# ---------------------------------------------------------------------------
# Secrets
# ---------------------------------------------------------------------------

def add_secret(value: Optional[str]) -> None:
    """Mask `value` wherever it appears in any later log record. Empty and non-string values are ignored."""
    if isinstance(value, str) and value:
        _secrets.add(value)


def clear_secrets() -> None:
    _secrets.clear()


def redact(text: str) -> str:
    """`text` with every registered secret replaced by REDACTED (longest first, so one secret containing another
    is masked as a whole)."""
    for secret in sorted(_secrets, key=len, reverse=True):
        if secret in text:
            text = text.replace(secret, REDACTED)
    return text


def redact_argv(argv: Iterable[str]) -> List[str]:
    """argv with the value of --password masked, in the `--password X` and `--password=X` forms and for any
    abbreviation argparse accepts (`--pass X`, `--p X`). Independent of add_secret(), so the command line is safe
    to log even before the password is known to the logger."""
    out: List[str] = []
    mask_next = False
    for arg in argv:
        if mask_next:
            out.append(REDACTED)
            mask_next = False
            continue
        name, equals, _value = arg.partition("=")
        if len(name) > 2 and name.startswith("--") and "--password".startswith(name):
            if equals:
                out.append(f"{name}={REDACTED}")
            else:
                out.append(arg)
                mask_next = True
            continue
        out.append(arg)
    return out


def clip(text: object, limit: int = 200) -> str:
    """One-line, length-bounded form of a command or error text for a log message."""
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else f"{flat[:limit]}... [{len(flat)} chars]"


def _clip_middle(text: str, limit: int = MAX_PART_CHARS) -> str:
    if len(text) <= limit:
        return text
    head = limit * 3 // 4
    tail = limit - head
    return f"{text[:head]}\n... [{len(text) - limit} characters omitted] ...\n{text[-tail:]}"


class _Formatter(logging.Formatter):
    """The log line format, with secrets masked and over-long text cut. Secrets are masked before the cut so a
    secret that straddles the cut cannot leave a readable fragment."""

    def formatException(self, ei):
        return _clip_middle(redact(super().formatException(ei)))

    def format(self, record: logging.LogRecord) -> str:
        record = copy.copy(record)          # other handlers (and pytest's caplog) keep the untouched record
        record.msg = _clip_middle(redact(record.getMessage()))
        record.args = None
        record.exc_text = None              # always format the traceback here, so it is masked and capped
        return redact(super().format(record))


# ---------------------------------------------------------------------------
# Level
# ---------------------------------------------------------------------------

def parse_level(level: Union[str, int]) -> int:
    """The numeric level for 'debug'/'INFO'/... or one of the four numeric levels. Raises ValueError otherwise, so a
    typo is never silently turned into a different level."""
    if isinstance(level, str):
        key = level.strip().upper()
        if key in LEVELS:
            return LEVELS[key]
    elif isinstance(level, int) and not isinstance(level, bool) and level in LEVELS.values():
        return level
    raise ValueError(f"Unknown log level {level!r}; expected one of {', '.join(LEVELS)}")


def add_log_level_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--log-level", type=str.upper, choices=list(LEVELS), default="INFO",
        help="Verbosity of the log files written under bootbench/logging/ (default: INFO). DEBUG adds every command "
             "sent to the device and every retry/poll; it does not change what is printed.")


# ---------------------------------------------------------------------------
# The logger
# ---------------------------------------------------------------------------

class BootLogger:
    """File-only logger that routes records to the central log and to the log of the active phase."""

    def __init__(self, name: str = "bootbench"):
        self.logger = logging.getLogger(name)
        self._level = logging.INFO
        self.logger.setLevel(self._level)
        # Records stay here. Without this a root logger that someone configured would print every record a second
        # time; paramiko and other libraries still reach the central file through the handler on the root logger.
        self.logger.propagate = False
        self.logger.handlers.clear()
        # A logger with no handler at all would hand WARNING+ records to logging.lastResort, i.e. to stderr.
        self.logger.addHandler(logging.NullHandler())

        self.formatter = _Formatter(fmt="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
        self.run_dir: Optional[Path] = None
        self.current_phase: Optional[str] = None
        self.centralized_handler: Optional[logging.FileHandler] = None
        self.current_phase_handler: Optional[logging.FileHandler] = None

    # -- level ---------------------------------------------------------------

    @property
    def level(self) -> int:
        """The numeric level in force (logging.INFO until set_level() is called)."""
        return self._level

    def set_level(self, level: Union[str, int]) -> None:
        """Set the verbosity of everything this logger writes: the central log, the current and every later phase
        log, and the root logger (which governs the libraries that log through it). Raises ValueError, changing
        nothing, for an unknown level."""
        value = parse_level(level)
        self._level = value
        self.logger.setLevel(value)
        for handler in (self.centralized_handler, self.current_phase_handler):
            if handler is not None:
                handler.setLevel(value)
        logging.getLogger().setLevel(value)
        for name in _CAPPED_LOGGERS:
            logging.getLogger(name).setLevel(max(value, logging.INFO))

    # -- files ---------------------------------------------------------------

    def add_centralized_handler(self, log_dir: Path, timestamp: str) -> None:
        """Write every record, whatever the phase, to <log_dir>/log-<timestamp>.log. The handler is also attached
        to the root logger so records from libraries (paramiko) land in the same file."""
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(log_dir / f"log-{timestamp}.log", mode="a", encoding="utf-8")
        handler.setLevel(self._level)
        handler.setFormatter(self.formatter)

        self._detach_centralized()
        self.logger.addHandler(handler)
        root = logging.getLogger()
        root.addHandler(handler)
        if root.level > self._level:           # a library record only reaches the handler if the root lets it by
            root.setLevel(self._level)
        self.centralized_handler = handler

    def configure_run_dir(self, run_dir: Path) -> None:
        """Set the folder that receives the per-phase logs."""
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)

    def set_phase(self, name: str) -> None:
        """Switch to phase `name` (one of PHASES): close the previous phase log and open <run_dir>/<name>.log in
        append mode, so coming back to a phase continues its file. A no-op if `name` is already current. Without a
        run directory only the phase name is tracked."""
        if name not in PHASES:
            raise ValueError(f"Unknown phase {name!r}; expected one of {', '.join(PHASES)}")
        if name == self.current_phase:
            return
        self.end_phase()
        self.current_phase = name
        if self.run_dir is None:
            return
        handler = logging.FileHandler(self.run_dir / f"{name}.log", mode="a", encoding="utf-8")
        handler.setLevel(self._level)
        handler.setFormatter(self.formatter)
        self.logger.addHandler(handler)
        self.current_phase_handler = handler
        self.logger.info("=== Started phase: %s ===", name)

    def end_phase(self) -> None:
        """Close the current phase log (if any)."""
        if self.current_phase_handler is not None:
            self.logger.info("=== Ended phase: %s ===", self.current_phase)
            self.current_phase_handler.close()
            self.logger.removeHandler(self.current_phase_handler)
            self.current_phase_handler = None
        self.current_phase = None

    @contextlib.contextmanager
    def phase(self, name: str):
        """Run a block in phase `name`, then go back to the phase that was active before it."""
        previous = self.current_phase
        self.set_phase(name)
        try:
            yield
        finally:
            if previous is not None:
                self.set_phase(previous)
            else:
                self.end_phase()

    def _detach_centralized(self) -> None:
        if self.centralized_handler is not None:
            self.logger.removeHandler(self.centralized_handler)
            logging.getLogger().removeHandler(self.centralized_handler)
            self.centralized_handler.close()
            self.centralized_handler = None

    def close(self) -> None:
        """Close every file and forget the run directory. Safe to call twice; the logger can be started again."""
        self.end_phase()
        self._detach_centralized()
        self.run_dir = None

    # -- records -------------------------------------------------------------

    def log(self, level: int, msg: str, *args, **kwargs) -> None:
        self.logger.log(level, msg, *args, **kwargs)

    def debug(self, msg: str, *args, **kwargs) -> None:
        self.logger.debug(msg, *args, **kwargs)

    def info(self, msg: str, *args, **kwargs) -> None:
        self.logger.info(msg, *args, **kwargs)

    def warning(self, msg: str, *args, **kwargs) -> None:
        self.logger.warning(msg, *args, **kwargs)

    def error(self, msg: str, *args, **kwargs) -> None:
        self.logger.error(msg, *args, **kwargs)

    def exception(self, msg: str, *args, **kwargs) -> None:
        self.logger.error(msg, *args, exc_info=True, **kwargs)


#: The logger shared by capture.py and report.py (they import this module under the same name).
boot_log = BootLogger()


def say(message: str, level: int = logging.INFO, **kwargs) -> None:
    """print(message) exactly as before, then record the same text in the log. Surrounding blank lines used for
    spacing on screen are not written to the log. `kwargs` (e.g. exc_info=True) go to the log record."""
    print(message)
    text = str(message).strip("\n")
    if text:
        boot_log.log(level, text, **kwargs)


# ---------------------------------------------------------------------------
# One run
# ---------------------------------------------------------------------------

def init_run(level: Union[str, int] = "INFO", argv: Optional[Iterable[str]] = None, secrets: Iterable[Optional[str]] = (),
             log_root: Optional[Path] = None) -> Optional[Path]:
    """Start file logging for this process in a new <log_root>/<timestamp>/ folder and return that folder.

    Logging must never cost a capture that takes the better part of an hour: if the folder cannot be created a
    warning goes to stderr and None is returned, and the run carries on without a log. An invalid `level` raises
    ValueError.
    """
    boot_log.close()
    boot_log.set_level(level)
    for secret in secrets:
        add_secret(secret)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = Path(log_root if log_root is not None else LOG_ROOT) / stamp
    try:
        boot_log.add_centralized_handler(run_dir, stamp)
        boot_log.configure_run_dir(run_dir)
    except OSError as exc:
        boot_log.close()
        print(f"WARNING: bootbench file logging is disabled, could not create {run_dir}: {exc}", file=sys.stderr)
        return None

    boot_log.info("bootbench started; log level %s; python %s on %s", logging.getLevelName(boot_log.level),
                  platform.python_version(), platform.platform())
    if argv is not None:
        boot_log.info("Command line: %s", " ".join(shlex.quote(a) for a in redact_argv(argv)))
    boot_log.info("Log folder: %s", run_dir)
    return run_dir


@contextlib.contextmanager
def logged_run(level: Union[str, int] = "INFO", argv: Optional[Iterable[str]] = None,
               secrets: Iterable[Optional[str]] = (), log_root: Optional[Path] = None):
    """Wrap a command line entry point: start the log, and record how the run ended. Exceptions, SystemExit and
    KeyboardInterrupt are logged and then re-raised unchanged, so exit codes and what reaches stderr are the same
    as without logging."""
    init_run(level, argv, secrets, log_root)
    try:
        yield boot_log
    except SystemExit as exc:
        code = exc.code
        if code in (None, 0):
            boot_log.info("Exiting with status 0")
        else:
            boot_log.error("Exiting with status %s", code)
        raise
    except KeyboardInterrupt:
        boot_log.warning("Interrupted by the user (KeyboardInterrupt)")
        raise
    except BaseException:
        boot_log.exception("Unhandled exception")
        raise
    else:
        boot_log.info("Finished")
    finally:
        boot_log.close()

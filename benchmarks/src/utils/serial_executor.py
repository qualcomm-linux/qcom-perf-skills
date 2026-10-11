"""
serial_executor.py - Serial-based remote command execution for benchmark
target devices.

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>

Rationale
---------
The benchmark harnesses in this project connect to the target device over
a USB-to-serial adapter. All actual benchmark execution (sysbench, tiotest, etc.)
runs over this SAME serial connection so results reflect the device's real,
unrestricted execution context.

ADB remains responsible for everything that is NOT benchmark execution.
"""

import re
import time
import uuid
from typing import Optional

from src.utils.logger import phase_logger

# --------------------------------------------------------------------------
# Exceptions
# --------------------------------------------------------------------------

class SerialCommandError(Exception):
    """
    Raised when a command could not be confirmed complete over the serial
    connection within the requested timeout, or when the underlying serial
    write/read itself fails.
    """


# --------------------------------------------------------------------------
# Common pre-benchmark validation helpers
# --------------------------------------------------------------------------

def print_nproc(serial_executor: "SerialCommandExecutor") -> str:
    """
    Execute `nproc` over the already-open serial connection and print the
    result.
    """
    phase_logger.info("\n--- System Validation: nproc (over serial) ---")
    try:
        output = serial_executor.execute_command("nproc", timeout_override=10.0)
    except SerialCommandError as exc:
        phase_logger.warning(f"nproc validation failed: {exc}")
        return ""

    result = output.strip()
    phase_logger.info(f"nproc = {result}")
    return result


# --------------------------------------------------------------------------
# SerialCommandExecutor
# --------------------------------------------------------------------------

class SerialCommandExecutor:
    """
    Executes shell commands on the device over an already-open serial
    connection, detecting command completion via a unique sentinel marker.
    """

    def __init__(
        self,
        conn,
        default_timeout: float = 15.0,
        poll_interval: float = 0.05,
    ):
        self.conn = conn
        self.default_timeout = default_timeout
        self.poll_interval = poll_interval

    # ---- Public API ----------------------------------------------------

    def execute_command(
        self,
        cmd: str,
        timeout_override: Optional[float] = None,
        prefer_stderr: bool = False,
    ) -> str:
        """
        Execute `cmd` on the device over serial and return its captured output.

        Note: `prefer_stderr` is accepted for interface parity with
        SshManager.execute_command(), but is a no-op here. A serial
        connection is a single character stream - stdout and stderr from
        the remote shell are interleaved into the same stream and cannot be
        distinguished, so there is nothing to "prefer" between them.
        """
        if timeout_override == 0 or timeout_override == float("inf"):
            final_timeout = None
        else:
            final_timeout = (
                timeout_override if timeout_override is not None else self.default_timeout
            )

        marker = f"__SERIALDONE_{uuid.uuid4().hex}__"
        full_cmd = f"{cmd}; echo {marker}$?"
        marker_pattern = re.compile(re.escape(marker) + r"(\d+)")

        try:
            self.conn.reset_input_buffer()
        except Exception:
            pass

        try:
            self.conn.write((full_cmd + "\n").encode("utf-8"))
        except Exception as exc:
            raise SerialCommandError(f"Failed to write command over serial: '{cmd}': {exc}") from exc

        buffer = ""
        start_time = time.monotonic()

        while True:
            try:
                chunk = self.conn.read(self.conn.in_waiting or 256)
            except Exception as exc:
                raise SerialCommandError(f"Failed to read serial response for command '{cmd}': {exc}") from exc

            if chunk:
                buffer += chunk.decode("utf-8", errors="ignore")
                match = marker_pattern.search(buffer)
                if match:
                    exit_code = int(match.group(1))
                    output = self._clean_output(buffer[:match.start()], full_cmd)
                    if exit_code != 0:
                        phase_logger.warning(f"serial command exited with code {exit_code}: {cmd}")
                    return output
            else:
                time.sleep(self.poll_interval)

            if final_timeout is not None and (time.monotonic() - start_time) > final_timeout:
                raise SerialCommandError(
                    f"Command timed out after {final_timeout}s waiting for completion "
                    f"marker over serial: '{cmd}'"
                )

    # ---- Internal helpers ------------------------------------------------

    @staticmethod
    def _clean_output(raw: str, sent_cmd: str) -> str:
        lines = raw.splitlines()
        cleaned = [line for line in lines if sent_cmd.strip() not in line.strip()]
        return "\n".join(cleaned).strip()
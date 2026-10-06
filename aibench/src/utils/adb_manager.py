"""
adb_manager.py - Robust, cross-platform Android Debug Bridge (ADB) connection
manager.

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>

Provides the AdbManager class, which wraps the `adb devices` workflow with:
  - Cross-platform executable resolution (adb.exe on Windows, adb elsewhere).
  - Structured parsing of device state (device / offline / unauthorized).
  - Graceful, retried recovery when a device is reported "offline"
    (kill-server / start-server / re-check), with full logging of each
    attempt.
  - Custom exceptions for precise error handling by calling code.
"""

import logging
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


# --------------------------------------------------------------------------
# Exceptions
# --------------------------------------------------------------------------

class AdbError(Exception):
    """Base exception for all ADB-related failures raised by AdbManager."""


class AdbDeviceOfflineError(AdbError):
    """
    Raised when one or more devices remain in the "offline" state after the
    configured number of recovery attempts have been exhausted.
    """

    def __init__(self, device_ids: List[str], attempts: int, steps: List[str]):
        self.device_ids = device_ids
        self.attempts = attempts
        self.steps = steps
        devices_str = ", ".join(device_ids)
        steps_str = "; ".join(steps)
        message = (
            f"Device(s) still OFFLINE after {attempts} recovery attempt(s): "
            f"{devices_str}. Steps attempted: {steps_str}"
        )
        super().__init__(message)


# --------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------

@dataclass
class AdbDevice:
    """A single entry from `adb devices`, e.g. ('ABC123', 'device')."""
    device_id: str
    state: str  # 'device', 'offline', 'unauthorized', or any other adb state


# --------------------------------------------------------------------------
# AdbManager
# --------------------------------------------------------------------------

class AdbManager:
    """
    Manages ADB server interactions and device status checks, with built-in
    graceful recovery for devices stuck in the "offline" state.

    Parameters
    ----------
    max_recovery_attempts:
        Maximum number of kill-server/start-server recovery cycles to
        attempt before giving up and raising AdbDeviceOfflineError.
    recovery_wait_seconds:
        Seconds to wait after `adb start-server` before re-checking device
        status, giving the daemon time to re-establish device connections.
    command_timeout:
        Timeout (seconds) applied to every individual `adb` subprocess call.
    """

    # States considered "ready to use" - i.e. not requiring any recovery.
    HEALTHY_STATES = {"device"}

    # Command used to fetch OS release metadata from the device.
    OS_RELEASE_CMD = 'cat /etc/os-release'

    # Matches simple KEY=VALUE lines in /etc/os-release, tolerating values
    # that are either double-quoted (e.g. PRETTY_NAME="Foo Bar 1.0") or bare
    # (e.g. BUILD_ID=12345).
    OS_RELEASE_LINE_PATTERN = re.compile(r'^([A-Za-z_][A-Za-z0-9_]*)=(.*)$')

    def __init__(
        self,
        max_recovery_attempts: int = 3,
        recovery_wait_seconds: float = 5.0,
        command_timeout: float = 15.0,
    ):
        self.max_recovery_attempts = max_recovery_attempts
        self.recovery_wait_seconds = recovery_wait_seconds
        self.command_timeout = command_timeout
        self.adb_executable = self._resolve_adb_executable()
        self._os_release_cache: Optional[Dict[str, str]] = None
        self._ip_address_cache: Optional[str] = None

    # ---- Public API ----------------------------------------------------

    def execute_shell_command(self, cmd: str, timeout_override: float = None) -> str:
        """
        Execute an ADB shell command and return the output.
        Optional timeout_override allows specific commands to override the default timeout.
        """
        return self._run_adb_command(["shell", cmd], timeout=timeout_override)

    def push_file(self, local_path: str, remote_path: str) -> str:
        """
        Push a file from the host to the device.
        """
        return self._run_adb_command(["push", local_path, remote_path])

    def pull_file(self, remote_path: str, local_path: str) -> str:
        """
        Pull a file from the device to the host.
        """
        return self._run_adb_command(["pull", remote_path, local_path])

    def get_os_release_info(self, refresh: bool = False) -> Dict[str, str]:
        """
        Fetch and parse `/etc/os-release` from the connected device via
        `adb shell cat /etc/os-release`, returning a dict with 'name',
        'pretty_name' and 'build_id' keys.
        """
        if self._os_release_cache is not None and not refresh:
            return self._os_release_cache

        logger.info("Fetching OS release information from device...")
        raw_output = self.execute_shell_command(self.OS_RELEASE_CMD)
        parsed = self._parse_os_release(raw_output)

        info = {
            'name': parsed.get('NAME', 'Unknown'),
            'pretty_name': parsed.get('PRETTY_NAME', 'Unknown'),
            'build_id': parsed.get('BUILD_ID', 'Unknown'),
        }
        self._os_release_cache = info
        return info

    def get_pretty_name(self) -> str:
        """Convenience accessor returning just the device's PRETTY_NAME."""
        return self.get_os_release_info().get('pretty_name', 'Unknown')

    def get_build_id(self) -> str:
        """Convenience accessor returning just the device's BUILD_ID via /etc/os-release."""
        return self.get_os_release_info().get('build_id', 'Unknown')

    @staticmethod
    def _parse_os_release(raw_output: str) -> Dict[str, str]:
        """
        Parse the raw text output of `cat /etc/os-release` into a dict of
        KEY -> VALUE pairs, stripping surrounding quotes from quoted values.
        """
        fields: Dict[str, str] = {}
        for line in raw_output.splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            match = AdbManager.OS_RELEASE_LINE_PATTERN.match(line)
            if not match:
                continue
            key, value = match.group(1), match.group(2).strip()
            if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
                value = value[1:-1]
            fields[key] = value
        return fields

    def check_device_status(self) -> List[AdbDevice]:
        """
        Query `adb devices` and ensure every connected device is in a
        healthy ("device") state, transparently attempting recovery for
        any device reported as "offline".
        """
        devices = self._get_devices()

        if not devices:
            logger.warning("No ADB devices detected (device list is empty).")
            return []

        offline_devices = [d for d in devices if d.state == "offline"]
        if not offline_devices:
            healthy = [d for d in devices if d.state in self.HEALTHY_STATES]
            logger.info(
                "All %d device(s) reported healthy state(s): %s",
                len(devices),
                ", ".join(f"{d.device_id}={d.state}" for d in devices),
            )
            return healthy

        offline_ids = [d.device_id for d in offline_devices]
        logger.warning(
            "Detected offline device(s): %s. Attempting graceful recovery.",
            ", ".join(offline_ids),
        )

        recovered, steps_attempted, attempts_made = self._recover_offline_devices(
            offline_ids
        )

        if not recovered:
            raise AdbDeviceOfflineError(
                device_ids=offline_ids,
                attempts=attempts_made,
                steps=steps_attempted,
            )

        final_devices = self._get_devices()
        return [d for d in final_devices if d.state in self.HEALTHY_STATES]

    # ---- Internal helpers ------------------------------------------------

    @staticmethod
    def _resolve_adb_executable() -> str:
        exe_name = "adb.exe" if sys.platform.startswith("win") else "adb"
        resolved = shutil.which(exe_name)
        if resolved is None:
            raise FileNotFoundError(
                f"'{exe_name}' was not found in the system PATH. "
                "Install Android SDK Platform Tools and ensure 'adb' is "
                "accessible from this shell, then try again."
            )
        return resolved

    def _run_adb_command(self, args: List[str], timeout: float = None) -> str:
        if timeout == 0 or timeout == float("inf"):
            final_timeout = None
        else:
            final_timeout = timeout if timeout is not None else self.command_timeout

        full_cmd = [self.adb_executable] + args
        logger.debug("Executing: %s", " ".join(full_cmd))

        try:
            process = subprocess.Popen(
                full_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise FileNotFoundError(
                f"'{self.adb_executable}' could not be executed. "
                "Ensure Android SDK Platform Tools are installed correctly."
            ) from exc

        start_time = time.monotonic()
        last_log_time = start_time

        while True:
            ret = process.poll()
            if ret is not None:
                break

            elapsed = time.monotonic() - start_time
            if final_timeout is not None and elapsed > final_timeout:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                raise AdbError(
                    f"'adb {' '.join(args)}' timed out after {final_timeout}s."
                )

            if time.monotonic() - last_log_time >= 5.0:
                logger.info(
                    "Command still running: adb %s (elapsed: %.1fs)",
                    " ".join(args), elapsed,
                )
                last_log_time = time.monotonic()

            time.sleep(0.5)

        stdout_bytes, stderr_bytes = process.communicate()
        stdout = stdout_bytes.decode("utf-8", errors="ignore")
        stderr = stderr_bytes.decode("utf-8", errors="ignore")

        if process.returncode != 0:
            logger.warning(
                "'adb %s' exited with code %d. stderr: %s",
                " ".join(args), process.returncode, stderr.strip()
            )

        return stdout

    def _get_devices(self) -> List[AdbDevice]:
        output = self._run_adb_command(["devices"])
        device_line_pattern = re.compile(r'^(\S+)\s+(\w+)\s*$', re.MULTILINE)

        devices: List[AdbDevice] = []
        for line in output.splitlines():
            line = line.strip()
            if not line or line.lower().startswith("list of devices"):
                continue
            match = device_line_pattern.match(line)
            if not match:
                continue
            device_id, state = match.group(1), match.group(2)
            devices.append(AdbDevice(device_id=device_id, state=state))

        return devices

    def _recover_offline_devices(
        self, offline_ids: List[str]
    ) -> Tuple[bool, List[str], int]:
        steps_attempted: List[str] = []

        for attempt in range(1, self.max_recovery_attempts + 1):
            logger.info(
                "Recovery attempt %d/%d for offline device(s): %s",
                attempt, self.max_recovery_attempts, ", ".join(offline_ids)
            )

            self._run_adb_command(["kill-server"])
            steps_attempted.append(f"attempt {attempt}: kill-server")

            self._run_adb_command(["start-server"])
            steps_attempted.append(f"attempt {attempt}: start-server")

            logger.info(
                "Waiting %.1fs for ADB daemon to re-establish device connections...",
                self.recovery_wait_seconds
            )
            time.sleep(self.recovery_wait_seconds)
            steps_attempted.append(
                f"attempt {attempt}: waited {self.recovery_wait_seconds}s"
            )

            current_devices = self._get_devices()
            current_states = {d.device_id: d.state for d in current_devices}

            still_offline = [
                dev_id for dev_id in offline_ids
                if current_states.get(dev_id) != "device"
            ]

            if not still_offline:
                logger.info(
                    "Recovery successful on attempt %d: all previously offline device(s) are now online.",
                    attempt
                )
                steps_attempted.append(f"attempt {attempt}: recovery succeeded")
                return True, steps_attempted, attempt

            logger.warning(
                "Attempt %d/%d: device(s) still offline after recovery cycle: %s",
                attempt, self.max_recovery_attempts, ", ".join(still_offline)
            )
            steps_attempted.append(
                f"attempt {attempt}: still offline -> {', '.join(still_offline)}"
            )

        logger.error(
            "Exhausted %d recovery attempt(s); device(s) remain offline: %s",
            self.max_recovery_attempts, ", ".join(offline_ids)
        )
        return False, steps_attempted, self.max_recovery_attempts


def check_adb_device_status(
    max_recovery_attempts: int = 3,
    recovery_wait_seconds: float = 5.0,
) -> List[AdbDevice]:
    manager = AdbManager(
        max_recovery_attempts=max_recovery_attempts,
        recovery_wait_seconds=recovery_wait_seconds,
    )
    return manager.check_device_status()
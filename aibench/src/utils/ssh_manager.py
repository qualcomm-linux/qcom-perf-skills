"""
ssh_manager.py - Paramiko-based SSH Manager mimicking both AdbManager and SerialCommandExecutor

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import logging
import os
import re
import socket
from typing import Dict, List, Optional
import paramiko

from src.utils.serial_executor import SerialCommandError
from src.utils.adb_manager import AdbDevice
from src.utils.credential_manager import get_ssh_credentials

logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

class SshManager:
    """
    Provides a dual-interface matching both AdbManager (for setup/teardown/files)
    and SerialCommandExecutor (for executing benchmark runs) but everything
    operates over a single SSH connection.
    """

    OS_RELEASE_LINE_PATTERN = re.compile(r'^([A-Za-z_][A-Za-z0-9_]*)=(.*)$')

    def __init__(self, host: str = None, username: str = None, password: str = None, port: int = None, timeout: float = 15.0):
        """
        Initialize SSH Manager.
        
        Args:
            host: Target device IP address (if None, loads from credentials.yaml)
            username: SSH username (if None, loads from credentials.yaml)
            password: SSH password (if None, loads from credentials.yaml)
            port: SSH port (if None, loads from credentials.yaml, defaults to 22)
            timeout: Connection timeout in seconds
            
        Raises:
            ValueError: If required credentials are missing
        """
        # Load credentials from credential manager if not provided
        if any(x is None for x in [host, username, password, port]):
            creds = get_ssh_credentials()
            if host is None:
                host = creds.get("host")
            if username is None:
                username = creds.get("username")
            if password is None:
                password = creds.get("password")
            if port is None:
                port = creds.get("port", 22)
        
        # Validate required credentials
        if not host:
            raise ValueError(
                "SSH host is required. Please provide via --host argument or "
                "create config/credentials.yaml from credentials.yaml.example"
            )
        if not username:
            raise ValueError(
                "SSH username is required. Please create config/credentials.yaml "
                "from credentials.yaml.example"
            )
        if not password:
            raise ValueError(
                "SSH password is required. Please create config/credentials.yaml "
                "from credentials.yaml.example"
            )
        
        self.host = host
        self.username = username
        self.password = password
        self.port = port or 22
        self.timeout = timeout
        self.client: Optional[paramiko.SSHClient] = None
        self.sftp: Optional[paramiko.SFTPClient] = None
        self._os_release_cache: Optional[Dict[str, str]] = None

    def connect(self) -> None:
        logger.info(f"Connecting to {self.host} via SSH...")
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            self.client.connect(
                hostname=self.host,
                port=self.port,
                username=self.username,
                password=self.password,
                timeout=self.timeout
            )
            self.sftp = self.client.open_sftp()
            logger.info("SSH and SFTP connections established successfully.")
        except Exception as exc:
            raise SerialCommandError(f"Failed to establish SSH connection to {self.host}: {exc}") from exc

    def close(self) -> None:
        if self.sftp:
            try:
                self.sftp.close()
            except Exception:
                pass
        if self.client:
            try:
                self.client.close()
            except Exception:
                pass
        logger.info("SSH connection closed.")

    # ---- SerialCommandExecutor Interface ----

    def execute_command(
        self,
        cmd: str,
        timeout_override: Optional[float] = None,
        prefer_stderr: bool = False,
    ) -> str:
        """
        Executes a shell command. Mimics SerialCommandExecutor's interface.
        """
        return self.execute_shell_command(cmd, timeout_override, prefer_stderr=prefer_stderr)

    # ---- AdbManager Interface ----

    def execute_shell_command(
        self,
        cmd: str,
        timeout_override: Optional[float] = None,
        prefer_stderr: bool = False,
    ) -> str:
        """
        Args:
            cmd: Shell command to execute on the target over SSH.
            timeout_override: See existing semantics (0/inf == no timeout).
            prefer_stderr: When True, stderr is treated as the PRIMARY output
                stream instead of stdout - i.e. if stderr has any content it
                is returned, and stdout is only used as a fallback if stderr
                is empty. This is opt-in and defaults to False, so behavior
                for every existing caller is completely unchanged. It exists
                because some on-target binaries (observed with lat_mem_rd)
                write their real output to stderr instead of stdout.
        """
        if self.client is None:
            self.connect()

        if timeout_override == 0 or timeout_override == float("inf"):
            final_timeout = None
        else:
            final_timeout = timeout_override if timeout_override is not None else self.timeout

        logger.debug(f"SSH Executing: {cmd}")
        try:
            stdin, stdout, stderr = self.client.exec_command(cmd, timeout=final_timeout)
            
            # Read output and error
            out_bytes = stdout.read()
            err_bytes = stderr.read()
            
            out_str = out_bytes.decode('utf-8', errors='ignore')
            err_str = err_bytes.decode('utf-8', errors='ignore')
            
            # Warn if command failed
            exit_status = stdout.channel.recv_exit_status()
            if exit_status != 0:
                logger.warning(f"SSH Command '{cmd}' exited with code {exit_status}. stderr: {err_str.strip()}")

            if prefer_stderr:
                # Explicit opt-in: caller knows this command's real output
                # goes to stderr. Return stderr if it has any content;
                # otherwise fall back to stdout so nothing is lost.
                if err_str.strip():
                    return err_str
                return out_str

            # Default path (unchanged behavior for every other caller):
            # return stdout. As a safety net, if stdout came back completely
            # empty AND stderr has content, fall back to stderr rather than
            # discarding real output - this does not affect any benchmark
            # that correctly produces stdout.
            if not out_str.strip() and err_str.strip():
                logger.info(
                    f"SSH Command '{cmd}' returned empty stdout but stderr has "
                    f"{len(err_str)} bytes of content. Falling back to stderr."
                )
                return err_str

            return out_str
        except (socket.timeout, paramiko.SSHException) as exc:
            raise SerialCommandError(f"SSH command execution failed or timed out: {exc}") from exc

    def push_file(self, local_path: str, remote_path: str) -> str:
        """
        Push a file from the host to the device via SFTP.
        """
        if self.client is None or self.sftp is None:
            self.connect()
        logger.info(f"SCP/SFTP pushing {local_path} -> {remote_path}")
        
        # Ensure remote directory exists
        remote_dir = os.path.dirname(remote_path)
        if remote_dir:
            self.execute_shell_command(f"mkdir -p {remote_dir}")
            
        try:
            self.sftp.put(local_path, remote_path)
        except Exception as exc:
            raise SerialCommandError(f"Failed to push file via SFTP: {exc}") from exc
        return ""

    def pull_file(self, remote_path: str, local_path: str) -> str:
        """
        Pull a file from the device to the host via SFTP.
        """
        if self.client is None or self.sftp is None:
            self.connect()
        logger.info(f"SCP/SFTP pulling {remote_path} -> {local_path}")
        
        # Ensure local directory exists
        local_dir = os.path.dirname(local_path)
        if local_dir:
            os.makedirs(local_dir, exist_ok=True)
            
        try:
            self.sftp.get(remote_path, local_path)
        except Exception as exc:
            raise SerialCommandError(f"Failed to pull file via SFTP: {exc}") from exc
        return ""

    def get_os_release_info(self, refresh: bool = False) -> Dict[str, str]:
        if self._os_release_cache is not None and not refresh:
            return self._os_release_cache

        logger.info("Fetching OS release information via SSH...")
        raw_output = self.execute_shell_command("cat /etc/os-release")
        parsed = self._parse_os_release(raw_output)

        info = {
            'name': parsed.get('NAME', 'Unknown'),
            'pretty_name': parsed.get('PRETTY_NAME', 'Unknown'),
            'build_id': parsed.get('BUILD_ID', 'Unknown'),
        }
        self._os_release_cache = info
        return info

    def get_pretty_name(self) -> str:
        return self.get_os_release_info().get('pretty_name', 'Unknown')

    def get_build_id(self) -> str:
        return self.get_os_release_info().get('build_id', 'Unknown')

    @staticmethod
    def _parse_os_release(raw_output: str) -> Dict[str, str]:
        fields: Dict[str, str] = {}
        for line in raw_output.splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            match = SshManager.OS_RELEASE_LINE_PATTERN.match(line)
            if not match:
                continue
            key, value = match.group(1), match.group(2).strip()
            if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
                value = value[1:-1]
            fields[key] = value
        return fields

    def check_device_status(self) -> List[AdbDevice]:
        """
        Mimics AdbManager.check_device_status() by attempting an SSH connection
        and verifying liveness. Returns a mock AdbDevice to signal success.
        """
        if self.client is None:
            self.connect()
            
        try:
            out = self.execute_shell_command("echo 1").strip()
            if out == "1":
                # Return dummy device to signify healthy status
                return [AdbDevice(device_id=self.host, state="device")]
            else:
                raise SerialCommandError("SSH device did not return expected check signal.")
        except Exception as exc:
            raise SerialCommandError(f"SSH device check failed: {exc}") from exc
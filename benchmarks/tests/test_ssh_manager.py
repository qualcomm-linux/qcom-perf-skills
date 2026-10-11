"""
test_ssh_manager.py - Unit tests for SshManager.execute_shell_command(),
specifically the stdout/stderr fallback logic added to fix the lat_mem_rd
empty-output bug (some on-target binaries write their primary output to
stderr instead of stdout).

These tests use mocked Paramiko stdout/stderr channel file objects so no
real SSH connection is required.

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils.ssh_manager import SshManager


def make_channel_file(content: bytes, exit_status: int = 0):
    """
    Returns a MagicMock standing in for a Paramiko ChannelFile (as returned
    by stdout/stderr from exec_command()). Supports .read() and
    .channel.recv_exit_status().
    """
    mock_file = MagicMock()
    mock_file.read.return_value = content
    mock_file.channel.recv_exit_status.return_value = exit_status
    return mock_file


class TestSshManagerStdoutStderrFallback(unittest.TestCase):
    def setUp(self):
        self.manager = SshManager()
        # Bypass real connect(): provide a fake already-connected client.
        self.manager.client = MagicMock()

    def _mock_exec_command(self, stdout_bytes: bytes, stderr_bytes: bytes, exit_status: int = 0):
        stdin_mock = MagicMock()
        stdout_mock = make_channel_file(stdout_bytes, exit_status)
        stderr_mock = make_channel_file(stderr_bytes, exit_status)
        self.manager.client.exec_command.return_value = (stdin_mock, stdout_mock, stderr_mock)

    def test_normal_case_returns_stdout_when_present(self):
        """Existing/default behavior: if stdout has content, return it
        exactly as before - regardless of whether stderr also has content.
        This must remain unchanged for every other benchmark."""
        self._mock_exec_command(
            stdout_bytes=b"normal output line 1\nline 2\n",
            stderr_bytes=b"some warning on stderr\n",
        )
        result = self.manager.execute_shell_command("some_command")
        self.assertEqual(result, "normal output line 1\nline 2\n")

    def test_fallback_to_stderr_when_stdout_empty(self):
        """New behavior: if stdout is completely empty but stderr has
        content, fall back to returning stderr content (fixes lat_mem_rd
        writing its data output to stderr)."""
        self._mock_exec_command(
            stdout_bytes=b"",
            stderr_bytes=b"stride=64\n0.00049 1.697\n64.00000 139.351\n",
        )
        result = self.manager.execute_shell_command("lat_mem_rd -t -N 7 64M 64")
        self.assertEqual(result, "stride=64\n0.00049 1.697\n64.00000 139.351\n")

    def test_both_empty_returns_empty_stdout(self):
        """If both stdout and stderr are empty, return empty string
        (unchanged from prior behavior) - no crash, no fallback needed."""
        self._mock_exec_command(stdout_bytes=b"", stderr_bytes=b"")
        result = self.manager.execute_shell_command("some_command")
        self.assertEqual(result, "")

    def test_stdout_whitespace_only_falls_back_to_stderr(self):
        """If stdout is present but only whitespace (e.g. a stray newline),
        it should still be treated as effectively empty and fall back to
        stderr if stderr has real content."""
        self._mock_exec_command(
            stdout_bytes=b"\n   \n",
            stderr_bytes=b"stride=64\n0.00049 1.697\n",
        )
        result = self.manager.execute_shell_command("lat_mem_rd ...")
        self.assertEqual(result, "stride=64\n0.00049 1.697\n")

    def test_stderr_whitespace_only_does_not_trigger_fallback(self):
        """If stdout is empty and stderr is ALSO only whitespace, no
        fallback should occur; return the (empty) stdout as before."""
        self._mock_exec_command(stdout_bytes=b"", stderr_bytes=b"   \n")
        result = self.manager.execute_shell_command("some_command")
        self.assertEqual(result, "")

    def test_nonzero_exit_status_with_stdout_present_still_returns_stdout(self):
        """A non-zero exit status alone should not trigger the stderr
        fallback if stdout has legitimate content (existing behavior for
        benchmarks that print partial results despite a non-zero exit)."""
        self._mock_exec_command(
            stdout_bytes=b"partial results here\n",
            stderr_bytes=b"some error message\n",
            exit_status=1,
        )
        result = self.manager.execute_shell_command("some_command")
        self.assertEqual(result, "partial results here\n")


class TestSshManagerPreferStderr(unittest.TestCase):
    """
    Tests for the explicit, opt-in `prefer_stderr=True` parameter added to
    support lat_mem_rd, which writes its real data output to stderr rather
    than stdout on-target. This flag defaults to False everywhere else, so
    these tests focus specifically on verifying it does not change default
    (prefer_stderr=False) behavior, and works correctly when explicitly set.
    """

    def setUp(self):
        self.manager = SshManager()
        self.manager.client = MagicMock()

    def _mock_exec_command(self, stdout_bytes: bytes, stderr_bytes: bytes, exit_status: int = 0):
        stdin_mock = MagicMock()
        stdout_mock = make_channel_file(stdout_bytes, exit_status)
        stderr_mock = make_channel_file(stderr_bytes, exit_status)
        self.manager.client.exec_command.return_value = (stdin_mock, stdout_mock, stderr_mock)

    def test_prefer_stderr_true_returns_stderr_when_present(self):
        """When prefer_stderr=True, stderr content should be returned even
        though stdout also has content (simulates lat_mem_rd's real
        behavior of writing its data output to stderr)."""
        self._mock_exec_command(
            stdout_bytes=b"some incidental stdout\n",
            stderr_bytes=b"stride=64\n0.00049 1.697\n64.00000 139.351\n",
        )
        result = self.manager.execute_shell_command("lat_mem_rd ...", prefer_stderr=True)
        self.assertEqual(result, "stride=64\n0.00049 1.697\n64.00000 139.351\n")

    def test_prefer_stderr_true_falls_back_to_stdout_when_stderr_empty(self):
        """When prefer_stderr=True but stderr is empty, stdout should still
        be returned as a fallback so no output is lost."""
        self._mock_exec_command(stdout_bytes=b"only stdout content\n", stderr_bytes=b"")
        result = self.manager.execute_shell_command("some_command", prefer_stderr=True)
        self.assertEqual(result, "only stdout content\n")

    def test_prefer_stderr_default_false_unaffected(self):
        """Default behavior (prefer_stderr not passed / False) must remain
        completely unchanged: stdout is returned when present, regardless
        of stderr content. This protects every other benchmark."""
        self._mock_exec_command(
            stdout_bytes=b"normal stdout output\n",
            stderr_bytes=b"stride=64\n0.00049 1.697\n",
        )
        result = self.manager.execute_shell_command("some_other_benchmark_command")
        self.assertEqual(result, "normal stdout output\n")

    def test_execute_command_wrapper_passes_prefer_stderr_through(self):
        """execute_command() (the SerialCommandExecutor-mimicking entrypoint)
        must correctly forward prefer_stderr to execute_shell_command()."""
        self._mock_exec_command(
            stdout_bytes=b"stdout junk\n",
            stderr_bytes=b"real lat_mem_rd data\n",
        )
        result = self.manager.execute_command("lat_mem_rd ...", prefer_stderr=True)
        self.assertEqual(result, "real lat_mem_rd data\n")


if __name__ == "__main__":
    unittest.main()

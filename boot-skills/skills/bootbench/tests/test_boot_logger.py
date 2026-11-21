"""
test_boot_logger.py - Unit tests for bootbench's file logger (capture/scripts/boot_logger.py)

Covers the logger itself (levels, phase files, secret masking, clipping), the print()-preserving say() helper, the
per-run entry points (init_run / logged_run), and the --log-level wiring of the real capture.py and report.py
main() functions. Nothing here needs a device, a network connection, paramiko or pyserial: the CLI tests stop at
usage errors that are raised before any connection is opened.

Run:  python -m pytest boot-skills/skills/bootbench/tests -q      (or: python -m unittest discover -s <this folder>)

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import contextlib
import io
import logging
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

BOOTBENCH = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = BOOTBENCH / "capture" / "scripts"
REPORT_PY = BOOTBENCH / "report" / "report.py"

sys.path.insert(0, str(SCRIPTS_DIR))

import boot_logger  # noqa: E402
from boot_logger import BootLogger, boot_log, say  # noqa: E402

SECRET = "hunter2secret"


def read(path) -> str:
    return Path(path).read_text(encoding="utf-8")


def central_log(run_dir) -> Path:
    files = sorted(Path(run_dir).glob("log-*.log"))
    assert len(files) == 1, f"expected exactly one central log in {run_dir}, found {files}"
    return files[0]


class LoggerTestCase(unittest.TestCase):
    """Fixture that undoes everything the logger can change process-wide: the root logger's level and handlers, the
    paramiko/comtypes levels, the registered secrets and the shared boot_log singleton."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

        root = logging.getLogger()
        self._root_handlers = list(root.handlers)
        self._levels = {name: logging.getLogger(name).level for name in ("", "paramiko", "comtypes")}
        boot_logger.clear_secrets()
        boot_log.close()
        self.addCleanup(self._restore)

    def _restore(self):
        boot_log.close()
        boot_log.set_level("INFO")
        boot_logger.clear_secrets()
        root = logging.getLogger()
        for handler in list(root.handlers):
            if handler not in self._root_handlers:
                root.removeHandler(handler)
        for name, level in self._levels.items():
            logging.getLogger(name).setLevel(level)

    def new_logger(self, name: str) -> BootLogger:
        """A logger of its own (so tests do not share state through the singleton), closed when the test ends."""
        lg = BootLogger(name)
        self.addCleanup(lg.close)
        return lg

    def started(self, lg: BootLogger, level="INFO", stamp="t") -> Path:
        """Give `lg` a central log and a phase directory under the test's temp dir; return that directory."""
        lg.set_level(level)
        lg.add_centralized_handler(self.dir, stamp)
        lg.configure_run_dir(self.dir)
        return self.dir

    def stray_root_handlers(self):
        return [h for h in logging.getLogger().handlers if h not in self._root_handlers]


# ---------------------------------------------------------------------------
# Level
# ---------------------------------------------------------------------------

class TestLevel(LoggerTestCase):

    def test_parse_level(self):
        self.assertEqual(boot_logger.parse_level("debug"), logging.DEBUG)
        self.assertEqual(boot_logger.parse_level(" Info "), logging.INFO)
        self.assertEqual(boot_logger.parse_level("WARNING"), logging.WARNING)
        self.assertEqual(boot_logger.parse_level(logging.ERROR), logging.ERROR)

    def test_parse_level_rejects_anything_else(self):
        for bad in ("verbose", "", "warn", None, True, 0, 15, 1.5, "10"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    boot_logger.parse_level(bad)

    def test_default_level_is_info_and_drops_debug(self):
        lg = self.new_logger("bb_test_default")
        self.assertEqual(lg.level, logging.INFO)
        self.started(lg, level="INFO")
        lg.debug("hidden-debug")
        lg.info("shown-info")
        text = read(central_log(self.dir))
        self.assertIn("shown-info", text)
        self.assertNotIn("hidden-debug", text)

    def test_debug_level_records_debug(self):
        lg = self.new_logger("bb_test_debug")
        self.started(lg, level="DEBUG")
        lg.debug("visible-debug")
        self.assertIn("[DEBUG] visible-debug", read(central_log(self.dir)))

    def test_warning_level_keeps_only_problems(self):
        lg = self.new_logger("bb_test_warning")
        self.started(lg, level="WARNING")
        lg.info("quiet-info")
        lg.warning("loud-warning")
        lg.error("loud-error")
        text = read(central_log(self.dir))
        self.assertNotIn("quiet-info", text)
        self.assertIn("[WARNING] loud-warning", text)
        self.assertIn("[ERROR] loud-error", text)

    def test_invalid_level_raises_and_changes_nothing(self):
        lg = self.new_logger("bb_test_invalid")
        self.started(lg, level="WARNING")
        root_level = logging.getLogger().level
        for bad in ("loud", True, 0, 15, None):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    lg.set_level(bad)
                self.assertEqual(lg.level, logging.WARNING)
                self.assertEqual(lg.centralized_handler.level, logging.WARNING)
                self.assertEqual(logging.getLogger().level, root_level)

    def test_level_reaches_open_and_later_phase_files(self):
        lg = self.new_logger("bb_test_phase_level")
        self.started(lg, level="INFO")
        lg.set_phase("setup")
        lg.set_level("DEBUG")
        lg.debug("in-setup")
        lg.set_phase("boot")
        lg.debug("in-boot")
        self.assertIn("in-setup", read(self.dir / "setup.log"))
        self.assertIn("in-boot", read(self.dir / "boot.log"))

    def test_repeated_set_level_adds_no_handlers_and_no_duplicate_lines(self):
        lg = self.new_logger("bb_test_repeat")
        self.started(lg)
        before = len(lg.logger.handlers), len(logging.getLogger().handlers)
        for level in ("DEBUG", "INFO", "DEBUG", "WARNING", "INFO"):
            lg.set_level(level)
        self.assertEqual((len(lg.logger.handlers), len(logging.getLogger().handlers)), before)
        lg.info("once")
        self.assertEqual(read(central_log(self.dir)).count("once"), 1)

    def test_paramiko_and_comtypes_stay_out_of_debug(self):
        lg = self.new_logger("bb_test_capped")
        self.started(lg, level="DEBUG")
        for name in ("paramiko", "comtypes"):
            self.assertGreaterEqual(logging.getLogger(name).level, logging.INFO)
        logging.getLogger("paramiko.transport").debug("packet-noise")
        logging.getLogger("paramiko.transport").info("kex-done")
        text = read(central_log(self.dir))
        self.assertNotIn("packet-noise", text)
        self.assertIn("kex-done", text)

    def test_capped_loggers_follow_a_stricter_level(self):
        lg = self.new_logger("bb_test_capped_warning")
        self.started(lg, level="WARNING")
        self.assertEqual(logging.getLogger("paramiko").level, logging.WARNING)

    def test_root_logger_is_lowered_for_library_records_but_never_raised(self):
        root = logging.getLogger()
        root.setLevel(logging.WARNING)
        lg = self.new_logger("bb_test_root_low")
        lg.add_centralized_handler(self.dir, "t")        # no set_level(): the logger is at its INFO default
        self.assertEqual(root.level, logging.INFO)
        logging.getLogger("some.library").info("library-info")
        self.assertIn("library-info", read(central_log(self.dir)))

        root.setLevel(logging.DEBUG)
        lg2 = self.new_logger("bb_test_root_high")
        with tempfile.TemporaryDirectory() as other:
            lg2.add_centralized_handler(Path(other), "t")
            self.assertEqual(root.level, logging.DEBUG)   # already more verbose: left alone
            lg2.close()

    def test_library_records_reach_the_file_exactly_once(self):
        lg = self.new_logger("bb_test_once")
        self.started(lg)
        logging.getLogger("some.module").warning("module-msg")
        lg.warning("own-msg")
        text = read(central_log(self.dir))
        self.assertEqual(text.count("module-msg"), 1)
        self.assertEqual(text.count("own-msg"), 1)


# ---------------------------------------------------------------------------
# Phases and handlers
# ---------------------------------------------------------------------------

class TestPhases(LoggerTestCase):

    def test_each_phase_gets_its_own_file_and_the_central_log_gets_all(self):
        lg = self.new_logger("bb_test_phases")
        self.started(lg)
        lg.set_phase("setup")
        lg.info("a-setup")
        lg.set_phase("boot")
        lg.info("b-boot")
        lg.set_phase("collect")
        lg.info("c-collect")
        lg.end_phase()

        self.assertEqual(sorted(p.name for p in self.dir.glob("*.log")),
                         ["boot.log", "collect.log", "log-t.log", "setup.log"])
        for name, mine, others in (("setup", "a-setup", ("b-boot", "c-collect")),
                                   ("boot", "b-boot", ("a-setup", "c-collect")),
                                   ("collect", "c-collect", ("a-setup", "b-boot"))):
            text = read(self.dir / f"{name}.log")
            self.assertIn(mine, text)
            self.assertIn(f"=== Started phase: {name} ===", text)
            self.assertIn(f"=== Ended phase: {name} ===", text)
            for other in others:
                self.assertNotIn(other, text)
        central = read(self.dir / "log-t.log")
        for message in ("a-setup", "b-boot", "c-collect"):
            self.assertIn(message, central)

    def test_re_entering_a_phase_continues_its_file(self):
        lg = self.new_logger("bb_test_reenter")
        self.started(lg)
        lg.set_phase("setup")
        lg.info("first-visit")
        lg.set_phase("boot")
        lg.info("elsewhere")
        lg.set_phase("setup")
        lg.info("second-visit")
        text = read(self.dir / "setup.log")
        self.assertIn("first-visit", text)
        self.assertIn("second-visit", text)
        self.assertEqual(text.count("=== Started phase: setup ==="), 2)
        self.assertNotIn("elsewhere", text)

    def test_set_phase_to_the_current_phase_is_a_no_op(self):
        lg = self.new_logger("bb_test_idempotent")
        self.started(lg)
        lg.set_phase("boot")
        handler = lg.current_phase_handler
        handlers = len(lg.logger.handlers)
        lg.set_phase("boot")
        self.assertIs(lg.current_phase_handler, handler)
        self.assertEqual(len(lg.logger.handlers), handlers)
        self.assertEqual(read(self.dir / "boot.log").count("=== Started phase: boot ==="), 1)

    def test_unknown_phase_raises_and_keeps_the_current_one(self):
        lg = self.new_logger("bb_test_bad_phase")
        self.started(lg)
        lg.set_phase("boot")
        with self.assertRaises(ValueError):
            lg.set_phase("teardown")
        self.assertEqual(lg.current_phase, "boot")
        self.assertIsNotNone(lg.current_phase_handler)
        self.assertFalse((self.dir / "teardown.log").exists())

    def test_phase_context_manager_restores_the_previous_phase(self):
        lg = self.new_logger("bb_test_ctx")
        self.started(lg)
        lg.set_phase("boot")
        with lg.phase("setup"):
            self.assertEqual(lg.current_phase, "setup")
            lg.info("inside")
        self.assertEqual(lg.current_phase, "boot")
        lg.info("after")
        self.assertIn("inside", read(self.dir / "setup.log"))
        self.assertIn("after", read(self.dir / "boot.log"))
        self.assertNotIn("inside", read(self.dir / "boot.log"))

    def test_phase_context_manager_restores_even_when_the_block_raises(self):
        lg = self.new_logger("bb_test_ctx_raise")
        self.started(lg)
        lg.set_phase("boot")
        with self.assertRaises(RuntimeError):
            with lg.phase("setup"):
                raise RuntimeError("inside")
        self.assertEqual(lg.current_phase, "boot")

    def test_phase_context_manager_without_a_previous_phase_ends_it(self):
        lg = self.new_logger("bb_test_ctx_none")
        self.started(lg)
        with lg.phase("collect"):
            self.assertEqual(lg.current_phase, "collect")
        self.assertIsNone(lg.current_phase)
        self.assertIsNone(lg.current_phase_handler)

    def test_without_a_run_dir_only_the_phase_name_is_tracked(self):
        lg = self.new_logger("bb_test_nodir")
        lg.set_phase("boot")
        self.assertEqual(lg.current_phase, "boot")
        self.assertIsNone(lg.current_phase_handler)
        lg.info("goes nowhere")           # must not raise

    def test_close_releases_every_handler_and_is_safe_twice(self):
        lg = self.new_logger("bb_test_close")
        self.started(lg)
        lg.set_phase("boot")
        lg.close()
        lg.close()
        self.assertEqual([h for h in lg.logger.handlers if not isinstance(h, logging.NullHandler)], [])
        self.assertEqual(self.stray_root_handlers(), [])
        self.assertIsNone(lg.centralized_handler)
        self.assertIsNone(lg.current_phase_handler)
        self.assertIsNone(lg.run_dir)

    def test_logger_can_be_started_again_after_close(self):
        lg = self.new_logger("bb_test_restart")
        self.started(lg, stamp="one")
        lg.info("first-run")
        lg.close()
        self.started(lg, stamp="two")
        lg.info("second-run")
        self.assertNotIn("second-run", read(self.dir / "log-one.log"))
        self.assertIn("second-run", read(self.dir / "log-two.log"))

    def test_logger_does_not_propagate_to_the_root(self):
        lg = self.new_logger("bb_test_propagate")
        self.assertFalse(lg.logger.propagate)
        seen = []

        class Collect(logging.Handler):
            def emit(self, record):
                seen.append(record.getMessage())

        collector = Collect()
        logging.getLogger().addHandler(collector)
        self.addCleanup(logging.getLogger().removeHandler, collector)
        lg.warning("only-in-the-file-logger")
        self.assertEqual(seen, [])

    def test_the_logger_never_writes_to_stderr_or_stdout(self):
        """With no handler of its own a logger would hand WARNING+ records to logging.lastResort, i.e. stderr."""
        lg = self.new_logger("bb_test_silent")
        err, out = io.StringIO(), io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
            lg.warning("not on the console")
            lg.error("neither is this")
            lg.exception("nor this")
            boot_log.error("nor from the shared logger")
        self.assertEqual((err.getvalue(), out.getvalue()), ("", ""))


# ---------------------------------------------------------------------------
# Secrets and clipping
# ---------------------------------------------------------------------------

class TestRedaction(LoggerTestCase):

    def test_registered_secrets_are_masked_in_messages_and_arguments(self):
        boot_logger.add_secret(SECRET)
        lg = self.new_logger("bb_test_mask")
        self.started(lg)
        lg.info("login with %s failed", SECRET)
        lg.info(f"plain {SECRET} text")
        text = read(central_log(self.dir))
        self.assertNotIn(SECRET, text)
        self.assertEqual(text.count(boot_logger.REDACTED), 2)

    def test_secrets_are_masked_in_tracebacks(self):
        boot_logger.add_secret(SECRET)
        lg = self.new_logger("bb_test_mask_tb")
        self.started(lg)
        try:
            raise RuntimeError(f"cannot authenticate with {SECRET}")
        except RuntimeError:
            lg.exception("auth failed")
        text = read(central_log(self.dir))
        self.assertNotIn(SECRET, text)
        self.assertIn("RuntimeError: cannot authenticate with ********", text)

    def test_a_secret_that_contains_another_is_masked_as_a_whole(self):
        boot_logger.add_secret("abc")
        boot_logger.add_secret("abcdef")
        self.assertEqual(boot_logger.redact("x abcdef y"), "x ******** y")

    def test_empty_and_non_string_secrets_are_ignored(self):
        for value in (None, "", 0, 1234, b"bytes", ["a"]):
            boot_logger.add_secret(value)
        self.assertEqual(boot_logger.redact("nothing to hide 1234"), "nothing to hide 1234")

    def test_masking_does_not_change_the_log_record_itself(self):
        boot_logger.add_secret(SECRET)
        record = logging.LogRecord("x", logging.INFO, __file__, 1, "pw=%s", (SECRET,), None)
        first = boot_log.formatter.format(record)
        second = boot_log.formatter.format(record)
        self.assertEqual(first, second)
        self.assertNotIn(SECRET, first)
        self.assertEqual(record.getMessage(), f"pw={SECRET}")        # other handlers keep what was logged

    def test_a_traceback_cached_by_another_handler_is_still_capped_and_masked(self):
        """logging.Formatter reuses record.exc_text when a handler formatted the record before, which would skip the
        cap; the formatter must always build the traceback itself."""
        boot_logger.add_secret(SECRET)
        try:
            raise RuntimeError(SECRET)
        except RuntimeError:
            exc_info = sys.exc_info()
        record = logging.LogRecord("x", logging.ERROR, __file__, 1, "failed", (), exc_info)
        record.exc_text = f"Traceback cached by another handler: {SECRET}\n" + "line\n" * 100_000
        out = boot_log.formatter.format(record)
        self.assertNotIn(SECRET, out)
        self.assertLess(len(out), 2 * boot_logger.MAX_PART_CHARS)
        self.assertIn("RuntimeError: ********", out)           # rebuilt from exc_info, not the cached text

    def test_redact_argv_masks_the_password_in_every_form(self):
        r = boot_logger.REDACTED
        cases = [
            (["--password", SECRET], ["--password", r]),
            (["--password=" + SECRET], [f"--password={r}"]),
            (["--pass", SECRET], ["--pass", r]),                # argparse accepts any unambiguous prefix
            (["--pas=" + SECRET], [f"--pas={r}"]),
            (["--p", SECRET], ["--p", r]),
            (["--host", "h", "--password", SECRET, "--user", "root"], ["--host", "h", "--password", r, "--user", "root"]),
        ]
        for argv, expected in cases:
            with self.subTest(argv=argv):
                self.assertEqual(boot_logger.redact_argv(argv), expected)

    def test_redact_argv_leaves_other_options_alone(self):
        argv = ["capture.py", "--port", "22", "--ssh-port", "22", "--", "-p", "x", "--pa-th", "y", "--target", "t"]
        self.assertEqual(boot_logger.redact_argv(argv), argv)

    def test_redact_argv_masks_a_trailing_password_flag_without_failing(self):
        self.assertEqual(boot_logger.redact_argv(["--password"]), ["--password"])

    def test_clip_flattens_and_bounds_a_command(self):
        self.assertEqual(boot_logger.clip("a  b\n\tc"), "a b c")
        long = "x" * 500
        clipped = boot_logger.clip(long, 50)
        self.assertTrue(clipped.startswith("x" * 50))
        self.assertIn("[500 chars]", clipped)
        self.assertEqual(boot_logger.clip(Exception("boom")), "boom")

    def test_an_over_long_message_keeps_its_head_and_tail(self):
        lg = self.new_logger("bb_test_long")
        self.started(lg)
        lg.error("HEAD-MARK " + "m" * 100_000 + " TAIL-MARK")
        text = read(central_log(self.dir))
        self.assertIn("HEAD-MARK", text)
        self.assertIn("TAIL-MARK", text)
        self.assertIn("characters omitted", text)
        self.assertLess(len(text), boot_logger.MAX_PART_CHARS + 1000)

    def test_an_over_long_traceback_is_capped_separately(self):
        lg = self.new_logger("bb_test_long_tb")
        self.started(lg)
        try:
            raise RuntimeError("dmesg:\n" + "line\n" * 50_000)
        except RuntimeError:
            lg.exception("parse failed")
        text = read(central_log(self.dir))
        self.assertIn("Traceback (most recent call last)", text)
        self.assertIn("characters omitted", text)
        self.assertLess(len(text), 2 * boot_logger.MAX_PART_CHARS + 1000)

    def test_a_secret_cut_by_the_clip_leaves_no_fragment(self):
        """Masking happens before the cut, so a secret that straddles it cannot survive as a readable piece."""
        boot_logger.add_secret(SECRET)
        head = boot_logger.MAX_PART_CHARS * 3 // 4
        tail = boot_logger.MAX_PART_CHARS - head
        for label, message, cut_inside_the_mask in (
            ("head edge", "a" * (head - 5) + SECRET + "b" * 20_000, True),
            ("tail edge", "a" * 20_000 + SECRET + "b" * (tail - 5), True),
            ("middle", "a" * 20_000 + SECRET + "b" * 20_000, False),
        ):
            with self.subTest(label):
                out = boot_log.formatter.format(
                    logging.LogRecord("x", logging.INFO, __file__, 1, message, (), None))
                for fragment in (SECRET, SECRET[:4], SECRET[-4:], "2sec"):
                    self.assertNotIn(fragment, out)
                if cut_inside_the_mask:
                    # Proves the scenario is real: the cut fell inside the 8-character mask, which survives only
                    # partly (5 of its 8 asterisks), and what is left of the secret is nothing readable.
                    self.assertIn("*****", out)
                    self.assertNotIn(boot_logger.REDACTED, out)


# ---------------------------------------------------------------------------
# say()
# ---------------------------------------------------------------------------

class TestSay(LoggerTestCase):

    def capture_stdout(self, fn):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            fn()
        return buf.getvalue()

    def test_say_prints_exactly_what_print_prints(self):
        for message in ("plain", "\nleading", "trailing\n", "\n--- Boot default-1 (1/6) ---", "", "multi\nline", 42):
            with self.subTest(message=message):
                self.assertEqual(self.capture_stdout(lambda: say(message)),
                                 self.capture_stdout(lambda: print(message)))

    def test_say_does_not_mask_the_console_output(self):
        boot_logger.add_secret(SECRET)
        self.assertEqual(self.capture_stdout(lambda: say(f"echo {SECRET}")), f"echo {SECRET}\n")

    def start(self, **kwargs) -> Path:
        """Start a run in the test's temp dir and return its central log."""
        return central_log(boot_logger.init_run("INFO", log_root=self.dir, **kwargs))

    def test_say_records_the_text_at_the_requested_level(self):
        log = self.start()
        self.capture_stdout(lambda: say("an info line"))
        self.capture_stdout(lambda: say("a warning line", logging.WARNING))
        self.capture_stdout(lambda: say("an error line", logging.ERROR))
        text = read(log)
        self.assertIn("[INFO] an info line", text)
        self.assertIn("[WARNING] a warning line", text)
        self.assertIn("[ERROR] an error line", text)

    def test_say_strips_spacing_newlines_from_the_log_and_skips_blank_lines(self):
        log = self.start()
        self.capture_stdout(lambda: say("\n--- Boot default-1 ---\n"))
        self.capture_stdout(lambda: say(""))
        self.capture_stdout(lambda: say("\n\n"))
        lines = read(log).splitlines()
        after_start = lines[lines.index(next(l for l in lines if "Log folder:" in l)) + 1:]
        self.assertEqual(len(after_start), 1)                       # the two blank calls wrote nothing
        self.assertTrue(after_start[0].endswith("[INFO] --- Boot default-1 ---"))

    def test_say_masks_the_log_but_not_the_console(self):
        log = self.start(secrets=[SECRET])
        shown = self.capture_stdout(lambda: say(f"password is {SECRET}"))
        self.assertIn(SECRET, shown)
        self.assertNotIn(SECRET, read(log))

    def test_say_passes_exc_info_to_the_log_only(self):
        log = self.start()
        try:
            raise RuntimeError("kaput")
        except RuntimeError:
            shown = self.capture_stdout(lambda: say("capture failed", logging.ERROR, exc_info=True))
        self.assertEqual(shown, "capture failed\n")
        text = read(log)
        self.assertIn("Traceback (most recent call last)", text)
        self.assertIn("RuntimeError: kaput", text)

    def test_say_works_before_any_run_is_started(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            shown = self.capture_stdout(lambda: say("no log yet", logging.ERROR))
        self.assertEqual(shown, "no log yet\n")
        self.assertEqual(err.getvalue(), "")


# ---------------------------------------------------------------------------
# init_run / logged_run
# ---------------------------------------------------------------------------

class TestInitRun(LoggerTestCase):

    def test_init_run_creates_a_timestamped_folder_with_the_central_log(self):
        run_dir = boot_logger.init_run("INFO", ["capture.py", "--host", "h"], log_root=self.dir)
        self.assertEqual(run_dir.parent, self.dir)
        self.assertRegex(run_dir.name, r"^\d{8}_\d{6}$")
        log = central_log(run_dir)
        self.assertEqual(log.name, f"log-{run_dir.name}.log")
        text = read(log)
        self.assertIn("bootbench started; log level INFO", text)
        self.assertIn("Command line: capture.py --host h", text)
        self.assertIn(f"Log folder: {run_dir}", text)
        boot_log.close()

    def test_the_command_line_is_logged_with_the_password_masked_even_if_unregistered(self):
        run_dir = boot_logger.init_run("INFO", ["capture.py", "--password", SECRET, "--pass=" + SECRET],
                                       log_root=self.dir)
        text = read(central_log(run_dir))
        self.assertNotIn(SECRET, text)
        self.assertIn("--password '********'", text)          # shlex.quote wraps the asterisks ...
        self.assertIn("'--pass=********'", text)               # ... and, for the = form, the whole argument
        boot_log.close()

    def test_secrets_given_to_init_run_are_registered(self):
        run_dir = boot_logger.init_run("INFO", secrets=[SECRET, None, ""], log_root=self.dir)
        boot_log.info("the password is %s", SECRET)
        self.assertNotIn(SECRET, read(central_log(run_dir)))
        boot_log.close()

    def test_an_invalid_level_raises_before_anything_is_created(self):
        with self.assertRaises(ValueError):
            boot_logger.init_run("loud", log_root=self.dir)
        self.assertEqual(list(self.dir.iterdir()), [])
        self.assertIsNone(boot_log.centralized_handler)

    def test_debug_level_is_applied(self):
        run_dir = boot_logger.init_run("debug", log_root=self.dir)
        boot_log.debug("debug-detail")
        self.assertIn("[DEBUG] debug-detail", read(central_log(run_dir)))
        boot_log.close()

    def test_an_unwritable_log_folder_degrades_to_no_logging_with_one_warning(self):
        blocker = self.dir / "not-a-directory"
        blocker.write_text("a file where the log root should be")
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            run_dir = boot_logger.init_run("INFO", ["capture.py"], log_root=blocker)
            say("the capture carries on")
            boot_log.error("and logging calls stay harmless")
        self.assertIsNone(run_dir)
        self.assertEqual(out.getvalue(), "the capture carries on\n")
        self.assertEqual(err.getvalue().count("WARNING: bootbench file logging is disabled"), 1)
        self.assertEqual(len(err.getvalue().strip().splitlines()), 1)
        self.assertIsNone(boot_log.centralized_handler)
        self.assertEqual(self.stray_root_handlers(), [])

    def test_a_failed_init_does_not_stop_a_later_one(self):
        blocker = self.dir / "file"
        blocker.write_text("x")
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertIsNone(boot_logger.init_run("INFO", log_root=blocker))
        good = boot_logger.init_run("INFO", log_root=self.dir / "logs")
        self.assertIsNotNone(good)
        self.assertTrue(central_log(good).is_file())
        boot_log.close()

    def test_repeated_runs_leak_no_handlers(self):
        baseline_root = len(logging.getLogger().handlers)
        baseline_own = len(boot_log.logger.handlers)
        for i in range(5):
            boot_logger.init_run("INFO", log_root=self.dir / str(i))
            boot_log.set_phase("boot")
        boot_log.close()
        self.assertEqual(len(logging.getLogger().handlers), baseline_root)
        self.assertEqual(len(boot_log.logger.handlers), baseline_own)

    def test_two_runs_in_the_same_second_share_a_folder_and_append(self):
        class Frozen(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 11, 5, 12, 0, 0)

        with mock.patch.object(boot_logger, "datetime", Frozen):
            first = boot_logger.init_run("INFO", log_root=self.dir)
            boot_log.info("from-the-first-run")
            second = boot_logger.init_run("INFO", log_root=self.dir)
            boot_log.info("from-the-second-run")
        boot_log.close()
        self.assertEqual(first, second)
        text = read(central_log(first))
        self.assertIn("from-the-first-run", text)       # appended to, never truncated
        self.assertIn("from-the-second-run", text)

    def test_library_records_land_in_the_run_log(self):
        run_dir = boot_logger.init_run("INFO", log_root=self.dir)
        logging.getLogger("paramiko.transport").info("Connected (version 2.0, client OpenSSH)")
        self.assertIn("Connected (version 2.0", read(central_log(run_dir)))
        boot_log.close()


class TestLoggedRun(LoggerTestCase):

    def run_dir(self) -> Path:
        dirs = [p for p in self.dir.iterdir() if p.is_dir()]
        self.assertEqual(len(dirs), 1)
        return dirs[0]

    def test_a_normal_run_is_logged_as_finished(self):
        with boot_logger.logged_run("INFO", ["capture.py"], log_root=self.dir):
            boot_log.info("work")
        text = read(central_log(self.run_dir()))
        self.assertIn("work", text)
        self.assertIn("Finished", text)
        self.assertIsNone(boot_log.centralized_handler)

    def test_system_exit_is_logged_and_re_raised_unchanged(self):
        for code, expected in ((1, "[ERROR] Exiting with status 1"), (2, "[ERROR] Exiting with status 2"),
                               (0, "[INFO] Exiting with status 0"), (None, "[INFO] Exiting with status 0")):
            with self.subTest(code=code):
                with tempfile.TemporaryDirectory() as tmp:
                    with self.assertRaises(SystemExit) as caught:
                        with boot_logger.logged_run("INFO", log_root=Path(tmp)):
                            raise SystemExit(code)
                    self.assertEqual(caught.exception.code, code)
                    self.assertIn(expected, read(central_log(next(Path(tmp).iterdir()))))

    def test_keyboard_interrupt_is_logged_and_re_raised(self):
        with self.assertRaises(KeyboardInterrupt):
            with boot_logger.logged_run("INFO", log_root=self.dir):
                raise KeyboardInterrupt
        self.assertIn("[WARNING] Interrupted by the user", read(central_log(self.run_dir())))

    def test_an_unhandled_exception_is_logged_with_its_traceback_and_re_raised(self):
        with self.assertRaises(ValueError) as caught:
            with boot_logger.logged_run("INFO", log_root=self.dir, secrets=[SECRET]):
                raise ValueError(f"bad value {SECRET}")
        self.assertIn(SECRET, str(caught.exception))                     # the exception itself is untouched
        text = read(central_log(self.run_dir()))
        self.assertIn("[ERROR] Unhandled exception", text)
        self.assertIn("ValueError: bad value ********", text)
        self.assertNotIn(SECRET, text)

    def test_the_exit_is_recorded_in_the_active_phase_file_and_everything_is_closed(self):
        with self.assertRaises(SystemExit):
            with boot_logger.logged_run("INFO", log_root=self.dir):
                boot_log.set_phase("boot")
                raise SystemExit(1)
        self.assertIsNone(boot_log.current_phase)
        self.assertIsNone(boot_log.run_dir)
        self.assertEqual(self.stray_root_handlers(), [])
        text = read(self.run_dir() / "boot.log")
        self.assertIn("Exiting with status 1", text)
        self.assertIn("=== Ended phase: boot ===", text)

    def test_logging_adds_nothing_to_stdout_or_stderr(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            for exc in (SystemExit(1), KeyboardInterrupt(), RuntimeError("x")):
                with tempfile.TemporaryDirectory() as tmp:
                    with self.assertRaises(type(exc)):
                        with boot_logger.logged_run("DEBUG", ["capture.py"], log_root=Path(tmp)):
                            raise exc
        self.assertEqual((out.getvalue(), err.getvalue()), ("", ""))

    def test_repeated_runs_leave_no_handlers_behind(self):
        baseline = len(logging.getLogger().handlers)
        for i in range(3):
            with self.assertRaises(SystemExit):
                with boot_logger.logged_run("INFO", log_root=self.dir / str(i)):
                    raise SystemExit(1)
        self.assertEqual(len(logging.getLogger().handlers), baseline)


# ---------------------------------------------------------------------------
# --log-level and the real entry points
# ---------------------------------------------------------------------------

class TestLogLevelArgument(LoggerTestCase):

    def parser(self):
        import argparse
        parser = argparse.ArgumentParser(prog="x")
        boot_logger.add_log_level_argument(parser)
        return parser

    def test_default_is_info(self):
        self.assertEqual(self.parser().parse_args([]).log_level, "INFO")

    def test_values_are_case_insensitive(self):
        for given, expected in (("debug", "DEBUG"), ("Info", "INFO"), ("WARNING", "WARNING"), ("error", "ERROR")):
            self.assertEqual(self.parser().parse_args(["--log-level", given]).log_level, expected)

    def test_an_invalid_level_is_a_usage_error(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as caught:
            self.parser().parse_args(["--log-level", "loud"])
        self.assertEqual(caught.exception.code, 2)
        self.assertIn("invalid choice", err.getvalue())


class TestEntryPoints(LoggerTestCase):
    """Drives the real capture.py and report.py main() as far as their usage checks, which come before any device
    or network access."""

    @classmethod
    def setUpClass(cls):
        import capture
        import report
        cls.capture = capture
        cls.report = report

    def main(self, module, argv):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "argv", argv), mock.patch.object(boot_logger, "LOG_ROOT", self.dir), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as caught:
                module.main()
        return caught.exception.code, out.getvalue(), err.getvalue()

    def run_dir(self) -> Path:
        dirs = [p for p in self.dir.iterdir() if p.is_dir()]
        self.assertEqual(len(dirs), 1)
        return dirs[0]

    def test_both_scripts_share_one_logger_object(self):
        self.assertIs(self.capture.boot_log, boot_log)
        self.assertIs(self.report.boot_log, boot_log)
        self.assertIs(self.capture.say, say)
        self.assertIs(self.report.say, say)

    def test_both_parsers_take_log_level(self):
        for module, argv in ((self.capture, []), (self.report, [])):
            args = module.build_parser().parse_args(argv)
            self.assertEqual(args.log_level, "INFO")
        self.assertEqual(self.capture.build_parser().parse_args(["--log-level", "debug"]).log_level, "DEBUG")
        self.assertEqual(self.report.build_parser().parse_args(["--log-level", "warning"]).log_level, "WARNING")

    def test_capture_usage_error_keeps_its_output_and_exit_code_and_is_logged(self):
        code, out, err = self.main(self.capture, ["capture.py", "--host", "h", "--com-port", "COM3",
                                                  "--password", SECRET])
        self.assertEqual(code, 1)
        self.assertEqual(out, "--host (SSH mode) and --com-port/--tac-port (serial mode) are mutually exclusive; "
                              "pass one or the other.\n")
        self.assertEqual(err, "")
        text = read(central_log(self.run_dir()))
        self.assertIn("[ERROR] --host (SSH mode) and --com-port/--tac-port", text)
        self.assertIn("Exiting with status 1", text)
        self.assertNotIn(SECRET, text)

    def test_capture_resume_pull_without_a_target_is_an_error_in_the_log(self):
        code, out, _err = self.main(self.capture, ["capture.py", "--host", "h", "--password", SECRET, "--resume-pull"])
        self.assertEqual(code, 1)
        self.assertIn("--resume-pull requires --target", out)
        self.assertIn("[ERROR] --resume-pull requires --target", read(central_log(self.run_dir())))

    def test_report_usage_error_keeps_its_output_and_exit_code_and_is_logged(self):
        code, out, err = self.main(self.report, ["report.py", "--report-cmd", "render", "--log-level", "debug"])
        self.assertEqual((code, out, err), (1, "report.py requires --target.\n", ""))
        run_dir = self.run_dir()
        self.assertIn("log level DEBUG", read(central_log(run_dir)))
        self.assertIn("[ERROR] report.py requires --target.", read(run_dir / "collect.log"))

    def test_report_runs_in_the_collect_phase(self):
        self.main(self.report, ["report.py"])
        self.assertTrue((self.run_dir() / "collect.log").is_file())
        self.assertFalse((self.run_dir() / "boot.log").exists())

    def test_a_bad_level_on_either_script_is_a_usage_error_before_any_log_is_made(self):
        for module, prog in ((self.capture, "capture.py"), (self.report, "report.py")):
            with self.subTest(prog=prog):
                code, out, err = self.main(module, [prog, "--log-level", "loud"])
                self.assertEqual(code, 2)
                self.assertEqual(out, "")
                self.assertIn("invalid choice", err)
                self.assertIn("LOUD", err)
        self.assertEqual(list(self.dir.iterdir()), [])

    def test_report_py_finds_the_logger_when_run_on_its_own(self):
        """report.py sits in a different folder from boot_logger.py; run directly nothing puts capture/scripts on
        sys.path, so it has to add it itself."""
        code = (
            "import importlib.util, sys\n"
            "spec = importlib.util.spec_from_file_location('report_under_test', sys.argv[1])\n"
            "module = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(module)\n"
            "import boot_logger\n"
            "assert module.boot_log is boot_logger.boot_log\n"
            "print('ok')\n"
        )
        with tempfile.TemporaryDirectory() as cwd:
            done = subprocess.run([sys.executable, "-I", "-c", code, str(REPORT_PY)], cwd=cwd,
                                  capture_output=True, text=True, timeout=60)
        self.assertEqual((done.returncode, done.stdout.strip()), (0, "ok"), done.stderr)


if __name__ == "__main__":
    unittest.main()

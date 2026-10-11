"""
test_telemetry_parser.py - Unit tests for the enhanced TelemetryParser
(cpufreq, dmesg, thermal, vmstat, top, ftrace parsing).

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import sys
import tempfile
import shutil
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.reporting.telemetry_parser import TelemetryParser


class TestTelemetryParser(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.parser = TelemetryParser()

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _write(self, filename: str, content: str):
        path = self.tmp_dir / filename
        path.write_text(content)
        return path

    def test_missing_files_produce_warnings_not_crash(self):
        anomalies = self.parser.parse_anomalies(str(self.tmp_dir))
        self.assertIn("warnings", anomalies)
        self.assertTrue(len(anomalies["warnings"]) >= 5)
        # No crash, all lists empty
        self.assertEqual(anomalies["cpu_frequency_drops"], [])
        self.assertEqual(anomalies["context_switch_spike"], [])

    def test_cpufreq_drop_detection(self):
        content = (
            "2026-09-08 02:05:10\n"
            "cpu0: 2400000 kHz\n"
            "cpu1: 2400000 kHz\n"
            "---\n"
            "2026-09-08 02:05:11\n"
            "cpu0: 1200000 kHz\n"
            "cpu1: 2400000 kHz\n"
            "---\n"
        )
        self._write("cpufreq_metrics_2026-09-08_02-05-10.log", content)
        anomalies = self.parser.parse_anomalies(str(self.tmp_dir))
        self.assertEqual(len(anomalies["cpu_frequency_drops"]), 1)
        self.assertEqual(anomalies["cpu_frequency_drops"][0]["core"], "cpu0")

    def test_dmesg_throttle_and_oom(self):
        content = (
            "[100.0] thermal: cpu0 throttled due to high temperature\n"
            "[200.0] Out of memory: Killed process 1234 (benchmark)\n"
        )
        self._write("dmesg_metrics_2026-09-08_02-05-10.log", content)
        anomalies = self.parser.parse_anomalies(str(self.tmp_dir))
        self.assertEqual(len(anomalies["thermal_throttles"]), 1)
        self.assertEqual(len(anomalies["oom_kills"]), 1)

    def test_thermal_csv_high_temp(self):
        content = (
            "timestamp,thermal_zone,type,temp_mC\n"
            "1000,thermal_zone0,cpu-0-thermal,90000\n"
            "1001,thermal_zone1,ddrss-0-thermal,80000\n"
        )
        self._write("thermal_metrics_2026-09-08_02-05-10.csv", content)
        anomalies = self.parser.parse_anomalies(str(self.tmp_dir))
        self.assertEqual(len(anomalies["thermal_high_temp"]), 2)

    def test_vmstat_spikes(self):
        # header lines + one normal sample + one spike sample
        # cols: r b swpd free buff cache si so bi bo in cs us sy id wa st
        header1 = "procs -----------memory---------- ---swap-- -----io---- -system-- ------cpu-----\n"
        header2 = " r  b   swpd   free   buff  cache   si   so    bi    bo   in   cs us sy id wa st\n"
        normal = " 1  0      0 800000  50000 200000    0    0     0     0  100  200  5  2 90  3  0\n"
        spike = " 1  0      0  40000  50000 200000    0    0     0     0  500 60000  5  2 40 50  0\n"
        content = header1 + header2 + normal + spike
        self._write("vmstat_metrics_2026-09-08_02-05-10.log", content)
        anomalies = self.parser.parse_anomalies(str(self.tmp_dir))
        self.assertEqual(len(anomalies["context_switch_spike"]), 1)
        self.assertEqual(len(anomalies["io_wait_spike"]), 1)
        self.assertEqual(len(anomalies["memory_pressure"]), 1)

    def test_top_zombie_and_cpu_anomaly(self):
        content = (
            "top - 02:05:10 up 1 day\n"
            "Tasks: 100 total\n"
            "  PID USER      PR  NI    VIRT    RES    SHR S  %CPU %MEM     TIME+ COMMAND\n"
            " 1234 root      20   0  100000  50000  10000 R  95.0  2.0   0:10.00 hog_process\n"
            " 5678 root      20   0   50000  20000   5000 Z   0.0  0.5   0:00.00 zombie_proc\n"
        )
        self._write("top_metrics_2026-09-08_02-05-10.log", content)
        anomalies = self.parser.parse_anomalies(str(self.tmp_dir))
        self.assertEqual(len(anomalies["process_cpu_anomalies"]), 1)
        self.assertEqual(anomalies["process_cpu_anomalies"][0]["pid"], "1234")
        self.assertEqual(len(anomalies["zombie_processes"]), 1)

    def test_top_memory_leak_detection(self):
        content = (
            " PID USER      PR  NI    VIRT    RES    SHR S  %CPU %MEM     TIME+ COMMAND\n"
            " 1000 root      20   0  100000  10000  10000 S   1.0  1.0   0:01.00 leaky_proc\n"
            " PID USER      PR  NI    VIRT    RES    SHR S  %CPU %MEM     TIME+ COMMAND\n"
            " 1000 root      20   0  100000  20000  10000 S   1.0  1.0   0:02.00 leaky_proc\n"
        )
        self._write("top_metrics_2026-09-08_02-05-10.log", content)
        anomalies = self.parser.parse_anomalies(str(self.tmp_dir))
        self.assertEqual(len(anomalies["process_memory_leak"]), 1)
        self.assertEqual(anomalies["process_memory_leak"][0]["growth_percent"], 100.0)

    def test_ftrace_scheduler_latency(self):
        # sched_wakeup at t=1.000000, sched_switch (next_pid matches) at t=1.010000
        # -> 10ms = 10000us latency, above default 5000us threshold
        content = (
            "          <idle>-0     [000] d..3  1.000000: sched_wakeup: comm=worker pid=999 prio=120\n"
            "          <idle>-0     [000] d..3  1.010000: sched_switch: prev_comm=idle prev_pid=0 prev_prio=120 prev_state=R ==> next_comm=worker next_pid=999 next_prio=120\n"
        )
        self._write("ftrace_metrics_2026-09-08_02-05-10.log", content)
        anomalies = self.parser.parse_anomalies(str(self.tmp_dir))
        self.assertEqual(len(anomalies["scheduler_latency_spikes"]), 1)
        self.assertAlmostEqual(anomalies["scheduler_latency_spikes"][0]["wakeup_to_switch_latency_us"], 10000.0, delta=1.0)

    def test_ftrace_missing_is_warning_only(self):
        anomalies = self.parser.parse_anomalies(str(self.tmp_dir))
        ftrace_warnings = [w for w in anomalies["warnings"] if "ftrace" in w]
        self.assertEqual(len(ftrace_warnings), 1)

    def test_custom_thresholds_applied(self):
        # Use a very low cpu_high_temp_c to force detection even at a lower reading
        custom_thresholds = {
            "thermal": {"cpu_high_temp_c": 30, "ddr_high_temp_c": 30},
        }
        parser = TelemetryParser(thresholds=custom_thresholds)
        content = (
            "timestamp,thermal_zone,type,temp_mC\n"
            "1000,thermal_zone0,cpu-0-thermal,40000\n"
        )
        self._write("thermal_metrics_2026-09-08_02-05-10.csv", content)
        anomalies = parser.parse_anomalies(str(self.tmp_dir))
        self.assertEqual(len(anomalies["thermal_high_temp"]), 1)


if __name__ == "__main__":
    unittest.main()
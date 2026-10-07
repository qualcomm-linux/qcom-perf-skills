"""
test_rca_detector.py - Unit tests for the enhanced RCADetector decision tree
(covering the new vmstat/top/ftrace-derived anomaly categories).

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.reporting.rca_detector import RCADetector


def _regression_result(tp_delta=0.0, lat_delta=0.0):
    return {
        "throughput_regression": tp_delta < 0,
        "latency_regression": lat_delta > 0,
        "metrics": {
            "throughput_delta_percent": tp_delta,
            "latency_delta_percent": lat_delta,
        },
    }


class TestRCADetector(unittest.TestCase):
    def test_thermal_throttling_detected(self):
        regression = _regression_result(tp_delta=-8.0)
        anomalies = {"thermal_throttles": [{"event": "cpu throttled"}]}
        result = RCADetector.apply_cot_logic("coremark_default", regression, anomalies)
        self.assertEqual(result["cause"], "DVFS / Thermal Throttling")
        self.assertEqual(result["confidence"], "92%")
        self.assertTrue(result["confidence_basis"])  # non-empty explanation

    def test_oom_kill_detected(self):
        regression = _regression_result(tp_delta=-10.0)
        anomalies = {"oom_kills": [{"event": "oom-kill"}]}
        result = RCADetector.apply_cot_logic("sysbench_fileio", regression, anomalies)
        self.assertEqual(result["cause"], "Severe Memory Pressure")

    def test_memory_pressure_without_oom(self):
        regression = _regression_result(tp_delta=-6.0)
        anomalies = {"memory_pressure": [{"sample": 1, "free_kb": 1000}]}
        result = RCADetector.apply_cot_logic("bw_mem_rd", regression, anomalies)
        self.assertEqual(result["cause"], "Memory Pressure (Low Free Memory / Possible Leak)")

    def test_io_wait_bottleneck(self):
        regression = _regression_result(tp_delta=-6.0)
        anomalies = {"io_wait_spike": [{"sample": 1, "io_wait_percent": 50}]}
        result = RCADetector.apply_cot_logic("tiobench_sequential", regression, anomalies)
        self.assertEqual(result["cause"], "I/O Bottleneck")

    def test_swap_activity_paging(self):
        regression = _regression_result(tp_delta=-6.0)
        anomalies = {"swap_activity_spike": [{"sample": 1, "swap_events_per_sec": 200000}]}
        result = RCADetector.apply_cot_logic("ramspeed_single", regression, anomalies)
        self.assertEqual(result["cause"], "Memory Pressure / Paging")

    def test_context_switch_scheduler_contention(self):
        regression = _regression_result(tp_delta=-6.0)
        anomalies = {"context_switch_spike": [{"sample": 1, "context_switches_per_sec": 80000}]}
        result = RCADetector.apply_cot_logic("hackbench_default", regression, anomalies)
        self.assertEqual(result["cause"], "Scheduler Contention")

    def test_task_migration_scheduler_contention(self):
        regression = _regression_result(tp_delta=-6.0)
        anomalies = {"task_migration_high": [{"migration_count": 800, "threshold": 500}]}
        result = RCADetector.apply_cot_logic("hackbench_default", regression, anomalies)
        self.assertEqual(result["cause"], "Scheduler Contention")

    def test_background_process_interference(self):
        regression = _regression_result(tp_delta=-6.0)
        anomalies = {"process_cpu_anomalies": [{"pid": "123", "command": "hog", "cpu_percent": 95.0}]}
        result = RCADetector.apply_cot_logic("coremark_default", regression, anomalies)
        self.assertEqual(result["cause"], "Background Process Interference")

    def test_ambiguous_cpu_bottleneck_no_evidence(self):
        regression = _regression_result(tp_delta=-6.0)
        anomalies = {}
        result = RCADetector.apply_cot_logic("coremark_default", regression, anomalies)
        self.assertEqual(result["cause"], "Ambiguous CPU/Storage Bottleneck")
        self.assertEqual(result["confidence"], "55%")

    def test_scheduler_latency_spike_for_latency_regression(self):
        regression = _regression_result(lat_delta=15.0)
        anomalies = {"scheduler_latency_spikes": [{"pid": "999", "wakeup_to_switch_latency_us": 12000.0}]}
        result = RCADetector.apply_cot_logic("sysbench_cpu", regression, anomalies)
        self.assertEqual(result["cause"], "Scheduler Latency / Preemption")
        self.assertEqual(result["confidence"], "88%")

    def test_thermal_induced_latency(self):
        regression = _regression_result(lat_delta=15.0)
        anomalies = {"thermal_high_temp": [{"event": "CPU Temperature Spike", "zone": "cpu0", "temp_c": 90.0}]}
        result = RCADetector.apply_cot_logic("sysbench_cpu", regression, anomalies)
        self.assertEqual(result["cause"], "Thermal-Induced Latency")

    def test_ambiguous_latency_no_evidence(self):
        regression = _regression_result(lat_delta=15.0)
        anomalies = {}
        result = RCADetector.apply_cot_logic("sysbench_cpu", regression, anomalies)
        self.assertEqual(result["cause"], "Ambiguous Latency Issue")

    def test_generate_rca_only_for_regressed_tests(self):
        regressions = {
            "test_a": _regression_result(tp_delta=-8.0),
            "test_b": {"throughput_regression": False, "latency_regression": False, "metrics": {}},
        }
        anomalies = {"thermal_throttles": [{"event": "x"}]}
        rca = RCADetector.generate_rca(regressions, anomalies)
        self.assertIn("test_a", rca)
        self.assertNotIn("test_b", rca)


if __name__ == "__main__":
    unittest.main()
"""
test_telemetry_thresholds.py - Unit tests for the telemetry_thresholds
loader used by the regression-detection-and-rca skill.

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / ".claude" / "skills" / "regression-detection-and-rca" / "scripts"))

import telemetry_thresholds


class TestTelemetryThresholds(unittest.TestCase):
    def test_resolves_active_device(self):
        config = {
            "active_device": "IQ-9075",
            "telemetry_thresholds": {
                "devices": {
                    "IQ-9075": {
                        "codename": "Lemans",
                        "thermal": {"cpu_high_temp_c": 85},
                    }
                }
            },
        }
        result = telemetry_thresholds.load_thresholds(config)
        self.assertEqual(result["codename"], "Lemans")
        self.assertEqual(result["thermal"]["cpu_high_temp_c"], 85)
        self.assertFalse(result["_used_fallback"])

    def test_backfills_missing_keys_from_fallback(self):
        config = {
            "active_device": "IQ-9075",
            "telemetry_thresholds": {
                "devices": {
                    "IQ-9075": {
                        "codename": "Lemans",
                        "thermal": {"cpu_high_temp_c": 85},
                        # vmstat/top/ftrace/memory intentionally omitted
                    }
                }
            },
        }
        result = telemetry_thresholds.load_thresholds(config)
        # Backfilled from FALLBACK_THRESHOLDS
        self.assertIn("vmstat", result)
        self.assertIn("context_switch_spike_per_sec", result["vmstat"])
        self.assertIn("top", result)
        self.assertIn("ftrace", result)

    def test_missing_config_section_uses_fallback(self):
        config = {}
        result = telemetry_thresholds.load_thresholds(config)
        self.assertTrue(result["_used_fallback"])
        self.assertEqual(result["codename"], "generic-fallback")

    def test_unknown_device_falls_back_to_first_defined(self):
        config = {
            "active_device": "NONEXISTENT-DEVICE",
            "telemetry_thresholds": {
                "devices": {
                    "IQ-9075": {"codename": "Lemans"}
                }
            },
        }
        result = telemetry_thresholds.load_thresholds(config)
        self.assertEqual(result["codename"], "Lemans")
        self.assertFalse(result["_used_fallback"])

    def test_device_override_parameter(self):
        config = {
            "active_device": "IQ-9075",
            "telemetry_thresholds": {
                "devices": {
                    "IQ-9075": {"codename": "Lemans"},
                    "OTHER-DEVICE": {"codename": "OtherCodename"},
                }
            },
        }
        result = telemetry_thresholds.load_thresholds(config, device_override="OTHER-DEVICE")
        self.assertEqual(result["codename"], "OtherCodename")


if __name__ == "__main__":
    unittest.main()
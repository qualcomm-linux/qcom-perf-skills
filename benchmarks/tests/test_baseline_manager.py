"""
test_baseline_manager.py - Unit tests for the baseline_manager module used
by the regression-detection-and-rca skill for explicit baseline storage.

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import sys
import tempfile
import shutil
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / ".claude" / "skills" / "regression-detection-and-rca" / "scripts"))

import baseline_manager


class TestBaselineManager(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_store_and_load_default_tag(self):
        stats = {"coremark_score": {"mean": 1000.0, "stddev": 10.0}}
        baseline_manager.store_baseline(self.tmp_dir, "coremark", "build_123", stats)
        loaded = baseline_manager.load_baseline(self.tmp_dir, "coremark")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["statistics"]["coremark_score"]["mean"], 1000.0)
        self.assertEqual(loaded["metadata"]["build_id"], "build_123")
        self.assertEqual(loaded["metadata"]["baseline_tag"], "default")

    def test_load_nonexistent_baseline_returns_none(self):
        result = baseline_manager.load_baseline(self.tmp_dir, "nonexistent_benchmark")
        self.assertIsNone(result)

    def test_named_tag_isolation(self):
        stats_a = {"metric": {"mean": 1.0}}
        stats_b = {"metric": {"mean": 2.0}}
        baseline_manager.store_baseline(self.tmp_dir, "coremark", "build_a", stats_a, tag="pre-fix")
        baseline_manager.store_baseline(self.tmp_dir, "coremark", "build_b", stats_b, tag="post-fix")

        loaded_a = baseline_manager.load_baseline(self.tmp_dir, "coremark", tag="pre-fix")
        loaded_b = baseline_manager.load_baseline(self.tmp_dir, "coremark", tag="post-fix")

        self.assertEqual(loaded_a["statistics"]["metric"]["mean"], 1.0)
        self.assertEqual(loaded_b["statistics"]["metric"]["mean"], 2.0)

    def test_list_baselines(self):
        baseline_manager.store_baseline(self.tmp_dir, "coremark", "b1", {}, tag="default")
        baseline_manager.store_baseline(self.tmp_dir, "sysbench", "b2", {}, tag="default")
        listing = baseline_manager.list_baselines(self.tmp_dir)
        self.assertEqual(len(listing), 2)

    def test_delete_baseline(self):
        baseline_manager.store_baseline(self.tmp_dir, "coremark", "b1", {})
        self.assertTrue(baseline_manager.delete_baseline(self.tmp_dir, "coremark"))
        self.assertIsNone(baseline_manager.load_baseline(self.tmp_dir, "coremark"))
        # Deleting again returns False (nothing to delete)
        self.assertFalse(baseline_manager.delete_baseline(self.tmp_dir, "coremark"))

    def test_overwrite_existing_baseline(self):
        baseline_manager.store_baseline(self.tmp_dir, "coremark", "b1", {"metric": {"mean": 1.0}})
        baseline_manager.store_baseline(self.tmp_dir, "coremark", "b2", {"metric": {"mean": 2.0}})
        loaded = baseline_manager.load_baseline(self.tmp_dir, "coremark")
        self.assertEqual(loaded["statistics"]["metric"]["mean"], 2.0)
        self.assertEqual(loaded["metadata"]["build_id"], "b2")


if __name__ == "__main__":
    unittest.main()
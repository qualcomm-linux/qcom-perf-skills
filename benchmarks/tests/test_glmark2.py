"""
test_glmark2.py - Regression test for findings #7 and #11: glmark2.py's
unified run() must flatten per-scene FPS data into distinct "tests" entries
(reusing the generic aggregator "tests" fallback), the same scene-flattening
_glmark2_base.py's now-deleted execute_lifecycle() used to perform before it
became dead code.

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.benchmark.glmark2 import GLMark2Benchmark

_TWO_SCENE_OUTPUT = (
    "[ideas] speed=duration: FPS: 1793 FrameTime: 0.558 ms\n"
    "[terrain] speed=duration: FPS: 450 FrameTime: 2.222 ms\n"
    "glmark2 Score: 3200\n"
)


class TestGLMark2SceneFlattening(unittest.TestCase):
    def setUp(self):
        self.run_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.run_dir, ignore_errors=True)

    def test_scenes_are_flattened_into_distinct_metrics(self):
        config = {
            "test_params": {
                "glmark2_default": {
                    "command": "/usr/bin/glmark2-es2-wayland",
                    "config_file": "src/configs/benchmarks_glmark2.txt",
                }
            },
            "tests": ["glmark2_default"],
        }
        bench = GLMark2Benchmark("glmark2", config, self.run_dir)

        mock_executor = MagicMock()
        mock_executor.execute_command.return_value = _TWO_SCENE_OUTPUT

        mock_adb = MagicMock()
        mock_adb.get_build_id.return_value = "build123"
        mock_adb.push_file.return_value = None

        with patch("src.benchmark.glmark2.time.sleep"):
            results = bench.run(mock_executor, mock_adb)

        self.assertIn("glmark2_default", results["tests"])
        self.assertIn("glmark2_default_ideas_speed_duration", results["tests"])
        self.assertIn("glmark2_default_terrain_speed_duration", results["tests"])

        self.assertEqual(
            results["tests"]["glmark2_default_ideas_speed_duration"]["throughput"], [1793]
        )
        self.assertEqual(
            results["tests"]["glmark2_default_terrain_speed_duration"]["throughput"], [450]
        )


if __name__ == "__main__":
    unittest.main()

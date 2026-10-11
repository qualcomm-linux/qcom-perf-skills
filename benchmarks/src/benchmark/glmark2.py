"""
glmark2.py - Unified GLMark2 Benchmark
Orchestrates multiple GLMark2 sub-tests (default, 1920x1080, offscreen, etc.)

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import time
from pathlib import Path
from typing import Any, Dict

from src.benchmark.base import BenchmarkBase
from src.benchmark._glmark2_base import Glmark2BenchmarkBase
from src.utils.logger import phase_logger
from src.utils.telemetry_helpers import setup_telemetry, teardown_telemetry

class GLMark2Benchmark(BenchmarkBase):
    """Unified benchmark class that runs all configured glmark2 tests."""
    
    def __init__(self, name: str, config: Dict[str, Any], run_dir: Path):
        super().__init__(name, config, run_dir)
        self.iterations = 1
        self.telemetry_timestamp = ""
        
    def setup(self, serial_executor, adb_manager) -> None:
        phase_logger.info("Setting up GLMark2 benchmark on device...")
        if self.config.get('collect_telemetry', False):
            self.telemetry_timestamp = setup_telemetry(adb_manager)
        
    def run(self, serial_executor, adb_manager) -> Dict[str, Any]:
        phase_logger.info(f"Running Unified GLMark2 benchmark suite...")
        
        # Determine which sub-tests to run based on config
        test_params = self.config.get("test_params", {})
        tests_to_run = self.config.get("tests", list(test_params.keys()))
        
        if not tests_to_run:
            phase_logger.warning("No tests configured for glmark2.")
            return {"metadata": {}, "tests": {}}
            
        combined_results = {
            "metadata": {
                "benchmark": "glmark2",
                "timestamp_utc": time.strftime("%Y-%m-%d %H:%M:%S"),
                "os_build_id": adb_manager.get_build_id() if adb_manager else "unknown",
                "os_pretty_name": adb_manager.get_pretty_name() if adb_manager and hasattr(adb_manager, "get_pretty_name") else "Linux",
                "iterations_run": self.iterations
            },
            "system_info": {},
            "tests": {}
        }
        
        for test_name in tests_to_run:
            phase_logger.info(f"--- Running GLMark2 Test: {test_name} ---")
            sub_config = test_params.get(test_name, {})
            
            # Use the base class logic to run the specific test
            runner = Glmark2BenchmarkBase(test_name, sub_config, self.run_dir)
            
            # Execute it directly
            try:
                # Capture raw output
                runner.serial = serial_executor
                remote_config_path = f"/root/{Path(runner.config_file).name}"
                
                if adb_manager:
                    adb_manager.push_file(runner.config_file, remote_config_path)
                    
                cmd = runner.command_base
                if runner.config.get("size"):
                    cmd += f" --size {runner.config.get('size')}"
                if runner.config.get("offscreen"):
                    cmd += " --off-screen"
                cmd += f" -f {remote_config_path}"
                
                phase_logger.info(f"[glmark2] Running {test_name}: {cmd}")
                raw_output = runner.serial.execute_command(cmd, timeout_override=0)
                
                # Save raw output to individual file
                logs_dir = self.run_dir / "logs"
                logs_dir.mkdir(parents=True, exist_ok=True)
                with open(logs_dir / f"{test_name}_output.txt", "w", encoding="utf-8") as f:
                    f.write(raw_output)
                    
                # Parse and merge
                parsed_data = runner._parse_output(raw_output)
                phase_logger.info(f"[glmark2] Result {test_name}: Score={parsed_data['score']}")
                
                # Only need to set system_info once since it's the same device
                if not combined_results["system_info"] and parsed_data.get("system_info"):
                    combined_results["system_info"] = parsed_data["system_info"]
                    
                combined_results["tests"][test_name] = {
                    "category": "graphics",
                    "score": parsed_data["score"],
                    "scenes": parsed_data["scenes"],
                    "throughput": [parsed_data["score"]]
                }

                # Flatten scenes for aggregator compatibility (helps with charting)
                for scene_name, metrics in parsed_data["scenes"].items():
                    safe_scene_name = scene_name.replace(" ", "_").replace("=", "_").replace("[", "").replace("]", "")
                    combined_results["tests"][f"{test_name}_{safe_scene_name}"] = {
                        "category": "graphics",
                        "throughput": [metrics["fps"]]
                    }

                # Sleep a bit between tests
                time.sleep(2)
                
            except Exception as e:
                phase_logger.error(f"Failed to run glmark2 test '{test_name}': {e}")
                
        return combined_results
        
    def teardown(self, serial_executor, adb_manager) -> None:
        teardown_telemetry(adb_manager, self.run_dir, self.telemetry_timestamp)

BENCHMARK_CLASS = GLMark2Benchmark

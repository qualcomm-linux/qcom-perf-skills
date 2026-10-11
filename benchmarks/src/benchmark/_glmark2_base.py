"""
_glmark2_base.py - Base class for glmark2 benchmarks

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import re
from typing import Any, Dict
from pathlib import Path

class Glmark2BenchmarkBase:
    """Base class for GLMark2 benchmark variants"""

    def __init__(self, name: str, config: Dict[str, Any], run_dir: Path):
        self.name = name
        self.config = config
        self.run_dir = run_dir
        self.command_base = self.config.get("command", "/usr/bin/glmark2-es2-wayland")
        self.config_file = self.config.get("config_file", "")
        # glmark2 default iteration = 1, no warmup
        self.iterations = 1 
        
    def _parse_output(self, output: str) -> Dict[str, Any]:
        """
        Parses glmark2 output.
        """
        parsed = {
            "score": 0,
            "system_info": {
                "driver_version": "Unknown",
                "opengl_version": "Unknown",
                "gpu_details": "Unknown"
            },
            "scenes": {}
        }
        
        for line in output.splitlines():
            line = line.strip()
            
            # System info parsing
            if line.startswith("Driver Version"):
                match = re.search(r'Driver Version\s*:\s*(.+)', line)
                if match:
                    parsed["system_info"]["driver_version"] = match.group(1).strip()
            elif line.startswith("GL_VERSION:"):
                match = re.search(r'GL_VERSION:\s*(.+)', line)
                if match:
                    parsed["system_info"]["opengl_version"] = match.group(1).strip()
            elif line.startswith("GL_RENDERER:"):
                match = re.search(r'GL_RENDERER:\s*(.+)', line)
                if match:
                    parsed["system_info"]["gpu_details"] = match.group(1).strip()
                    
            # Scene parsing
            # [ideas] speed=duration: FPS: 1793 FrameTime: 0.558 ms
            scene_match = re.search(r'^(\[.*?\].*?):\s*FPS:\s*(\d+)\s*FrameTime:\s*([\d.]+)\s*ms', line)
            if scene_match:
                scene_name = scene_match.group(1).strip()
                fps = int(scene_match.group(2))
                frametime = float(scene_match.group(3))
                parsed["scenes"][scene_name] = {
                    "fps": fps,
                    "frametime_ms": frametime
                }
                
            # Score parsing
            # glmark2 Score: 3200
            score_match = re.search(r'glmark2 Score:\s*(\d+)', line)
            if score_match:
                parsed["score"] = int(score_match.group(1))
                
        return parsed
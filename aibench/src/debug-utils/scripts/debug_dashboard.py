#!/usr/bin/env python3
"""
Debug dashboard generation to see what's being loaded
"""
import sys
import json
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

output_dir = Path("output")

print("Checking benchmark directories...")
for bench_dir in output_dir.iterdir():
    if not bench_dir.is_dir() or bench_dir.name == "reports":
        continue
    
    print(f"\n📁 Found benchmark: {bench_dir.name}")
    
    # Get build folders
    build_dirs = sorted([d for d in bench_dir.glob("build_*") if d.is_dir()], key=lambda x: x.stat().st_mtime)
    print(f"   Build directories: {len(build_dirs)}")
    
    for b_dir in build_dirs:
        print(f"   📂 {b_dir.name}")
        analysis_file = b_dir / "build_analysis.json"
        
        if analysis_file.exists():
            with open(analysis_file, "r") as f:
                data = json.load(f)
            stats = data.get("statistics", {})
            print(f"      ✅ build_analysis.json found")
            print(f"      📊 Statistics keys: {list(stats.keys())}")
            for key, val in list(stats.items())[:3]:
                print(f"         - {key}: mean={val.get('mean', 0):.1f}")
        else:
            print(f"      ❌ build_analysis.json NOT found")
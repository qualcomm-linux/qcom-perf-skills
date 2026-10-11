#!/usr/bin/env python3
"""
Regenerate index.html dashboard with updated chart data
"""
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from main import render_dashboard
from src.utils.config_loader import load_yaml_config

# Load config
config_path = Path("config/benchmarks.yaml")
config = load_yaml_config(config_path)

# Set paths
output_dir = Path("output")
template_path = Path("config/templates/summary_dashboard.html")

print("Regenerating index.html dashboard...")
render_dashboard(output_dir, template_path, config, skipped_benchmarks=[])
print("✅ Dashboard regenerated successfully!")
print(f"📊 View at: {output_dir / 'reports' / 'index.html'}")
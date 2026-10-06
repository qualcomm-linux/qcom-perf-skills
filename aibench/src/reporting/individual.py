"""
individual.py - Generate run-specific JSON and HTML reports.

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import json
from pathlib import Path
from typing import Any, Dict
from src.utils.logger import phase_logger

try:
    from jinja2 import Environment, FileSystemLoader
    _JINJA_AVAILABLE = True
except ImportError:
    _JINJA_AVAILABLE = False

def write_json_results(results: Dict[str, Any], run_dir: Path) -> Path:
    """Writes the raw/parsed benchmark results to results.json."""
    output_file = Path(run_dir) / "results.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    phase_logger.info(f"JSON results saved to {output_file}")
    return output_file

def generate_individual_html_report(results: Dict[str, Any], run_dir: Path, template_path: Path) -> Path:
    """
    Renders a self-contained HTML report for an individual run.
    Uses Jinja2 if available, otherwise falls back to a clean text-replacement renderer.

    If a rca_report.json exists in run_dir (written by the
    regression-detection-and-rca skill, typically AFTER this function has
    already run once during the normal lifecycle), it is loaded and passed
    to the template as `rca_report` so regressed benchmarks/metrics can be
    highlighted with evidence/root-cause/recommendation. If absent, templates
    should treat `rca_report` as None/falsy and skip that section.
    """
    output_file = Path(run_dir) / "report.html"
    
    metadata = results.get("metadata", {})
    # Handle variations in metadata keys between benchmarks
    benchmark_name = metadata.get("benchmark_name") or metadata.get("benchmark", "unknown")

    rca_report = None
    rca_report_path = Path(run_dir) / "rca_report.json"
    if rca_report_path.exists():
        try:
            with open(rca_report_path, "r", encoding="utf-8") as rf:
                rca_report = json.load(rf)
        except Exception as e:
            phase_logger.warning(f"Failed to load rca_report.json for HTML rendering: {e}")

    if _JINJA_AVAILABLE and template_path.exists():
        try:
            env = Environment(loader=FileSystemLoader(template_path.parent))
            template = env.get_template(template_path.name)
            html_content = template.render(
                results=results, metadata=metadata, benchmark_name=benchmark_name,
                rca_report=rca_report
            )
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(html_content)
            phase_logger.info(f"HTML report successfully rendered via Jinja2: {output_file}")
            return output_file
        except Exception as e:
            phase_logger.warning(f"Failed to render via Jinja2 ({e}). Falling back to simple renderer.")
            
    # Fallback/simple text replacement html
    fallback_html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Benchmark Report: {benchmark_name.upper()}</title>
    <style>
        body {{ font-family: 'Segoe UI', sans-serif; margin: 30px; background-color: #f8f9fa; }}
        .container {{ background: #fff; padding: 25px; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }}
        h1 {{ color: #2c3e50; border-bottom: 2px solid #e67e22; padding-bottom: 10px; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
        th, td {{ padding: 12px; border: 1px solid #ddd; text-align: left; }}
        th {{ background-color: #f1f2f6; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>{benchmark_name.upper()} Benchmark Run Report</h1>
        <p><strong>Timestamp:</strong> {metadata.get('timestamp_utc', 'N/A')}</p>
        <p><strong>Build ID:</strong> {metadata.get('os_build_id', 'N/A')}</p>
        <p><strong>OS Name:</strong> {metadata.get('os_pretty_name', 'N/A')}</p>
        <p><strong>Iterations Run:</strong> {metadata.get('iterations_run', 'N/A')}</p>
        
        <h2>Results Summary</h2>
        <pre>{json.dumps(results.get('result', results.get('tests', results)), indent=2)}</pre>
    </div>
</body>
</html>"""
    
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(fallback_html)
    phase_logger.info(f"Fallback HTML report saved: {output_file}")
    return output_file
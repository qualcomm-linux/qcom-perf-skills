#!/usr/bin/env python3
"""
main.py - Unified Benchmark Harness Entrypoint
Orchestrates setup, benchmark lifecycles, sequential execution constraints,
and tier-based reporting.

Author: Sarbojit Ganguly <sarbgang@qti.qualcomm.com>
"""

import os
import sys
import argparse
import time
import json
import webbrowser
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any

# Ensure we can import from src/
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.utils.logger import phase_logger
from src.utils.config_loader import load_yaml_config
from src.utils.timestamp_utils import generate_run_name
from src.utils.lifecycle import validate_and_enforce_gap, GapValidationError
from src.utils.serial_connect import open_serial_connection, handle_login, close_connection, send_cmd
from src.utils.serial_executor import SerialCommandExecutor, print_nproc
from src.utils.adb_manager import AdbManager
from src.utils.device_info_collector import collect_device_info
from src.utils.device_history import DeviceHistoryManager

from src.benchmark.factory import get_benchmark
from src.reporting.individual import write_json_results, generate_individual_html_report
from src.reporting.aggregator import aggregate_build_runs
from src.reporting.regression_detector import RegressionDetector
from src.reporting.chart_generator import generate_chart_js_data
from src.reporting.telemetry_parser import TelemetryParser
from src.reporting.rca_detector import RCADetector
from src.reporting.excel_generator import generate_excel_report as _generate_excel_report

# regression-detection-and-rca skill (scripts/ folder under .claude/skills/)
_RCA_SKILL_SCRIPTS = Path(__file__).resolve().parent / ".claude" / "skills" / "regression-detection-and-rca" / "scripts"
if str(_RCA_SKILL_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_RCA_SKILL_SCRIPTS))
try:
    from run_rca import run_rca_for_run
    import baseline_manager
    import metrics_extractor
    _RCA_SKILL_AVAILABLE = True
except ImportError as _rca_import_exc:
    _RCA_SKILL_AVAILABLE = False
    phase_logger.warning(f"regression-detection-and-rca skill unavailable (import failed: {_rca_import_exc}). Automatic RCA will be skipped.")

try:
    from jinja2 import Environment, FileSystemLoader
    _JINJA_AVAILABLE = True
except ImportError:
    _JINJA_AVAILABLE = False

def parse_unknown_args(unknown_args: List[str]) -> Dict[str, str]:
    overrides = {}
    i = 0
    while i < len(unknown_args):
        arg = unknown_args[i]
        if arg.startswith("-"):
            if "=" in arg:
                key, val = arg.split("=", 1)
                overrides[key] = val
            else:
                key = arg
                # Check if next element is a value and doesn't start with "-"
                if i + 1 < len(unknown_args) and not unknown_args[i + 1].startswith("-"):
                    overrides[key] = unknown_args[i + 1]
                    i += 1
                else:
                    overrides[key] = "true"  # flag argument
        i += 1
    return overrides

def parse_args():
    help_desc = (
        "Unified Benchmark Harness\n\n"
        "This harness orchestrates benchmark execution on target devices. You can trigger\n"
        "entire benchmark suites or target individual sub-tests using --tests. It supports custom\n"
        "iterations, execution modes (ADB/Serial or SSH), and dynamic parameter overrides.\n\n"
        "Examples:\n"
        "  1. Run all active benchmarks over ADB/Serial (default):\n"
        "     python main.py\n"
        "  2. Run single benchmark over SSH:\n"
        "     python main.py -b sysbench --ssh-connection\n"
        "  3. Run multiple benchmarks (comma-separated):\n"
        "     python main.py -b hackbench,sysbench,coremark --ssh-connection\n"
        "  4. Run only specific sysbench tests over SSH:\n"
        "     python main.py -b sysbench -t sysbench_cpu_prime_single_test sysbench_memory_random_read --ssh-connection\n"
        "  5. Dynamically override any sysbench parameter for an AI Agent:\n"
        "     python main.py -b sysbench -t sysbench_cpu_prime_multi_test --time=10 --threads=4 --ssh-connection\n"
        "  6. Run sequential tiobench over SSH with 5 iterations:\n"
        "     python main.py -b tiobench -t sequential -r 5 --ssh-connection\n"
        "  7. Run all active benchmarks EXCEPT unixbench and hackbench:\n"
        "     python main.py --skip unixbench,hackbench\n"
    )
    
    parser = argparse.ArgumentParser(
        description=help_desc,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--benchmark", "-b",
        type=str,
        default=None,
        help="Name of the benchmark to run (e.g. coremark, sysbench, tiobench) or comma-separated list of multiple benchmarks. If omitted, runs all active benchmarks."
    )
    parser.add_argument(
        "--build-id", "-i",
        type=str,
        default=None,
        help="Identifier for the build being tested. Auto-detected from device via ADB if omitted."
    )
    parser.add_argument(
        "--runs", "-r",
        type=int,
        default=None,
        help="Overrides number of runs for the benchmark suite (default: 1)."
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=None,
        help="Overrides number of iterations for each individual sub-benchmark test (default: 3)."
    )
    parser.add_argument(
        "--config", "-c",
        type=str,
        default="config/benchmarks.yaml",
        help="Path to benchmarks.yaml config file."
    )
    parser.add_argument(
        "--bypass-gap",
        action="store_true",
        help="Bypasses the 5-minute sequential execution gap constraint."
    )
    parser.add_argument(
        "--default-connection",
        action="store_true",
        help="Activate default mode: logs/telemetry via ADB and benchmarks over Serial."
    )
    parser.add_argument(
        "--ssh-connection",
        action="store_true",
        help="Activate SSH mode: perform all activities via SSH."
    )
    parser.add_argument(
        "--host",
        type=str,
        default=None,
        help="Target device IP/hostname for SSH mode (loaded from config/credentials.yaml)."
    )
    parser.add_argument(
        "--tests", "--test", "-t",
        type=str,
        nargs="+",
        default=None,
        dest="tests",
        help=(
            "Space-separated list of individual sub-tests or test types to execute. For e.g. 'sysbench',\n"
            ", sysbench_cpu_prime_single_test, sysbench_fileio_seq_write_test, etc. For e.g.\n"
            "'tiobench', , sequential, random."
        )
    )
    parser.add_argument(
        "--skip",
        type=str,
        default=None,
        help="Name of the benchmark to skip or comma-separated list of multiple benchmarks to skip."
    )
    parser.add_argument(
        "--store-baseline",
        action="store_true",
        help="After this run completes, store its aggregated build statistics as the regression-detection-and-rca baseline for each benchmark run (see --baseline-tag). Use this on a known-good build before flashing a new one."
    )
    parser.add_argument(
        "--baseline-tag",
        type=str,
        default=None,
        help="Named baseline slot to store to (with --store-baseline) or compare against (default RCA comparisons always check the 'default' tag unless overridden here)."
    )
    parser.add_argument(
        "--rca-all-runs",
        action="store_true",
        help="Force RCA to use ALL runs (not just last 3) for regression detection."
    )
    parser.add_argument(
        "--rca-all-iterations",
        action="store_true",
        help="Force RCA to use ALL iterations (not just last 3) for regression detection."
    )
    parser.add_argument(
        "--smart-rca",
        action="store_true",
        help="Default mode. Performs regression detection, then 2-tier RCA ONLY on regressed benchmarks."
    )
    parser.add_argument(
        "--full-rca",
        action="store_true",
        help="Run benchmarks, perform regression detection, and run RCA on ALL benchmarks."
    )
    parser.add_argument(
        "--report-mode",
        action="store_true",
        help="(Deprecated) Run benchmarks and perform regression detection without root-cause analysis (RCA)."
    )
    parser.add_argument(
        "--rca-mode",
        action="store_true",
        help="(Deprecated) Use --full-rca instead. Run benchmarks, perform regression detection, and run full root-cause analysis (RCA)."
    )
    parser.add_argument(
        "--collect-telemetry",
        action="store_true",
        help="Enable device telemetry collection during benchmarks (optional in full-rca, handled automatically in smart-rca)."
    )
    parser.add_argument(
        "--rca-use-ai",
        action="store_true",
        help="Route regression detection and RCA through the AI-driven Chain-of-Thought skills (via the local 'claude' CLI) before falling back to the deterministic Python engine on any failure. Default: Python engine only."
    )
    args, unknown = parser.parse_known_args()
    
    # Auto-add --ssh-connection if --host is provided without it
    if args.host and not args.ssh_connection and not args.default_connection:
        phase_logger.info("--host provided without --ssh-connection, automatically enabling SSH mode")
        args.ssh_connection = True
    
    if args.default_connection and args.ssh_connection:
        parser.error("Cannot specify both --default-connection and --ssh-connection simultaneously.")
        
    # Handle deprecated flags
    if args.report_mode:
        phase_logger.warning("Warning: --report-mode is deprecated. Smart RCA now runs efficiently by default.")
    if args.rca_mode:
        phase_logger.warning("Warning: --rca-mode is deprecated. Use --full-rca if you need telemetry for all benchmarks.")
        args.full_rca = True

    # Count mutually exclusive modes
    modes_selected = sum(1 for m in [args.smart_rca, args.full_rca, args.report_mode] if m)
    if modes_selected > 1:
        parser.error("Cannot specify multiple RCA modes simultaneously (--smart-rca, --full-rca, --report-mode).")
        
    # Default to smart-rca if nothing is specified
    if modes_selected == 0:
        args.smart_rca = True
        
    # Disable telemetry if in report-mode
    args._telemetry_conflict = False
    if args.report_mode and args.collect_telemetry:
        phase_logger.warning("Warning: --collect-telemetry was requested but is disabled in --report-mode. Telemetry will NOT be collected.")
        args.collect_telemetry = False
        args._telemetry_conflict = True
    
    # Handle manual overriding of runs and iterations if they were accidentally captured as unknown 
    filtered_unknown = []
    i = 0
    while i < len(unknown):
        arg = unknown[i]
        if arg.startswith("--runs="):
            args.runs = int(arg.split("=")[1])
        elif arg == "--runs" and i + 1 < len(unknown) and not unknown[i + 1].startswith("-"):
            args.runs = int(unknown[i + 1])
            i += 1
        elif arg.startswith("--iterations=") or arg.startswith("--iteration="):
            args.iterations = int(arg.split("=")[1])
        elif (arg == "--iterations" or arg == "--iteration") and i + 1 < len(unknown) and not unknown[i + 1].startswith("-"):
            args.iterations = int(unknown[i + 1])
            i += 1
        else:
            filtered_unknown.append(arg)
        i += 1
            
    args.unknown_args = filtered_unknown
    
    # Process comma-separated benchmarks
    if args.benchmark:
        args.benchmarks = [b.strip() for b in args.benchmark.split(",")]
    else:
        args.benchmarks = None
        
    # Process comma-separated skip list
    if args.skip:
        args.skip = [s.strip() for s in args.skip.split(",")]
    else:
        args.skip = []
        
    # Process comma-separated tests
    if args.tests:
        processed_tests = []
        for test_group in args.tests:
            if not test_group.strip():
                continue
            for t in test_group.split(","):
                stripped = t.strip()
                if stripped:
                    processed_tests.append(stripped)
        args.tests = processed_tests if processed_tests else None
        
    return args

def render_dashboard(output_dir: Path, template_path: Path, config: Dict[str, Any], skipped_benchmarks: List[Dict[str, str]] = None):
    """Renders the summary dashboard showing aggregated history and charts based on smart comparison logic."""
    reports_dir = output_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    
    regression_detector = RegressionDetector()
    telemetry_parser = TelemetryParser()
    
    benchmarks_data = []
    
    # NEW: Load RCA reports for all runs to pass to dashboard
    rca_reports = {}
    
    if output_dir.exists():
        for bench_dir in output_dir.iterdir():
            if not bench_dir.is_dir() or bench_dir.name == "reports":
                continue
                
            bench_name = bench_dir.name
            # Get build folders sorted by modification time
            build_dirs = sorted([d for d in bench_dir.glob("build_*") if d.is_dir()], key=os.path.getmtime)
            
            if not build_dirs:
                continue
                
            # Load RCA reports
            for b_dir in build_dirs:
                for run_dir in b_dir.glob("run_*"):
                    if not run_dir.is_dir():
                        continue
                    rca_file = run_dir / "rca_report.json"
                    if rca_file.exists():
                        try:
                            with open(rca_file, "r") as f:
                                rca_reports[run_dir.name] = json.load(f)
                        except Exception as e:
                            phase_logger.error(f"Failed to load RCA report from {rca_file}: {e}")
                
            benchmark_info = {
                "name": bench_name,
                "comparison_type": None,
                "history": [],
                "chart_data": {}
            }
            
            if len(build_dirs) > 1:
                benchmark_info["comparison_type"] = "build-over-build"
                # If more than 3, pick latest 3
                latest_builds = build_dirs[-3:]
                
                for b_dir in latest_builds:
                    analysis_file = b_dir / "build_analysis.json"
                    if analysis_file.exists():
                        try:
                            with open(analysis_file, "r") as f:
                                data = json.load(f)
                                
                            anomalies = {}
                            runs = sorted([d for d in b_dir.glob("run_*") if d.is_dir()])
                            if runs:
                                latest_run_logs = runs[-1] / "logs"
                                if latest_run_logs.exists():
                                    anomalies = telemetry_parser.parse_anomalies(str(latest_run_logs))
                                    
                            stats = data.get("statistics", {})
                                
                            # Manually calculate total_time_sec from the latest run's results.json if it doesn't exist
                            if bench_name == "sysbench":
                                latest_run = runs[-1] if runs else None
                                if latest_run:
                                    res_file = latest_run / "results.json"
                                    if res_file.exists():
                                        try:
                                            with open(res_file, "r") as rf:
                                                rdata = json.load(rf)
                                                for tname, tdata in rdata.get("tests", {}).items():
                                                    time_key = f"{tname}_total_time_sec"
                                                    if time_key not in stats and "iterations" in tdata:
                                                        times = [it.get("total_time_sec") for it in tdata["iterations"] if it.get("total_time_sec") is not None]
                                                        if times:
                                                            stats[time_key] = {"mean": sum(times) / len(times), "cv": 0}
                                        except Exception:
                                            pass
                                            
                            entry = {
                                "id": b_dir.name.replace("build_", ""),
                                "date": data.get("metadata", {}).get("aggregated_at", "N/A"),
                                "runs_count": data.get("metadata", {}).get("total_runs_aggregated", 1),
                                "statistics": stats,
                                "anomalies": anomalies,
                                "rca": {},
                                "regressions": {}
                            }
                            benchmark_info["history"].append(entry)
                        except Exception as e:
                            phase_logger.error(f"Failed to read {analysis_file}: {e}")
                            
            else:
                b_dir = build_dirs[0]
                benchmark_info["build_id"] = b_dir.name.replace("build_", "")
                run_dirs = sorted([d for d in b_dir.glob("run_*") if d.is_dir()], key=os.path.getmtime)
                
                if len(run_dirs) > 1:
                    benchmark_info["comparison_type"] = "run-over-run"
                    
                    # Filter out RCA re-run directories (run_*.1, run_*.2) before counting/displaying
                    base_run_dirs = [d for d in run_dirs if d.name.startswith("run_") and not d.name.endswith(".1") and not d.name.endswith(".2")]
                    
                    # If we only have 1 base run after filtering, treat as single run
                    if len(base_run_dirs) <= 1:
                        if base_run_dirs:
                            run_dirs = base_run_dirs
                        # Fall through to the len(run_dirs) == 1 case logic below
                        # But we can't easily change control flow here without refactoring the whole block
                        # So we'll just continue processing it as run-over-run but it will only have 1 column
                        pass
                        
                    latest_runs = base_run_dirs[-3:] if base_run_dirs else []
                    
                    for i, r_dir in enumerate(latest_runs):
                        results_file = r_dir / "results.json"
                        if results_file.exists():
                            try:
                                with open(results_file, "r") as f:
                                    data = json.load(f)
                                stats = {}
                                
                                b_name = data.get("metadata", {}).get("benchmark_name", "")
                                if b_name == "tiobench":
                                    for key, val in data.items():
                                        if key == "metadata": continue
                                        if isinstance(val, dict) and "average_bandwidth" in val:
                                            w_rate = val["average_bandwidth"].get("write_rate_mbs", 0.0)
                                            stats[f"{key}_write_rate"] = {"mean": w_rate, "cv": 0}
                                            r_rate = val["average_bandwidth"].get("read_rate_mbs", 0.0)
                                            stats[f"{key}_read_rate"] = {"mean": r_rate, "cv": 0}
                                elif b_name == "unixbench":
                                    tests_data = data.get("tests", {})
                                    if "unixbench_single_core" in tests_data:
                                        stats["unixbench_single_core"] = {"mean": tests_data["unixbench_single_core"].get("metrics", {}).get("index_score", 0.0), "cv": 0}
                                    if "unixbench_multi_core" in tests_data:
                                        stats["unixbench_multi_core"] = {"mean": tests_data["unixbench_multi_core"].get("metrics", {}).get("index_score", 0.0), "cv": 0}
                                    if "unixbench_scaling" in tests_data:
                                        tp = tests_data["unixbench_scaling"].get("throughput", [])
                                        if tp:
                                            stats["unixbench_scaling"] = {"mean": sum(tp) / len(tp), "cv": 0}
                                elif b_name == "bw_mem":
                                    tests_data = data.get("tests", {})
                                    for iter_key, iter_data in tests_data.items():
                                        if isinstance(iter_data, dict):
                                            for op, op_data in iter_data.items():
                                                if isinstance(op_data, dict) and "plateau" in op_data:
                                                    plateau_val = op_data.get("plateau")
                                                    if plateau_val is not None:
                                                        stats[f"bw_mem_{op}_plateau"] = {"mean": plateau_val, "cv": 0}
                                                    peak_val = op_data.get("plateau_analysis", {}).get("peak_observed")
                                                    if peak_val is not None:
                                                        stats[f"bw_mem_{op}_peak_observed"] = {"mean": peak_val, "cv": 0}
                                elif b_name == "lat_mem_rd":
                                    tests_data = data.get("tests", {})
                                    for test_name, test_data in tests_data.items():
                                        if not isinstance(test_data, dict):
                                            continue
                                        overall_plateau = test_data.get("overall_plateau_latency_ns")
                                        if overall_plateau is not None:
                                            stats[f"{test_name}_overall_plateau_ns"] = {"mean": overall_plateau, "cv": 0}
                                        spread_pct = test_data.get("iteration_to_iteration_spread_pct")
                                        if spread_pct is not None:
                                            stats[f"{test_name}_iter_spread_pct"] = {"mean": spread_pct, "cv": 0}
                                elif b_name == "geekbench":
                                    # Geekbench uses single_core_scores / multi_core_scores arrays.
                                    # Store as geekbench_cpu_single_core / geekbench_cpu_multi_core
                                    # to match the dashboard template's table_config keys.
                                    tests_data = data.get("tests", {})
                                    sc_all, mc_all = [], []
                                    for test_name, test_data in tests_data.items():
                                        if not isinstance(test_data, dict):
                                            continue
                                        sc_all.extend([s for s in test_data.get("single_core_scores", []) if s is not None])
                                        mc_all.extend([s for s in test_data.get("multi_core_scores", []) if s is not None])
                                    if sc_all:
                                        stats["geekbench_cpu_single_core"] = {"mean": sum(sc_all) / len(sc_all), "cv": 0}
                                    if mc_all:
                                        stats["geekbench_cpu_multi_core"] = {"mean": sum(mc_all) / len(mc_all), "cv": 0}
                                else:
                                    tests_data = data.get("tests", {})
                                    for test_name, test_data in tests_data.items():
                                        if isinstance(test_data, dict) and "throughput" in test_data:
                                            tp = test_data["throughput"]
                                            # Fallback to raw iterations if outlier detection discarded all iterations
                                            if isinstance(tp, list) and not tp and "iterations" in test_data:
                                                tp = [it.get("cpu_events_per_sec") for it in test_data["iterations"] if it.get("cpu_events_per_sec") is not None]
                                            
                                            if isinstance(tp, list) and tp:
                                                stats[test_name] = {"mean": sum(tp) / len(tp), "cv": 0}
                                            elif isinstance(tp, (int, float)):
                                                stats[test_name] = {"mean": tp, "cv": 0}
                                                
                                        # Manually calculate total_time_sec from iterations
                                        if bench_name == "sysbench" and isinstance(test_data, dict) and "iterations" in test_data:
                                            time_key = f"{test_name}_total_time_sec"
                                            times = [it.get("total_time_sec") for it in test_data["iterations"] if it.get("total_time_sec") is not None]
                                            if times:
                                                stats[time_key] = {"mean": sum(times) / len(times), "cv": 0}
                                                
                                # Extract original run number if possible
                                run_id = r_dir.name.replace("run_", "")
                                try:
                                    # Try to extract the run index (e.g. 001, 002) for consistent display
                                    parts = run_id.split("_")
                                    if len(parts) >= 2 and parts[-1].isdigit():
                                        display_id = f"Run {int(parts[-1])}"
                                    else:
                                        display_id = f"Run {i+1}"
                                except Exception:
                                    display_id = f"Run {i+1}"

                                entry = {
                                    "id": display_id,
                                    "build_id": b_dir.name.replace("build_", ""),
                                    "date": run_id,
                                    "runs_count": 1,
                                    "statistics": stats,
                                    "rca": {},
                                    "regressions": {}
                                }
                                benchmark_info["history"].append(entry)
                            except Exception as e:
                                phase_logger.error(f"Failed to read {results_file}: {e}")
                
                # Single run case (either literally 1 run, or 1 run left after filtering out RCA re-runs)
                elif len(run_dirs) == 1 or (len(run_dirs) > 1 and len([d for d in run_dirs if d.name.startswith("run_") and not d.name.endswith(".1") and not d.name.endswith(".2")]) == 1):
                    benchmark_info["comparison_type"] = "single-run"
                    base_run_dirs = [d for d in run_dirs if d.name.startswith("run_") and not d.name.endswith(".1") and not d.name.endswith(".2")]
                    r_dir = base_run_dirs[0] if base_run_dirs else run_dirs[0]
                    results_file = r_dir / "results.json"
                    analysis_file = b_dir / "build_analysis.json"
                    stats = {}
                    
                    if analysis_file.exists():
                        try:
                            with open(analysis_file, "r") as f:
                                analysis_data = json.load(f)
                            stats = analysis_data.get("statistics", {})
                            date_str = analysis_data.get("metadata", {}).get("aggregated_at", r_dir.name.replace("run_", ""))
                            
                            # Manually calculate total_time_sec from results.json if it doesn't exist
                            if bench_name == "sysbench" and results_file.exists():
                                try:
                                    with open(results_file, "r") as rf:
                                        rdata = json.load(rf)
                                        for tname, tdata in rdata.get("tests", {}).items():
                                            time_key = f"{tname}_total_time_sec"
                                            if time_key not in stats and "iterations" in tdata:
                                                times = [it.get("total_time_sec") for it in tdata["iterations"] if it.get("total_time_sec") is not None]
                                                if times:
                                                    stats[time_key] = {"mean": sum(times) / len(times), "cv": 0}
                                except Exception:
                                    pass
                                    
                            entry = {
                                "id": b_dir.name.replace("build_", ""),
                                "build_id": b_dir.name.replace("build_", ""),
                                "date": date_str,
                                "runs_count": 1,
                                "statistics": stats,
                                "rca": {},
                                "regressions": {}
                            }
                            benchmark_info["history"].append(entry)
                        except Exception as e:
                            phase_logger.error(f"Failed to read {analysis_file}: {e}")

            # Calculate regressions between consecutive elements in history
            for i in range(1, len(benchmark_info["history"])):
                baseline = benchmark_info["history"][i-1]
                current = benchmark_info["history"][i]
                base_stats = baseline.get("statistics", {})
                curr_stats = current.get("statistics", {})
                build_reg_results = {}
                for test_name in curr_stats.keys():
                    if test_name in base_stats:
                        res = regression_detector.detect_regressions(
                            baseline_metrics=base_stats[test_name],
                            current_metrics=curr_stats[test_name],
                            test_name=test_name
                        )
                        build_reg_results[test_name] = res
                
                anomalies = current.get("anomalies", {})
                rca_out = RCADetector.generate_rca(build_reg_results, anomalies)
                current["rca"] = rca_out
                current["regressions"] = build_reg_results

            # Generate chart data for this benchmark
            if benchmark_info["history"]:
                labels = [h["id"] for h in benchmark_info["history"]]
                
                all_metrics = set()
                for h in benchmark_info["history"]:
                    all_metrics.update(h["statistics"].keys())
                
                charts = []
                
                category_mapping = {
                    "sysbench_cpu_prime_single_test": "CPU",
                    "sysbench_cpu_prime_multi_test": "CPU",
                    "sysbench_memory_sequential_read": "Memory",
                    "sysbench_memory_sequential_write": "Memory",
                    "sysbench_memory_seq_read_test": "Memory",
                    "sysbench_memory_seq_write_test": "Memory",
                    "sysbench_memory_random_read": "Memory",
                    "sysbench_memory_random_write": "Memory",
                    "sysbench_threads_scheduler_test": "Threads",
                    "sysbench_mutex_contention_test": "Mutex contention",
                    "sysbench_fileio_seq_write_test": "FileIO",
                    "sysbench_fileio_seq_read_test": "FileIO",
                    "sysbench_fileio_random_write_test": "FileIO",
                    "sysbench_fileio_random_read_test": "FileIO",
                    "sysbench_fileio_random_mixed_test": "FileIO",
                    "sched_ipc_default": "scheduler_ipc_default_test",
                    "sched_ipc_heavy": "scheduler_ipc_default_test",
                    "sched_ipc_sockets_extreme": "scheduler_ipc_default_test",
                    "sequential_write_rate": "FileIO",
                    "random_write_rate": "FileIO",
                    "mixed_write_rate": "FileIO",
                    "geekbench_cpu_single_core": "CPU",
                    "geekbench_cpu_multi_core": "CPU"
                }
                
                category_order = ["CPU", "Memory", "Threads", "Mutex contention", "FileIO", "scheduler_ipc_default_test", "Graphics"]
                charts_by_category = {cat: [] for cat in category_order}
                
                colors = ['#3498db', '#e74c3c', '#2ecc71', '#f1c40f', '#9b59b6', '#1abc9c', '#34495e', '#e67e22', '#95a5a6', '#d35400']
                
                for idx, m_name in enumerate(sorted(list(all_metrics))):
                    cat = category_mapping.get(m_name)
                    
                    if m_name.startswith("glmark2"):
                        cat = "Graphics"
                        
                    if not cat:
                        continue
                        
                    data_points = []
                    for h in benchmark_info["history"]:
                        val = h["statistics"].get(m_name, {}).get("mean", 0)
                        data_points.append(val)
                    
                    chart_obj = {
                        "metric_name": m_name,
                        "labels": labels,
                        "dataset": {
                            "label": m_name,
                            "data": data_points,
                            "backgroundColor": colors[idx % len(colors)],
                            "borderColor": colors[idx % len(colors)],
                            "borderWidth": 1
                        }
                    }
                    charts.append(chart_obj)
                    charts_by_category[cat].append(chart_obj)
                
                # Filter out empty categories while preserving order
                charts_by_category = {k: v for k, v in charts_by_category.items() if v}
                
                benchmark_info["charts"] = charts
                benchmark_info["charts_by_category"] = charts_by_category
                
                benchmarks_data.append(benchmark_info)
    
    updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    output_html = reports_dir / "index.html"
    
    # Extract device information from latest results.json (collected from target device)
    device_info = {
        'model': 'not available',
        'os_pretty_name': 'not available',
        'os_build_id': 'unknown',
        'kernel': 'not available'
    }
    
    # Find the most recent results.json with device_info
    if output_dir.exists():
        latest_result_file = None
        latest_mtime = 0
        
        for bench_dir in output_dir.iterdir():
            if not bench_dir.is_dir() or bench_dir.name == "reports":
                continue
            for build_dir in bench_dir.glob("build_*"):
                if not build_dir.is_dir():
                    continue
                for run_dir in build_dir.glob("run_*"):
                    if not run_dir.is_dir():
                        continue
                    results_file = run_dir / "results.json"
                    if results_file.exists():
                        mtime = results_file.stat().st_mtime
                        if mtime > latest_mtime:
                            latest_mtime = mtime
                            latest_result_file = results_file
        
        # Extract device info from latest results.json
        if latest_result_file:
            try:
                with open(latest_result_file, "r") as f:
                    results_data = json.load(f)
                    metadata = results_data.get("metadata", {})
                    extracted_device_info = metadata.get("device_info", {})
                    
                    if extracted_device_info:
                        device_info = {
                            'model': extracted_device_info.get('model', 'not available'),
                            'os_pretty_name': extracted_device_info.get('os_pretty_name', 'not available'),
                            'os_build_id': extracted_device_info.get('os_build_id', 'unknown'),
                            'kernel': extracted_device_info.get('kernel', 'not available')
                        }
                        phase_logger.info(f"Device information extracted from {latest_result_file.name}")
            except Exception as e:
                phase_logger.warning(f"Failed to extract device info from results: {e}")
    
    if _JINJA_AVAILABLE and template_path.exists():
        try:
            env = Environment(loader=FileSystemLoader(template_path.parent))
            template = env.get_template(template_path.name)
            
            # Re-render with skipped benchmarks if Jinja is available
            rendered = template.render(
                benchmarks=benchmarks_data,
                rca_reports=rca_reports,  # NEW: pass RCA reports directly to template
                updated_at=updated_at,
                json=json,
                config=config,
                skipped_benchmarks=skipped_benchmarks or [],
                device_info=device_info  # NEW: pass device info to template
            )
            with open(output_html, "w", encoding="utf-8") as f:
                f.write(rendered)
            phase_logger.info(f"Dashboard rendered successfully: {output_html}")
        except Exception as e:
            phase_logger.error(f"Failed to render dashboard via Jinja2: {e}")
    else:
        phase_logger.warning("Jinja2 or dashboard template missing. Dashboard HTML could not be rendered.")

def main():
    # Phase 1: Validating working directory
    cwd = Path.cwd()
    if cwd.name != "aibench":
        print("Fatal: main.py must be executed from within the aibench/ directory")
        print("Example: cd aibench && python main.py")
        sys.exit(1)
        
    args = parse_args()
    skipped_benchmarks = []
    
    # Load Configurations
    config_path = Path(args.config)
    if not config_path.exists():
        # Try fallback relative to benchmarks folder
        config_path = Path("benchmarks") / args.config
        
    if not config_path.exists():
        print(f"Error: Config file not found at {args.config}")
        sys.exit(1)
        
    config = load_yaml_config(config_path)
    
    report_config_path = config_path.parent / "report.yaml"
    report_config = load_yaml_config(report_config_path) if report_config_path.exists() else {}

    output_dir = Path(__file__).resolve().parent / "output"
    
    # Gap Enforcement
    bypass_gap = args.bypass_gap or config.get("bypass_gap", False)
    
    # Generate harness timestamp for centralized logging and run naming
    harness_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = Path(__file__).resolve().parent / "logging"
    phase_logger.add_centralized_handler(log_dir, harness_timestamp)
    try:
        validate_and_enforce_gap(output_dir, bypass_gap=bypass_gap)
    except GapValidationError as exc:
        print(f"Aborting execution: {exc}")
        sys.exit(2)

    use_ssh = args.ssh_connection
    conn = None
    adb_manager = None
    serial_executor = None

    if use_ssh:
        from src.utils.ssh_manager import SshManager
        from src.utils.credential_manager import get_ssh_credentials
        phase_logger.info("Initializing SSH Connection Mode...")
        
        # Initialize device history manager
        device_history = DeviceHistoryManager()
        
        # Determine target host from args or let SshManager load from credentials
        target_host = args.host
        
        # Check if target_host looks like a device model name (not an IP)
        if target_host and not any(c.isdigit() or c == '.' for c in target_host):
            # Looks like a device model name, try to lookup in history
            phase_logger.info(f"Looking up device '{target_host}' in history...")
            device_entry = device_history.get_device_by_model(target_host)
            
            if device_entry:
                stored_ip = device_entry.get("ip_address")
                phase_logger.info(f"Found device '{target_host}' in history with IP: {stored_ip}")
                
                # Check if device is reachable
                if device_history.is_reachable(stored_ip):
                    target_host = stored_ip
                    phase_logger.info(f"Device '{target_host}' is reachable, using stored IP: {stored_ip}")
                else:
                    # Device not reachable, show list of reachable devices
                    phase_logger.error(f"Device '{target_host}' (IP: {stored_ip}) is not reachable.")
                    reachable_devices = device_history.get_reachable_devices()
                    if reachable_devices:
                        phase_logger.info("Available reachable devices:")
                        for dev in reachable_devices:
                            phase_logger.info(f"  - {dev.get('device_model')} (last used: {dev.get('last_used')})")
                    else:
                        phase_logger.info("No reachable devices found in history.")
                    phase_logger.error("Please provide a valid IP address using --host <ip-address>")
                    sys.exit(1)
            else:
                # Device not found in history
                phase_logger.error(f"Device '{target_host}' not found in history.")
                all_devices = device_history.list_devices(names_only=True)
                if all_devices:
                    phase_logger.info(f"Known devices: {', '.join(all_devices)}")
                phase_logger.error("Please provide the IP address using --host <ip-address>")
                sys.exit(1)

        # No --host and not a device model name: fall back to the default
        # host configured in config/credentials.yaml (ssh.host).
        if not target_host:
            default_host = get_ssh_credentials().get("host")
            if default_host:
                target_host = default_host
                phase_logger.info(f"No --host provided; using default host from config/credentials.yaml: {target_host}")
            else:
                phase_logger.error("No --host provided and no default host configured.")
                phase_logger.error(
                    "Please provide a target using --host <ip-address>, or set ssh.host "
                    "in config/credentials.yaml (see credentials.yaml.example)."
                )
                sys.exit(1)

        # Validate IP address format (basic check)
        if target_host and not target_host.replace('.', '').isdigit():
            phase_logger.error(f"Invalid IP address format: {target_host}")
            sys.exit(1)
        
        # Check if IP is reachable before attempting SSH connection
        if not device_history.is_reachable(target_host):
            phase_logger.error(f"Target host {target_host} is not reachable (SSH port 22 not responding).")
            reachable_devices = device_history.get_reachable_devices()
            if reachable_devices:
                phase_logger.info("Available reachable devices:")
                for dev in reachable_devices:
                    phase_logger.info(f"  - {dev.get('device_model')} (last used: {dev.get('last_used')})")
            sys.exit(1)
        
        # SshManager will load credentials from credential_manager automatically
        ssh_manager = SshManager(host=target_host)
        try:
            ssh_manager.connect()
            ssh_manager.check_device_status()
            
            # Fetch device details and add to history
            try:
                os_info = ssh_manager.get_os_release_info()
                build_id = os_info.get('build_id', 'unknown')
                pretty_name = os_info.get('pretty_name', 'unknown')
                
                # Extract device model from os-release or use codename
                device_model = os_info.get('name', 'unknown').lower()
                if device_model == 'unknown':
                    # Try to get from active_device in config
                    device_model = config.get('active_device', 'unknown').lower()
                
                # Get kernel version
                kernel_output = ssh_manager.execute_shell_command("uname -r", timeout_override=5.0)
                kernel = kernel_output.strip() if kernel_output else 'unknown'
                
                # Add device to history
                device_history.add_device(
                    ip_address=target_host,
                    device_model=device_model,
                    build_id=build_id,
                    os_pretty_name=pretty_name,
                    kernel=kernel
                )
                phase_logger.info(f"Device '{device_model}' added to history")
                
            except Exception as dev_exc:
                phase_logger.warning(f"Failed to fetch device details for history: {dev_exc}")
            
        except Exception as exc:
            phase_logger.error(f"Target connection validation via SSH failed: {exc}")
            sys.exit(1)
        
        conn = ssh_manager
        adb_manager = ssh_manager
        serial_executor = ssh_manager
    else:
        # Resolve COM Port and Baud
        port = config.get("port", "COM7")
        baud = config.get("baud", 115200)

        phase_logger.info(f"Connecting to target on {port} @ {baud} bps...")
        conn = open_serial_connection(port, baud)
        
        if not handle_login(conn):
            phase_logger.error("Failed to authenticate/log in on serial terminal. Exiting.")
            close_connection(conn)
            sys.exit(1)

        # Enable target ADB and start daemon
        phase_logger.info("Enabling target debugging interfaces...")
        send_cmd(conn, "touch /etc/usb-debugging-enabled")
        send_cmd(conn, "systemctl start android-tools-adbd")
        time.sleep(2)

        try:
            adb_manager = AdbManager()
            adb_manager.check_device_status()
        except Exception as exc:
            phase_logger.error(f"Target connection validation via ADB failed: {exc}")
            close_connection(conn)
            sys.exit(1)
            
        serial_executor = SerialCommandExecutor(conn)

    # Retrieve build id
    build_id = args.build_id or config.get("build_id")
    if not build_id:
        build_id = adb_manager.get_build_id()
    phase_logger.info(f"Target Build ID confirmed: {build_id}")

    print_nproc(serial_executor)

    # Select benchmarks to execute
    active_from_config = config.get("active_benchmarks", ["coremark", "sysbench", "tiobench", "unixbench"])
    selected_benchmarks = args.benchmarks if args.benchmarks else active_from_config
    
    benchmarks_to_run = []
    
    # Validate benchmarks against config
    bench_configs = config.get("benchmarks", {})
    
    # First, handle selected benchmarks
    for bench in selected_benchmarks:
        if bench in bench_configs:
            if bench in args.skip:
                phase_logger.info(f"Skipping benchmark '{bench}' as requested by --skip flag.")
                skipped_benchmarks.append({"name": bench, "reason": "Skipped explicitly via --skip"})
            else:
                benchmarks_to_run.append(bench)
        else:
            warn_msg = f"Benchmark '{bench}' not found in benchmarks.yaml. Skipping."
            phase_logger.warning(warn_msg)
            skipped_benchmarks.append({"name": bench, "reason": "Not found in configuration"})
            
    # Then, record active benchmarks that were NOT selected (e.g. because of --benchmarks filter)
    if args.benchmarks:
        for bench in active_from_config:
            if bench not in selected_benchmarks and bench not in [s["name"] for s in skipped_benchmarks]:
                skipped_benchmarks.append({"name": bench, "reason": "Not selected in --benchmarks"})
                
    # Also handle skipped active benchmarks if they weren't in selected_benchmarks but were in --skip
    for bench in args.skip:
        if bench in active_from_config and bench not in selected_benchmarks and bench not in [s["name"] for s in skipped_benchmarks]:
            skipped_benchmarks.append({"name": bench, "reason": "Skipped explicitly via --skip"})
            
    if not benchmarks_to_run:
        phase_logger.error("No valid benchmarks selected to run. Exiting.")
        sys.exit(1)

    phase_logger.info(f"Selected benchmarks to run: {benchmarks_to_run}")

    for bench_name in benchmarks_to_run:
        phase_logger.info(f"\n==================================================")
        phase_logger.info(f"Beginning Benchmark Execution: {bench_name.upper()}")
        phase_logger.info(f"==================================================")
        
        bench_config = config.get("benchmarks", {}).get(bench_name, {})
        
        # In the context of the harness:
        # bench_config["runs"] controls suite execution (default 1)
        # bench_config["iterations"] controls sub-test execution (default 3)
        if args.runs is not None:
            bench_config["runs"] = args.runs
            
        if args.iterations is not None:
            bench_config["iterations"] = args.iterations
            
        if args.tests:
            test_key = "tests"
            available_tests = bench_config.get(test_key, [])
            valid_tests = []
            
            for t in args.tests:
                # Direct match for specific test (e.g. sysbench_fileio_seq_read_test)
                if t in available_tests:
                    valid_tests.append(t)
                else:
                    # Category match logic (e.g. 'fileio', 'cpu', 'memory')
                    category_matches = []
                    for available_test in available_tests:
                        # Extract category from available test name
                        # Standard format is often benchname_category_...
                        # (e.g., sysbench_fileio_seq_read_test -> fileio)
                        # We also check if the user provided category string is anywhere in the test name
                        # or if it matches the prefix after the benchmark name.
                        
                        # Remove benchmark prefix if present to find category
                        parsed_name = available_test
                        if parsed_name.startswith(f"{bench_name}_"):
                            parsed_name = parsed_name[len(f"{bench_name}_"):]
                            
                        test_category = parsed_name.split('_')[0]
                        
                        if t == test_category or f"_{t}_" in available_test or available_test.endswith(f"_{t}"):
                            category_matches.append(available_test)
                            
                    if category_matches:
                        phase_logger.info(f"Expanded category '{t}' to {len(category_matches)} tests.")
                        # Extend but avoid duplicates
                        for match in category_matches:
                            if match not in valid_tests:
                                valid_tests.append(match)
                    else:
                        phase_logger.warning(f"Test or category '{t}' not found for benchmark '{bench_name}'. Skipping.")
            
            if valid_tests:
                bench_config[test_key] = valid_tests
                phase_logger.info(f"Filtering {bench_name} tests to: {valid_tests}")
            else:
                phase_logger.warning(f"No valid tests provided for benchmark '{bench_name}'. Using default tests.")

        if getattr(args, "unknown_args", None):
            bench_config["overrides"] = parse_unknown_args(args.unknown_args)

        # Pass telemetry collection flag to the benchmark instance
        bench_config["collect_telemetry"] = args.collect_telemetry

        # Get total runs (default to 1)
        total_runs = bench_config.get("runs", 1)
        if total_runs < 1:
            total_runs = 1
            
        for current_run in range(1, total_runs + 1):
            phase_logger.info(f"\n--- Suite Run {current_run}/{total_runs} for {bench_name.upper()} ---")
            
            # Create collision-proof run name for each suite run (suffixes increment naturally)
            run_name = generate_run_name(output_dir, bench_name, build_id, base_timestamp=harness_timestamp)
            run_dir = output_dir / bench_name / f"build_{build_id}" / run_name
            run_dir.mkdir(parents=True, exist_ok=True)
            
            phase_logger.info(f"Executing in run folder: {run_dir}")
            
            # Load and execute benchmark
            try:
                runner = get_benchmark(bench_name, bench_config, run_dir)
                results = runner.execute_lifecycle(serial_executor, adb_manager)
                
                # Tier 1 - Write individual results JSON (HTML report is
                # (re-)generated AFTER the RCA report below, so it can include
                # regression/RCA findings for this run in one render pass).
                write_json_results(results, run_dir)

                # Tier 2 - Re-aggregate build metrics and generate build_analysis.json
                phase_logger.info(f"Re-aggregating stats for benchmark {bench_name}...")
                build_analysis = aggregate_build_runs(output_dir, bench_name, build_id)

                # regression-detection-and-rca skill: automatically triggered after
                # EVERY suite run, per project requirement (no explicit invocation
                # needed). Runs the 3-tier (iteration/run/build) comparison plus
                # any explicitly-stored baseline comparison, and writes
                # rca_report.json into this run's directory. Any failure here is
                # logged as a warning only -- it must never fail the benchmark run.
                if _RCA_SKILL_AVAILABLE:
                    try:
                        phase_logger.info(f"Running regression-detection-and-rca for {bench_name}...")
                        
                        rca_mode_str = "smart" if args.smart_rca else ("full" if args.full_rca else "report")
                        
                        rca_report = run_rca_for_run(
                            output_dir=output_dir,
                            benchmark_name=bench_name,
                            build_id=build_id,
                            run_dir=run_dir,
                            config=config,
                            baseline_tag=args.baseline_tag,
                            rca_all_runs=args.rca_all_runs,
                            rca_all_iterations=args.rca_all_iterations,
                            rca_mode=rca_mode_str,
                            serial_executor=serial_executor,
                            adb_manager=adb_manager,
                            bench_config=bench_config,
                            use_ai_skill=args.rca_use_ai
                        )
                        
                        if getattr(args, "_telemetry_conflict", False):
                            conflict_warn = "--collect-telemetry was requested but is disabled in --report-mode."
                            if conflict_warn not in rca_report.setdefault("telemetry_warnings", []):
                                rca_report["telemetry_warnings"].append(conflict_warn)
                                # Rewrite the report with the new warning
                                rca_file = run_dir / "rca_report.json"
                                if rca_file.exists():
                                    with open(rca_file, "w") as f:
                                        json.dump(rca_report, f, indent=4)
                                        
                        if rca_report.get("any_regression_detected"):
                            rca_msg = "see rca_report.json for full RCA." if (args.full_rca or args.smart_rca) else "see rca_report.json for details."
                            phase_logger.warning(
                                f"REGRESSION DETECTED for {bench_name} (run {run_dir.name}) -- {rca_msg}"
                            )
                        for w in rca_report.get("telemetry_warnings", []):
                            phase_logger.warning(f"[RCA telemetry warning] {w}")
                    except Exception as rca_exc:
                        phase_logger.warning(f"regression-detection-and-rca failed for {bench_name} (run {run_dir.name}): {rca_exc}")

                # Now render the individual HTML report -- if rca_report.json was
                # just written above, generate_individual_html_report() picks it
                # up automatically and passes it to the template as `rca_report`.
                indiv_template = Path(report_config.get("templates", {}).get("individual", "config/templates/individual_report.html"))
                if not indiv_template.exists():
                    indiv_template = Path("benchmarks") / indiv_template
                generate_individual_html_report(results, run_dir, indiv_template)

                # --store-baseline: persist this build's aggregated statistics as
                # the named baseline (default tag "default") for this benchmark,
                # for use by future explicit "compare with baseline" runs.
                if args.store_baseline and _RCA_SKILL_AVAILABLE and build_analysis:
                    try:
                        tag = args.baseline_tag or baseline_manager.DEFAULT_TAG
                        baseline_manager.store_baseline(
                            output_dir, bench_name, build_id,
                            build_analysis.get("statistics", {}), tag=tag
                        )
                        phase_logger.info(f"Stored baseline (tag='{tag}') for {bench_name} from build {build_id}.")
                    except Exception as baseline_exc:
                        phase_logger.warning(f"Failed to store baseline for {bench_name}: {baseline_exc}")

            except Exception as e:
                phase_logger.error(f"Benchmark '{bench_name}' execution encountered a fatal error during run {current_run}: {e}")
                continue
            
            # Enforce gap if running multiple times (except after the last run)
            if current_run < total_runs and not bypass_gap:
                phase_logger.info("Enforcing cooldown gap before next suite run...")
                time.sleep(300) # 5 minutes cooldown

    # Tier 3 - Render Summary Dashboard
    dash_template = Path(report_config.get("templates", {}).get("dashboard", "config/templates/summary_dashboard.html"))
    if not dash_template.exists():
        dash_template = Path("benchmarks") / dash_template
    render_dashboard(output_dir, dash_template, config, skipped_benchmarks)

    # Tier 4 - Generate Excel Report (automatic, alongside HTML dashboard)
    build_history_path = output_dir / "reports" / "build_history.json"
    if build_history_path.exists():
        try:
            phase_logger.info("Generating Excel benchmark report...")
            
            # Construct template path relative to project root
            template_path = Path(__file__).resolve().parent.parent / "performance-dashboard-skill" / "templates" / "QA_Data_Template.xlsx"
            
            excel_path = _generate_excel_report(
                output_dir=output_dir / "reports",
                build_history_path=build_history_path,
                template_path=template_path,
            )
            if excel_path:
                phase_logger.info(f"Excel report saved: {excel_path.name}")
            else:
                phase_logger.warning("Excel report generation returned no output (openpyxl may not be installed or template not found).")
        except Exception as _excel_exc:
            phase_logger.warning(f"Excel report generation failed (non-fatal): {_excel_exc}")
    else:
        phase_logger.warning(f"build_history.json not found at {build_history_path} — skipping Excel generation.")

    # Safely teardown connection
    if args.ssh_connection:
        conn.close()
    else:
        close_connection(conn)
    
    # Open dashboard in browser
    dashboard_path = (output_dir / "reports" / "index.html").resolve()
    if dashboard_path.exists():
        try:
            phase_logger.info(f"Opening dashboard in default browser: {dashboard_path}")
            webbrowser.open(f"file:///{dashboard_path}")
        except Exception as e:
            phase_logger.error(f"Failed to open dashboard in browser: {e}")
    else:
        phase_logger.error(f"Dashboard file not found, cannot open in browser: {dashboard_path}")
        
    phase_logger.info("\nUnified Benchmark Campaign Complete!")


if __name__ == "__main__":
    main()

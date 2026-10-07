"""
CLI entry point for generating Excel benchmark reports.

This script can be invoked directly from the command line to generate
an Excel report from an existing build_history.json file, without
needing to re-run any benchmarks.

Usage:
    cd benchmarks
    python -m src.reporting.generate_excel_report
    python -m src.reporting.generate_excel_report --build-history output/reports/build_history.json
    python -m src.reporting.generate_excel_report --output-dir /custom/path
    python -m src.reporting.generate_excel_report --device SA8775P
    python -m src.reporting.generate_excel_report --template /path/to/template.xlsx
"""

import argparse
import logging
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default paths (relative to the aibench/ working directory)
# ---------------------------------------------------------------------------
_DEFAULT_BUILD_HISTORY = Path("output/reports/build_history.json")
_DEFAULT_OUTPUT_DIR    = Path("output/reports")
_DEFAULT_DEVICE        = "IQ-9075"


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Generate an Excel benchmark report from build_history.json.\n"
            "The output file is saved as:\n"
            "  benchmark_report_<build_id>_<YYYYMMDD>_<HHMMSS>.xlsx\n"
            "in the specified output directory."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--build-history",
        type=Path,
        default=_DEFAULT_BUILD_HISTORY,
        metavar="PATH",
        help=(
            f"Path to build_history.json "
            f"(default: {_DEFAULT_BUILD_HISTORY})"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=_DEFAULT_OUTPUT_DIR,
        metavar="DIR",
        help=(
            f"Directory where the .xlsx file will be saved "
            f"(default: {_DEFAULT_OUTPUT_DIR})"
        ),
    )
    parser.add_argument(
        "--template",
        type=Path,
        default=None,
        metavar="PATH",
        help=(
            "Path to the Excel template (.xlsx). "
            "Defaults to performance-dashboard-skill/templates/QA_Data_Template.xlsx"
        ),
    )
    parser.add_argument(
        "--device",
        type=str,
        default=_DEFAULT_DEVICE,
        metavar="DEVICE",
        help=(
            f"Device name used to select the correct tab in the template "
            f"(default: {_DEFAULT_DEVICE}). "
            "Examples: IQ-9075, SA8775P, SA8295P"
        ),
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose (DEBUG) logging.",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    """
    Main entry point.

    Returns:
        0 on success, 1 on failure.
    """
    args = parse_args(argv)

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Validate inputs
    if not args.build_history.exists():
        logger.error(f"build_history.json not found: {args.build_history}")
        logger.error(
            "Run benchmarks first (python main.py --ssh-connection) "
            "or specify the correct path with --build-history."
        )
        return 1

    # Import here so the module can be imported without openpyxl installed
    try:
        from src.reporting.excel_generator import generate_excel_report
    except ImportError as exc:
        logger.error(f"Failed to import excel_generator: {exc}")
        return 1

    logger.info(f"Generating Excel report from: {args.build_history}")
    logger.info(f"Output directory: {args.output_dir}")
    logger.info(f"Device: {args.device}")

    output_path = generate_excel_report(
        output_dir=args.output_dir,
        build_history_path=args.build_history,
        template_path=args.template,
        device=args.device,
    )

    if output_path is None:
        logger.error("Excel report generation failed.")
        return 1

    logger.info(f"✓ Excel report saved: {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
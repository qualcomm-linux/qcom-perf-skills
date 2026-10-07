"""
Excel Report Generator for the Unified Benchmark Harness.

Reads build_history.json and populates the QA_Data_Template.xlsx
with benchmark results. Generates a timestamped output file in the
same directory as index.html (output/reports/).

The template has these columns:
    A: Benchmark
    B: Sub-test / Metric
    C: QLI 2.0 GA Final Value  ← mean of all runs
    D: Unit                    ← auto-inferred from metric key
    E: Notes / Caveats         ← left blank

Usage (standalone):
    python -m src.reporting.generate_excel_report \
        --build-history output/reports/build_history.json \
        --output-dir output/reports

Usage (programmatic):
    from src.reporting.excel_generator import ExcelGenerator
    gen = ExcelGenerator(output_dir=Path("output/reports"))
    gen.generate_report(build_history_path=Path("output/reports/build_history.json"))
"""

import json
import logging
import shutil
import tempfile
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter, column_index_from_string
    from openpyxl.cell.cell import MergedCell
    _OPENPYXL_AVAILABLE = True
except ImportError:
    _OPENPYXL_AVAILABLE = False
    MergedCell = None

from .excel_mappings import (
    BENCHMARK_METRIC_MAPPINGS,
    BENCHMARK_SECTION_HEADERS,
    DEVICE_TAB_NAMES,
    UNIT_PATTERNS,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default template path (relative to this file's location)
# ---------------------------------------------------------------------------
_THIS_DIR = Path(__file__).parent
_DEFAULT_TEMPLATE = (
    _THIS_DIR.parent.parent.parent
    / "performance-dashboard-skill"
    / "templates"
    / "QA_Data_Template.xlsx"
)

# ---------------------------------------------------------------------------
# Styling constants
# ---------------------------------------------------------------------------
_DATA_FILL    = PatternFill(start_color="FFFF99", end_color="FFFF99", fill_type="solid") if _OPENPYXL_AVAILABLE else None
_CENTER_ALIGN = Alignment(horizontal="center", vertical="center") if _OPENPYXL_AVAILABLE else None


class ExcelGenerator:
    """
    Generates an Excel benchmark report by populating the QA_Data_Template.xlsx
    with data from build_history.json.

    Column mapping:
        C (QLI 2.0 GA Final Value) ← mean of all runs for the metric
        D (Unit)                   ← auto-inferred from the metric key
        E (Notes / Caveats)        ← left blank

    Multi-device support:
        The template may contain one tab per device (e.g. "IQ-9075", "SA8775P").
        The generator detects the device from build_history.json metadata (or falls
        back to the default device) and populates the corresponding tab.
    """

    def __init__(
        self,
        output_dir: Path,
        template_path: Optional[Path] = None,
        device: str = "IQ-9075",
    ):
        self.output_dir = Path(output_dir)
        self.template_path = Path(template_path) if template_path else _DEFAULT_TEMPLATE
        self.device = device
        self._build_history: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_report(
        self,
        build_history_path: Optional[Path] = None,
        build_history_data: Optional[List[Dict]] = None,
    ) -> Optional[Path]:
        """
        Generate the Excel report.

        Args:
            build_history_path: Path to build_history.json (used if data not provided).
            build_history_data: Pre-loaded list from build_history.json.

        Returns:
            Path to the generated .xlsx file, or None on failure.
        """
        if not _OPENPYXL_AVAILABLE:
            logger.error(
                "[ExcelGenerator] openpyxl is not installed. "
                "Run: pip install openpyxl"
            )
            return None

        # Load data
        if build_history_data is not None:
            self._build_history = build_history_data
        elif build_history_path is not None:
            if not self._load_build_history(Path(build_history_path)):
                return None
        else:
            logger.error("[ExcelGenerator] No data source provided.")
            return None

        if not self._build_history:
            logger.warning("[ExcelGenerator] build_history is empty — nothing to write.")
            return None

        if not self.template_path.exists():
            logger.error(f"[ExcelGenerator] Template not found: {self.template_path}")
            return None

        try:
            return self._build_excel()
        except Exception as exc:
            logger.error(f"[ExcelGenerator] Unexpected error: {exc}")
            logger.debug(traceback.format_exc())
            return None

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_build_history(self, path: Path) -> bool:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                self._build_history = json.load(fh)
            logger.info(f"[ExcelGenerator] Loaded {len(self._build_history)} benchmark entries from {path}")
            return True
        except Exception as exc:
            logger.error(f"[ExcelGenerator] Failed to load {path}: {exc}")
            return False

    def _get_build_id(self) -> str:
        if self._build_history:
            return self._build_history[0]["metadata"].get("build_id", "unknown")
        return "unknown"

    def _get_device_from_history(self) -> str:
        """
        Try to detect the device from build_history metadata.
        Falls back to self.device (constructor argument).
        """
        for entry in self._build_history:
            meta = entry.get("metadata", {})
            device = meta.get("device") or meta.get("device_name") or meta.get("target_device")
            if device:
                return device
        return self.device

    def _build_excel(self) -> Optional[Path]:
        """Core logic: load template, populate, save."""
        # Copy template to a temp file to avoid PermissionError when the
        # original is open in Excel or being synced by OneDrive/SharePoint.
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            shutil.copy2(self.template_path, tmp_path)
        except Exception as copy_exc:
            logger.error(f"[ExcelGenerator] Failed to copy template to temp file: {copy_exc}")
            return None

        try:
            workbook = openpyxl.load_workbook(tmp_path)
        except Exception as load_exc:
            logger.error(f"[ExcelGenerator] Failed to load template: {load_exc}")
            tmp_path.unlink(missing_ok=True)
            return None
        finally:
            # Remove temp copy after loading (workbook is in memory)
            tmp_path.unlink(missing_ok=True)

        device = self._get_device_from_history()
        tab_name = DEVICE_TAB_NAMES.get(device, DEVICE_TAB_NAMES["default"])

        # Resolve worksheet
        ws = self._get_or_create_worksheet(workbook, tab_name, device)
        if ws is None:
            logger.error(f"[ExcelGenerator] Could not find or create worksheet for device '{device}'.")
            return None

        # Scan template rows
        row_map = self._scan_template_rows(ws)
        data_col_letter = self._find_data_column(ws)
        data_col_idx = column_index_from_string(data_col_letter)
        unit_col_idx = data_col_idx + 1   # D: Unit
        # notes_col_idx = data_col_idx + 2  # E: Notes / Caveats — left blank

        # Populate data
        populated = 0
        for bench_entry in self._build_history:
            bench_name = bench_entry["metadata"]["benchmark_name"]
            statistics = bench_entry.get("statistics", {})

            if bench_name not in BENCHMARK_METRIC_MAPPINGS:
                logger.debug(f"[ExcelGenerator] No mapping for benchmark '{bench_name}' — skipping.")
                continue

            section_headers = BENCHMARK_SECTION_HEADERS.get(bench_name, [])
            metric_map = BENCHMARK_METRIC_MAPPINGS[bench_name]

            # Track which template rows have already been written for this benchmark
            # (prevents duplicate writes when two metric keys map to the same row)
            written_rows = set()

            for metric_key, sub_test_text in metric_map.items():
                if metric_key not in statistics:
                    continue

                metric_stats = statistics[metric_key]

                # Find the target row
                target_row = self._find_row(
                    row_map, sub_test_text, section_headers
                )
                if target_row is None:
                    logger.debug(
                        f"[ExcelGenerator] Row not found for "
                        f"benchmark='{bench_name}' metric='{metric_key}' "
                        f"search='{sub_test_text}'"
                    )
                    continue

                if target_row in written_rows:
                    # Two metric keys mapped to the same template row - the
                    # second one's data is dropped (writing it would
                    # overwrite the first). Surface this with a warning
                    # instead of only a code comment, since it otherwise
                    # silently discards real benchmark data (e.g. sysbench
                    # multi-core CPU results) with zero visibility.
                    logger.warning(
                        f"[ExcelGenerator] benchmark='{bench_name}' metric='{metric_key}' "
                        f"maps to the same template row ('{sub_test_text}') as a previously "
                        f"written metric — this metric's data will NOT appear in the report."
                    )
                    continue
                written_rows.add(target_row)

                # Write mean → Column C, unit → Column D
                self._write_value_row(
                    ws, target_row, data_col_idx, unit_col_idx,
                    metric_stats, metric_key
                )
                populated += 1

        logger.info(f"[ExcelGenerator] Populated {populated} metric rows.")

        # Generate output path
        build_id = self._get_build_id()
        now = datetime.now()
        date_str = now.strftime("%Y%m%d")
        time_str = now.strftime("%H%M%S")
        filename = f"benchmark_report_{build_id}_{date_str}_{time_str}.xlsx"

        self.output_dir.mkdir(parents=True, exist_ok=True)
        output_path = self.output_dir / filename

        workbook.save(output_path)
        logger.info(f"[ExcelGenerator] Saved Excel report → {output_path}")
        return output_path

    # ------------------------------------------------------------------
    # Worksheet helpers
    # ------------------------------------------------------------------

    def _get_or_create_worksheet(self, workbook, tab_name: str, device: str):
        """Return the worksheet for the given tab name, or None if not found."""
        if tab_name in workbook.sheetnames:
            return workbook[tab_name]
        # Try the device name directly
        if device in workbook.sheetnames:
            return workbook[device]
        # Try case-insensitive match
        for name in workbook.sheetnames:
            if name.lower() == tab_name.lower() or name.lower() == device.lower():
                return workbook[name]
        # If only one sheet exists, use it
        if len(workbook.sheetnames) == 1:
            logger.warning(
                f"[ExcelGenerator] Tab '{tab_name}' not found; "
                f"using only available sheet '{workbook.sheetnames[0]}'."
            )
            return workbook[workbook.sheetnames[0]]
        logger.warning(
            f"[ExcelGenerator] Tab '{tab_name}' not found in template. "
            f"Available sheets: {workbook.sheetnames}"
        )
        return None

    def _scan_template_rows(self, ws) -> Dict[str, List[Tuple[int, str]]]:
        """
        Scan the worksheet and build a row index.

        Returns:
            {
                'sub_test_text_lower': [(row_number, section_header), ...],
                ...
            }
        """
        row_map: Dict[str, List[Tuple[int, str]]] = {}
        current_section = ""

        for row in ws.iter_rows():
            col_a_val = row[0].value if len(row) > 0 else None
            col_b_val = row[1].value if len(row) > 1 else None

            # Update current section from column A
            if col_a_val and isinstance(col_a_val, str) and col_a_val.strip():
                current_section = col_a_val.strip()

            # Index column B text
            if col_b_val and isinstance(col_b_val, str) and col_b_val.strip():
                sub_text = col_b_val.strip()
                key = sub_text.lower()
                row_num = row[0].row
                if key not in row_map:
                    row_map[key] = []
                row_map[key].append((row_num, current_section))

        return row_map

    def _find_data_column(self, ws) -> str:
        """
        Find the column letter for the primary data column.
        Looks for 'final value', 'ga final', or 'value' in the header rows.
        Falls back to column C.
        """
        for row in ws.iter_rows(min_row=1, max_row=6):
            for cell in row:
                if cell.value and isinstance(cell.value, str):
                    lower = cell.value.lower()
                    if "final value" in lower or "ga final" in lower:
                        return cell.column_letter
        return "C"

    def _find_row(
        self,
        row_map: Dict[str, List[Tuple[int, str]]],
        sub_test_text: str,
        section_headers: List[str],
    ) -> Optional[int]:
        """
        Find the row number for a given sub-test text.

        Strategy:
        1. Exact match (case-insensitive) with section disambiguation.
        2. Substring match (sub_test_text contained in template text).
        3. Reverse substring match (template text contained in sub_test_text).
        """
        search = sub_test_text.lower().strip()
        section_lower = [s.lower() for s in section_headers]

        # --- Pass 1: exact match ---
        if search in row_map:
            candidates = row_map[search]
            row = self._disambiguate(candidates, section_lower)
            if row:
                return row

        # --- Pass 2: template text contains search string ---
        for key, candidates in row_map.items():
            if search in key:
                row = self._disambiguate(candidates, section_lower)
                if row:
                    return row

        # --- Pass 3: search string contains template text ---
        for key, candidates in row_map.items():
            if key in search:
                row = self._disambiguate(candidates, section_lower)
                if row:
                    return row

        return None

    def _disambiguate(
        self,
        candidates: List[Tuple[int, str]],
        section_lower: List[str],
    ) -> Optional[int]:
        """
        Given multiple candidate rows, pick the one whose section header
        matches the expected benchmark section.  If no section match,
        return the first candidate.
        """
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0][0]
        # Prefer the candidate whose section matches
        for row_num, section in candidates:
            for s in section_lower:
                if s in section.lower() or section.lower() in s:
                    return row_num
        # Fall back to first candidate
        return candidates[0][0]

    # ------------------------------------------------------------------
    # Statistics column helpers
    # ------------------------------------------------------------------

    def _find_header_row(self, ws) -> int:
        """Find the row number that contains column headers."""
        for row in ws.iter_rows(min_row=1, max_row=5):
            for cell in row:
                if cell.value and isinstance(cell.value, str):
                    lower = cell.value.lower()
                    if "benchmark" in lower or "sub-test" in lower or "final value" in lower:
                        return cell.row
        return 2  # default

    @staticmethod
    def _is_merged(cell) -> bool:
        """Return True if the cell is a read-only merged cell (not the top-left anchor)."""
        return MergedCell is not None and isinstance(cell, MergedCell)

    @staticmethod
    def _infer_unit(metric_key: str) -> str:
        """
        Infer the unit string for a metric key by matching against UNIT_PATTERNS.
        Returns an empty string if no pattern matches.
        """
        key_lower = metric_key.lower()
        for pattern, unit in UNIT_PATTERNS:
            if pattern.lower() in key_lower:
                return unit
        return ""

    def _write_value_row(
        self,
        ws,
        row_num: int,
        data_col_idx: int,
        unit_col_idx: int,
        metric_stats: Dict[str, Any],
        metric_key: str,
    ) -> None:
        """
        Write the mean value into Column C (QLI 2.0 GA Final Value) and
        the inferred unit into Column D (Unit).  Column E (Notes / Caveats)
        is left untouched (blank).
        """
        # --- Column C: mean value ---
        val_cell = ws[f"{get_column_letter(data_col_idx)}{row_num}"]
        if not self._is_merged(val_cell):
            mean = metric_stats.get("mean")
            if mean is not None:
                val_cell.value = round(mean, 4) if isinstance(mean, float) else mean
                if _DATA_FILL:
                    val_cell.fill = _DATA_FILL
            if _CENTER_ALIGN:
                val_cell.alignment = _CENTER_ALIGN

        # --- Column D: unit ---
        unit_cell = ws[f"{get_column_letter(unit_col_idx)}{row_num}"]
        if not self._is_merged(unit_cell):
            unit_cell.value = self._infer_unit(metric_key)
            if _CENTER_ALIGN:
                unit_cell.alignment = _CENTER_ALIGN


# ---------------------------------------------------------------------------
# Convenience function (used by main.py)
# ---------------------------------------------------------------------------

def generate_excel_report(
    output_dir: Path,
    build_history_path: Optional[Path] = None,
    build_history_data: Optional[List[Dict]] = None,
    template_path: Optional[Path] = None,
    device: str = "IQ-9075",
) -> Optional[Path]:
    """
    Convenience wrapper around ExcelGenerator.

    Args:
        output_dir:          Directory where the .xlsx file will be saved.
        build_history_path:  Path to build_history.json.
        build_history_data:  Pre-loaded list (alternative to path).
        template_path:       Override the default template path.
        device:              Device name for tab selection.

    Returns:
        Path to the generated file, or None on failure.
    """
    gen = ExcelGenerator(
        output_dir=output_dir,
        template_path=template_path,
        device=device,
    )
    return gen.generate_report(
        build_history_path=build_history_path,
        build_history_data=build_history_data,
    )
"""The workbook processing pipeline."""

import logging
import re
import shutil
import subprocess
import tempfile
import csv
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from src.ingestion.schema_detector import detect_schema

logger = logging.getLogger(__name__)

# How many sample rows are cached per sheet, for prompt context.
DEFAULT_SAMPLE_ROWS = 10

# A column is treated as categorical when it has at most this many distinct
# values. Above it, the column is free text.
CATEGORICAL_MAX_DISTINCT = 50

# How many distinct values are listed for a categorical column.
MAX_CATEGORY_VALUES = 12

# A sheet is treated as tabular when it has at least this many columns.
MIN_TABULAR_COLUMNS = 2
HEADER_SCAN_ROWS = 10
LARGE_FILE_BYTES = 25 * 1024 * 1024
LARGE_FILE_ROWS = 200_000

# A sheet with more nulls in a column than this is flagged, not dropped.
NULL_HEAVY_RATIO = 0.5

# Currency symbols and thousands separators stripped from numeric columns.
_CURRENCY_RE = re.compile(r"[^0-9eE+\-.]")
_THOUSANDS_RE = re.compile(r"(?<=\d),(?=\d{3}\b)")


class SheetError(Exception):
    """Raised when a single sheet cannot be used."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


# ---------------------------------------------------------------------------
# Step 1: validate
# ---------------------------------------------------------------------------

def validate_file(path: str, max_bytes: int = 100 * 1024 * 1024) -> None:
    """
    Check the file before parsing it.

    Raises:
        SheetError: If the file is missing, empty, too large, or has an
            extension the app does not read.
    """
    file_path = Path(path)
    if not file_path.exists() or not file_path.is_file():
        raise SheetError("The uploaded file is missing.")

    size = file_path.stat().st_size
    if size == 0:
        raise SheetError("The uploaded file is empty.")
    if size > max_bytes:
        raise SheetError(
            f"The file is too large to process ({size // (1024 * 1024)} MB)."
        )

    if file_path.suffix.lower() not in {".csv", ".xlsx", ".xls"}:
        raise SheetError(
            f"'{file_path.suffix}' files are not supported; use .csv or .xlsx."
        )


# ---------------------------------------------------------------------------
# Step 2: parse
# ---------------------------------------------------------------------------

def _read_sheets(path: str) -> Dict[str, pd.DataFrame]:
    """
    Read every sheet in the file.

    A CSV is a single sheet. An Excel workbook has one frame per sheet.
    """
    file_path = Path(path)

    if file_path.suffix.lower() in {".xlsx", ".xls"}:
        try:
            source_path, cleanup = _recalculate_formulas(file_path)
            try:
                frames = {}
                workbook = pd.ExcelFile(source_path)
                for name in workbook.sheet_names:
                    raw = pd.read_excel(
                        source_path,
                        sheet_name=name,
                        header=None,
                        nrows=HEADER_SCAN_ROWS,
                    )
                    header_row = detect_header_row(raw)
                    frames[name] = pd.read_excel(
                        source_path,
                        sheet_name=name,
                        header=header_row,
                    )
            finally:
                if cleanup:
                    source_path.unlink(missing_ok=True)
                    shutil.rmtree(source_path.parent, ignore_errors=True)
        except Exception as exc:  # noqa: BLE001 - any read failure is a sheet failure
            raise SheetError(f"The Excel file could not be read: {exc}") from exc

        if not frames:
            raise SheetError("The Excel file has no sheets.")

        return {str(name): frame for name, frame in frames.items()}

    try:
        header_row = detect_csv_header_row(file_path)
        frame = _read_csv(file_path, header=header_row)
    except pd.errors.EmptyDataError as exc:
        raise SheetError("The file has no header row.") from exc
    except Exception as exc:  # noqa: BLE001 - any read failure is a sheet failure
        raise SheetError(f"The file could not be read: {exc}") from exc

    return {file_path.stem: frame}


def _recalculate_formulas(path: "Path") -> Tuple["Path", bool]:
    """Return a recalculated temporary workbook when LibreOffice is available."""
    executable = shutil.which("libreoffice") or shutil.which("soffice")
    if executable is None or path.suffix.lower() not in {".xlsx", ".xls"}:
        return path, False

    output_dir = Path(tempfile.mkdtemp(prefix="datalogue-recalc-"))
    try:
        completed = subprocess.run(
            [
                executable,
                "--headless",
                "--convert-to",
                "xlsx",
                "--outdir",
                str(output_dir),
                str(path),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
        recalculated = output_dir / f"{path.stem}.xlsx"
        if completed.returncode == 0 and recalculated.exists():
            return recalculated, True
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("Formula recalculation unavailable for '%s': %s", path.name, exc)
    shutil.rmtree(output_dir, ignore_errors=True)
    return path, False


def detect_header_row(sample: pd.DataFrame) -> int:
    """Find the most likely header row in the first few raw rows."""
    if sample.empty:
        raise SheetError("The file has no header row.")

    best_row = 0
    best_score = float("-inf")
    for index, row in sample.iterrows():
        values = [value for value in row.tolist() if pd.notna(value) and str(value).strip()]
        if not values:
            continue
        text = [str(value).strip() for value in values]
        unique = len(set(text))
        non_numeric = sum(not _is_numeric(value) for value in text)
        score = len(values) * 2 + non_numeric + (unique / len(values))
        if index > 0:
            score -= index * 0.25
        if score > best_score:
            best_row = int(index)
            best_score = score
    return best_row


def detect_csv_header_row(path: "Path", encoding: str = "utf-8") -> int:
    """Find a CSV header using physical lines, including leading blanks."""
    with path.open("r", encoding=encoding, newline="") as handle:
        rows = list(csv.reader(handle))[:HEADER_SCAN_ROWS]
    if not rows:
        raise SheetError("The file has no header row.")
    sample = pd.DataFrame(rows)
    return detect_header_row(sample)


def _is_numeric(value: str) -> bool:
    try:
        float(value.replace(",", "").replace("$", "").replace("€", "").replace("£", ""))
        return True
    except ValueError:
        return False


def _read_csv(path: "Path", header: int = 0) -> pd.DataFrame:
    """Read CSVs in chunks for large files while preserving normal behavior."""
    chunks = pd.read_csv(
        path,
        header=0,
        chunksize=50_000,
        engine="python",
        skiprows=header,
    )
    return pd.concat(chunks, ignore_index=True)


def looks_tabular(frame: pd.DataFrame) -> bool:
    """Whether a frame has the shape of a table rather than a cover sheet."""
    if frame is None or frame.empty:
        return False
    if frame.shape[1] < MIN_TABULAR_COLUMNS:
        return False

    # A cover or summary sheet has almost no rows and many empty cells.
    non_null = frame.notna().sum().sum()
    if non_null == 0:
        return False

    density = non_null / (frame.shape[0] * frame.shape[1])
    if frame.shape[0] <= 2 and density < 0.2:
        return False

    return True


def classify_sheet(frame: pd.DataFrame, name: str = "") -> Dict[str, Any]:
    """Classify a sheet before deriving metrics from it."""
    if frame is None or frame.empty:
        return {"class": "not_data", "skip_reason": "The sheet is empty."}

    non_null = frame.notna().sum().sum()
    density = non_null / max(frame.shape[0] * frame.shape[1], 1)
    normalized_name = re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()
    values = " ".join(
        str(value).lower() for value in frame.head(8).fillna("").values.ravel()
    )
    calculator_signal = any(
        token in f"{normalized_name} {values}"
        for token in ("calculator", "lookup", "vlookup", "index match", "select a product")
    )
    if calculator_signal and (
        frame.shape[1] >= 6
        or frame.shape[0] <= 25
        or density < 0.65
    ):
        return {
            "class": "not_data",
            "skip_reason": "This sheet appears to be a calculator or lookup tool, not source data.",
        }
    if not looks_tabular(frame):
        return {
            "class": "not_data",
            "skip_reason": "This sheet does not contain a dense tabular region.",
        }

    period_columns = sum(
        bool(re.search(r"\b(?:q[1-4]|fy|20\d{2})\b", str(column).lower()))
        for column in frame.columns
    )
    if (
        any(token in f"{normalized_name} {values}" for token in (
            "financial", "profit and loss", "income statement", "balance sheet", "ebitda"
        ))
        or ("line item" in values and period_columns >= 2)
    ):
        return {"class": "wide_financial", "skip_reason": None}
    if "dashboard" in normalized_name or (frame.shape[1] >= 8 and density < 0.7):
        return {"class": "dashboard", "skip_reason": None}
    if frame.shape[1] == 1 or (
        frame.shape[0] <= 20 and frame.shape[1] <= 3 and density < 0.7
    ):
        return {"class": "multi_block", "skip_reason": "The sheet may contain multiple small blocks."}
    return {"class": "tabular", "skip_reason": None}


# ---------------------------------------------------------------------------
# Step 3 and 4: infer schema, then clean
# ---------------------------------------------------------------------------

def _clean_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """
    Clean the frame in place, without dropping any rows.

    Header whitespace is trimmed, dates are normalised, and currency
    symbols are stripped from numeric columns. Null-heavy columns are
    flagged rather than removed.
    """
    cleaned = frame.copy()

    cleaned.columns = [
        str(column).strip() if isinstance(column, str) else column
        for column in cleaned.columns
    ]

    # Two columns can end up with the same name after trimming.
    seen: Dict[str, int] = {}
    renamed = []
    for column in cleaned.columns:
        name = str(column)
        if name in seen:
            seen[name] += 1
            renamed.append(f"{name}_{seen[name]}")
        else:
            seen[name] = 0
            renamed.append(name)
    cleaned.columns = renamed

    for column in cleaned.columns:
        series = cleaned[column]

        if pd.api.types.is_datetime64_any_dtype(series):
            continue

        if pd.api.types.is_numeric_dtype(series):
            continue

        # A text column that is really a number, with currency in it.
        cleaned_values = series.astype(str).str.strip()
        if cleaned_values.str.contains(r"[$€£¥,]", regex=True, na=False).any():
            stripped = cleaned_values.str.replace(_CURRENCY_RE, "", regex=True)
            stripped = stripped.str.replace(_THOUSANDS_RE, "", regex=True)
            numeric = pd.to_numeric(stripped, errors="coerce")
            # Only convert when most non-null values became numbers.
            original_non_null = cleaned_values.notna().sum()
            if original_non_null and numeric.notna().sum() / original_non_null >= 0.8:
                cleaned[column] = numeric
                continue

        # A text column that is really a date.
        if series.notna().any():
            parsed = pd.to_datetime(series, errors="coerce", format="mixed")
            if parsed.notna().sum() / series.notna().sum() >= 0.8:
                cleaned[column] = parsed

    return cleaned


def _column_type(series: pd.Series) -> str:
    """The inferred type of a column: number, date, categorical or text."""
    if pd.api.types.is_datetime64_any_dtype(series):
        return "date"
    if pd.api.types.is_numeric_dtype(series):
        return "number"
    if pd.api.types.is_bool_dtype(series):
        return "categorical"

    distinct = int(series.dropna().nunique())
    if distinct <= CATEGORICAL_MAX_DISTINCT:
        return "categorical"
    return "text"


def infer_schema(frame: pd.DataFrame) -> List[Dict[str, Any]]:
    """Describe each column: its name, its type and, for a categorical
    column, its distinct values."""
    columns: List[Dict[str, Any]] = []

    for column in frame.columns:
        series = frame[column]
        kind = _column_type(series)
        entry: Dict[str, Any] = {
            "name": str(column),
            "type": kind,
            "null_count": int(series.isna().sum()),
        }

        if kind == "number":
            numbers = series.dropna().astype(float)
            if not numbers.empty:
                entry["min"] = round(float(numbers.min()), 4)
                entry["max"] = round(float(numbers.max()), 4)
                entry["mean"] = round(float(numbers.mean()), 4)
        elif kind == "date":
            dates = series.dropna()
            if not dates.empty:
                entry["from"] = dates.min().isoformat()
                entry["to"] = dates.max().isoformat()
        else:
            counts = series.dropna().value_counts()
            entry["distinct_count"] = int(len(counts))
            if kind == "categorical":
                entry["values"] = [str(value) for value in counts.head(MAX_CATEGORY_VALUES).index]
            entry["null_heavy"] = bool(
                frame.shape[0] and series.isna().sum() / frame.shape[0] >= NULL_HEAVY_RATIO
            )

        columns.append(entry)

    return columns


# ---------------------------------------------------------------------------
# Step 5: compute findings
# ---------------------------------------------------------------------------

def _concentration(counts: pd.Series) -> Optional[float]:
    """The share of the total held by the largest single value."""
    total = float(counts.sum())
    if not total or counts.empty:
        return None
    return round(float(counts.iloc[0]) / total, 4)


def _trend_direction(series: pd.Series) -> Optional[str]:
    """Whether a numeric series is rising, falling or flat."""
    values = series.dropna().astype(float)
    if len(values) < 3:
        return None

    midpoint = len(values) // 2
    first = float(values.iloc[:midpoint].mean())
    second = float(values.iloc[midpoint:].mean())
    if first == second:
        return "flat"

    change = (second - first) / abs(first) if first else 0.0
    if change > 0.05:
        return "rising"
    if change < -0.05:
        return "falling"
    return "flat"


def compute_findings(frame: pd.DataFrame, schema: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    The aggregate statistics both consumers need, computed once.

    The totals, averages, unique counts, category breakdowns, concentration
    ratios, trend directions and outliers a deck or a chat answer can be
    built from, without touching the raw rows again.
    """
    findings: Dict[str, Any] = {
        "row_count": int(frame.shape[0]),
        "column_count": int(frame.shape[1]),
        "totals": {},
        "averages": {},
        "unique_counts": {},
        "category_breakdowns": {},
        "concentration": {},
        "trends": {},
        "outliers": {},
    }

    for entry in schema:
        name = entry["name"]
        if name not in frame.columns:
            continue
        series = frame[name]

        if entry["type"] == "number":
            numbers = series.dropna().astype(float)
            if numbers.empty:
                continue
            findings["totals"][name] = round(float(numbers.sum()), 4)
            findings["averages"][name] = round(float(numbers.mean()), 4)
            findings["unique_counts"][name] = int(numbers.nunique())

            # A value far from the mean, by a standard deviation.
            if len(numbers) >= 4:
                deviation = numbers.std()
                if deviation and deviation > 0:
                    extreme = numbers[(numbers - numbers.mean()).abs() > 3 * deviation]
                    if not extreme.empty:
                        findings["outliers"][name] = {
                            "count": int(len(extreme)),
                            "max": round(float(extreme.max()), 4),
                            "min": round(float(extreme.min()), 4),
                        }

        elif entry["type"] == "categorical":
            counts = series.dropna().value_counts()
            findings["unique_counts"][name] = int(len(counts))
            if not counts.empty:
                findings["category_breakdowns"][name] = {
                    str(value): int(count) for value, count in counts.head(MAX_CATEGORY_VALUES).items()
                }
                ratio = _concentration(counts)
                if ratio is not None:
                    findings["concentration"][name] = ratio

        elif entry["type"] == "date":
            dates = series.dropna()
            if not dates.empty:
                findings["trends"][name] = {
                    "from": dates.min().isoformat(),
                    "to": dates.max().isoformat(),
                    "span_days": int((dates.max() - dates.min()).days),
                }

    # A trend on the first numeric column, over the row order.
    for name, summary in findings["totals"].items():
        direction = _trend_direction(frame[name])
        if direction:
            findings["trends"][f"{name}_by_row"] = {"direction": direction}
            break

    return findings


# ---------------------------------------------------------------------------
# Step 6: the auto-summary
# ---------------------------------------------------------------------------

def build_auto_summary(
    sheet_name: str,
    schema: List[Dict[str, Any]],
    findings: Dict[str, Any],
) -> str:
    """
    A one-line description of a sheet, generated from the schema and the
    findings.

    Template-based rather than model-based: the list page has to render
    instantly and the line has to be the same every time the same file is
    uploaded.
    """
    numeric = [entry for entry in schema if entry["type"] == "number"]
    categorical = [entry for entry in schema if entry["type"] == "categorical"]
    dates = [entry for entry in schema if entry["type"] == "date"]

    row_count = findings.get("row_count", 0)
    parts = [f"{row_count:,} rows"]

    if numeric:
        names = ", ".join(entry["name"] for entry in numeric[:3])
        parts.append(f"{len(numeric)} numeric column{'s' if len(numeric) != 1 else ''} ({names})")

    if categorical:
        # The most useful line: how many distinct values a categorical
        # column holds, which is the "217 unique customers" of the example.
        widest = max(categorical, key=lambda entry: entry.get("distinct_count", 0))
        distinct = widest.get("distinct_count", 0)
        if distinct:
            parts.append(f"{distinct} distinct {widest['name']} values")

    if dates:
        parts.append(f"spanning {dates[0]['from'][:10]} to {dates[0]['to'][:10]}")

    return f"{sheet_name}: " + ", ".join(parts)


# ---------------------------------------------------------------------------
# The pipeline
# ---------------------------------------------------------------------------

def _sample_rows(frame: pd.DataFrame, count: int = DEFAULT_SAMPLE_ROWS) -> List[Dict[str, Any]]:
    """The first few rows, as plain JSON values."""
    rows: List[Dict[str, Any]] = []
    for record in frame.head(count).to_dict(orient="records"):
        row: Dict[str, Any] = {}
        for key, value in record.items():
            if value is None:
                row[str(key)] = None
            elif isinstance(value, (bool, int, str)):
                row[str(key)] = value
            elif isinstance(value, float):
                row[str(key)] = round(value, 4) if value == value else None
            elif isinstance(value, pd.Timestamp):
                row[str(key)] = value.isoformat()
            else:
                row[str(key)] = str(value)
        rows.append(row)
    return rows


def process_sheet(
    sheet_id: str,
    name: str,
    frame: pd.DataFrame,
    processing_notice: Optional[str] = None,
) -> Tuple[Dict[str, Any], pd.DataFrame]:
    """
    Run steps 3 to 6 over one sheet.

    Returns:
        The sheet record, and the cleaned frame.
    """
    cleaned = _clean_frame(frame)
    schema = infer_schema(cleaned)
    findings = compute_findings(cleaned, schema)
    auto_summary = build_auto_summary(name, schema, findings)

    record = {
        "id": sheet_id,
        "name": name,
        "row_count": int(cleaned.shape[0]),
        "column_count": int(cleaned.shape[1]),
        "schema": schema,
        "sample_rows": _sample_rows(cleaned),
        "findings": findings,
        "auto_summary": auto_summary,
        "status": "parsed",
        "error_reason": None,
        "sheet_class": classify_sheet(cleaned, name)["class"],
        "skip_reason": None,
        "processing_notice": processing_notice,
    }

    return record, cleaned


def process_workbook(path: str) -> Dict[str, Any]:
    """
    Run the whole pipeline over a file.

    Returns a dict with:
      - "sheets": the sheet records, each with its own status
      - "frames": the cleaned dataframe for each sheet, keyed by sheet id
      - "status": the workbook status
      - "error_reason": set when the workbook needs attention

    A sheet that fails does not fail the workbook: it is marked, and the
    sheets that worked are still usable.
    """
    try:
        validate_file(path)
    except SheetError as exc:
        # A file that cannot be read at all is a workbook that needs
        # attention, not a failed request: it still appears in the list.
        return {
            "sheets": [],
            "frames": {},
            "status": "needs_attention",
            "error_reason": exc.reason,
            "active_sheet_id": None,
        }

    try:
        raw_sheets = _read_sheets(path)
    except SheetError as exc:
        return {
            "sheets": [],
            "frames": {},
            "status": "needs_attention",
            "error_reason": exc.reason,
            "active_sheet_id": None,
        }

    sheets: List[Dict[str, Any]] = []
    frames: Dict[str, pd.DataFrame] = {}
    errors: List[str] = []
    processing_notice = (
        "Large file processed in chunks; aggregations use the complete dataset."
        if Path(path).stat().st_size >= LARGE_FILE_BYTES
        else None
    )

    for index, (name, frame) in enumerate(raw_sheets.items()):
        sheet_id = f"sheet_{index + 1}"
        classification = classify_sheet(frame, name)

        if classification["class"] == "not_data":
            record = {
                "id": sheet_id,
                "name": name,
                "row_count": int(frame.shape[0]) if frame is not None else 0,
                "column_count": int(frame.shape[1]) if frame is not None else 0,
                "schema": [],
                "sample_rows": [],
                "findings": {},
                "auto_summary": f"{name}: not a tabular sheet",
                "status": "skipped",
                "error_reason": classification["skip_reason"],
                "sheet_class": classification["class"],
                "skip_reason": classification["skip_reason"],
                "processing_notice": processing_notice,
            }
            sheets.append(record)
            continue

        try:
            record, cleaned = process_sheet(
                sheet_id, name, frame, processing_notice=processing_notice
            )
        except Exception as exc:  # noqa: BLE001 - one bad sheet must not lose the others
            logger.warning("Sheet '%s' could not be processed: %s", name, exc)
            errors.append(f"Sheet '{name}': {exc}")
            sheets.append({
                "id": sheet_id,
                "name": name,
                "row_count": 0,
                "column_count": 0,
                "schema": [],
                "sample_rows": [],
                "findings": {},
                "auto_summary": "",
                "status": "needs_attention",
                "error_reason": str(exc),
                "sheet_class": classification["class"],
                "skip_reason": None,
                "processing_notice": processing_notice,
            })
            continue

        sheets.append(record)
        frames[sheet_id] = cleaned

    usable = [sheet for sheet in sheets if sheet["status"] == "parsed"]

    if not usable:
        return {
            "sheets": sheets,
            "frames": frames,
            "status": "needs_attention",
            "error_reason": (
                "; ".join(errors)
                or "No sheet in this file contains a usable table."
            ),
            "active_sheet_id": None,
            "processing_notice": processing_notice,
        }

    has_skipped = any(sheet["status"] == "skipped" for sheet in sheets)
    has_errors = bool(errors) or any(sheet["status"] == "needs_attention" for sheet in sheets)
    return {
        "sheets": sheets,
        "frames": frames,
        "status": "partially_parsed" if has_skipped or has_errors else "parsed",
        "error_reason": "; ".join(errors) if errors else None,
        # The first tabular sheet is the default one to work with.
        "active_sheet_id": usable[0]["id"],
        "processing_notice": processing_notice,
    }

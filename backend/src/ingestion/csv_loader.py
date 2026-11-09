"""Handles reading and parsing uploaded CSV files into pandas DataFrames,"""

import logging
import csv
from pathlib import Path
from typing import Optional, Union

import pandas as pd

logger = logging.getLogger(__name__)

# Encodings attempted, in order, when reading an uploaded CSV.
ENCODINGS_TO_TRY = ("utf-8", "utf-8-sig", "latin-1")
HEADER_SCAN_ROWS = 10


def _header_row(sample: pd.DataFrame) -> int:
    """Choose the densest, mostly textual row from the initial sample."""
    best = 0
    best_score = float("-inf")
    for index, row in sample.iterrows():
        values = [value for value in row.tolist() if pd.notna(value) and str(value).strip()]
        if not values:
            continue
        text = [str(value).strip() for value in values]
        numeric = 0
        for value in text:
            try:
                float(value.replace(",", "").replace("$", "").replace("€", "").replace("£", ""))
                numeric += 1
            except ValueError:
                pass
        score = len(values) * 2 + len(values) - numeric - float(index) * 0.25
        if score > best_score:
            best, best_score = int(index), score
    return best


def _csv_header_row(path: Path, encoding: str) -> int:
    with path.open("r", encoding=encoding, newline="") as handle:
        rows = list(csv.reader(handle))[:HEADER_SCAN_ROWS]
    if not rows:
        raise EmptyCSVError(f"CSV file has no header row: {path.name}")
    return _header_row(pd.DataFrame(rows))


class CSVLoadError(Exception):
    """Base exception for all CSV loading failures."""


class EmptyCSVError(CSVLoadError):
    """Raised when the CSV file has no rows or columns of data."""


class CorruptedCSVError(CSVLoadError):
    """Raised when the CSV file cannot be parsed or decoded."""


def load_csv(file_path: Union[str, Path]) -> pd.DataFrame:
    """
    Load a CSV or Excel file from disk into a pandas DataFrame.

    Attempts several common text encodings for CSV files, or parses Excel
    workbooks (.xlsx, .xls) when matching extension is detected.

    Args:
        file_path: Path to the CSV or Excel file on disk.

    Returns:
        The parsed contents as a pandas DataFrame.

    Raises:
        FileNotFoundError: If the file does not exist.
        EmptyCSVError: If the file is empty or has no usable data.
        CorruptedCSVError: If the file cannot be parsed.
    """
    path = Path(file_path)

    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"Dataset file not found: {path}")

    if path.stat().st_size == 0:
        raise EmptyCSVError(f"Uploaded file is empty: {path.name}")

    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        try:
            sample = pd.read_excel(path, header=None, nrows=HEADER_SCAN_ROWS)
            df = pd.read_excel(path, header=_header_row(sample))
            if df.empty or df.shape[1] == 0:
                raise EmptyCSVError(f"Excel file contains no usable data: {path.name}")
            return df
        except Exception as exc:
            if isinstance(exc, EmptyCSVError):
                raise
            raise CorruptedCSVError(f"Excel file could not be parsed: {path.name}") from exc

    df: Optional[pd.DataFrame] = None
    last_error: Optional[Exception] = None

    for encoding in ENCODINGS_TO_TRY:
        try:
            header_row = _csv_header_row(path, encoding)
            df = pd.read_csv(
                path,
                encoding=encoding, header=0, skiprows=header_row,
                engine="python",
            )
            break
        except UnicodeDecodeError as exc:
            last_error = exc
            logger.warning("Failed to decode '%s' using encoding '%s'", path.name, encoding)
            continue
        except pd.errors.EmptyDataError as exc:
            raise EmptyCSVError(f"CSV file has no columns or data: {path.name}") from exc
        except pd.errors.ParserError as exc:
            raise CorruptedCSVError(f"CSV file could not be parsed: {path.name}") from exc

    if df is None:
        raise CorruptedCSVError(
            f"Could not decode CSV file '{path.name}' using any of {ENCODINGS_TO_TRY}"
        ) from last_error

    if df.empty or df.shape[1] == 0:
        raise EmptyCSVError(f"CSV file contains no usable data: {path.name}")

    return df


load_dataset = load_csv

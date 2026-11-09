"""Shared utility/helper functions: filename validation, unique filename"""

import re
import uuid
from pathlib import Path

ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".xls"}

# Characters kept in a human-readable filename slug.
_SLUG_STRIP_RE = re.compile(r"[^A-Za-z0-9_-]+")


def validate_csv_extension(filename: str) -> bool:
    """Return True if the given filename has an allowed extension (.csv, .xlsx, .xls)."""
    if not filename:
        return False
    return Path(filename).suffix.lower() in ALLOWED_EXTENSIONS


def validate_supported_extension(filename: str) -> bool:
    """Return True if the given filename has an allowed dataset extension."""
    return validate_csv_extension(filename)


def ensure_upload_dir(upload_dir: Path) -> Path:
    """Create the upload directory (and any parents) if it doesn't already exist."""
    upload_dir.mkdir(parents=True, exist_ok=True)
    return upload_dir


def slugify_filename(filename: str) -> str:
    """
    Turn an original filename into a short, filesystem-safe, human-readable slug.

    "Q1 Sales Report.csv" -> "Q1_Sales_Report"
    """
    stem = Path(filename).stem
    slug = _SLUG_STRIP_RE.sub("_", stem).strip("_")
    return slug[:48] or "dataset"


def generate_unique_filename(original_filename: str) -> str:
    """
    Generate a unique, collision-safe filename that preserves the original extension.

    The original name is kept as a readable prefix so uploaded datasets stay
    identifiable in the UI, e.g. "Q1_Sales_Report_1a2b3c4d.csv".
    """
    extension = Path(original_filename).suffix.lower()
    return f"{slugify_filename(original_filename)}_{uuid.uuid4().hex[:8]}{extension}"


def sanitize_filename(filename: str) -> str:
    """Strip any directory components from a filename to prevent path traversal."""
    return Path(filename).name

"""Coordinates workbook storage, processing, caching, and lifecycle state."""

import logging
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from src.workbook.workbook_cache import WorkbookCache
from src.ingestion.workbook_processor import process_workbook
from src.workbook.workbook_store import (
    STATUS_NEEDS_ATTENTION as STORE_NEEDS_ATTENTION,
    STATUS_PARSED as STORE_PARSED,
    STATUS_PARTIALLY_PARSED as STORE_PARTIALLY_PARSED,
    STATUS_STALE as STORE_STALE,
    WorkbookStore,
)

logger = logging.getLogger(__name__)

# How many matches a search returns. Enough to show the caller where the
# keyword lives, without sending the whole workbook back over the wire.
SEARCH_RESULT_LIMIT = 200


def _is_missing(value: Any) -> bool:
    """Whether a value is missing (None, NaN or pandas' own NA)."""
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        # A list or a dict is not something pandas can judge, and it is
        # certainly not missing.
        return False


class WorkbookNotFound(Exception):
    """Raised when a workbook id does not exist."""


class WorkbookService:
    """
    The workbooks in the app.

    Holds the metadata store, the dataframe cache, and the processing
    pipeline, and keeps them consistent with each other.
    """

    def __init__(self, store: WorkbookStore, cache: WorkbookCache):
        self.store = store
        self.cache = cache

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _public_sheet(sheet: Dict[str, Any], include_detail: bool = False) -> Dict[str, Any]:
        """The sheet as the client sees it."""
        public = {
            "id": sheet["id"],
            "name": sheet["name"],
            "row_count": sheet.get("row_count", 0),
            "column_count": sheet.get("column_count", 0),
            "auto_summary": sheet.get("auto_summary", ""),
            "status": sheet.get("status", "parsed"),
            "error_reason": sheet.get("error_reason"),
            "sheet_class": sheet.get("sheet_class", "tabular"),
            "skip_reason": sheet.get("skip_reason"),
            "processing_notice": sheet.get("processing_notice"),
        }
        if include_detail:
            public["schema"] = sheet.get("schema", [])
            public["sample_rows"] = sheet.get("sample_rows", [])
            public["findings"] = sheet.get("findings", {})
        return public

    @classmethod
    def _public_workbook(
        cls, workbook: Dict[str, Any], include_detail: bool = False
    ) -> Dict[str, Any]:
        """The workbook as the client sees it."""
        public = {
            "id": workbook["id"],
            "file_name": workbook["file_name"],
            "file_type": workbook["file_type"],
            "uploaded_at": workbook["uploaded_at"],
            "status": workbook["status"],
            "active_sheet_id": workbook.get("active_sheet_id"),
            "error_reason": workbook.get("error_reason"),
            "sheets": [cls._public_sheet(sheet, include_detail) for sheet in workbook.get("sheets", [])],
        }
        if include_detail:
            public["storage_path"] = workbook.get("storage_path")
            public["processing_notice"] = next(
                (
                    sheet.get("processing_notice")
                    for sheet in workbook.get("sheets", [])
                    if sheet.get("processing_notice")
                ),
                None,
            )
        return public

    def _require(self, workbook_id: str) -> Dict[str, Any]:
        workbook = self.store.get_workbook(workbook_id)
        if workbook is None:
            raise WorkbookNotFound(f"No workbook with id '{workbook_id}'.")
        return workbook

    # -- the lifecycle ------------------------------------------------------

    def create(
        self,
        file_name: str,
        storage_path: str,
        file_type: str = "csv",
        user_id: str = "local",
        file_data: Optional[bytes] = None,
    ) -> Dict[str, Any]:
        """
        Create a workbook and run the pipeline over its file.

        The record is written first, so a failure still leaves a workbook
        in the list — in the ``needs_attention`` state, with the reason.
        """
        workbook = self.store.create_workbook(
            file_name=file_name,
            file_type=file_type,
            storage_path=storage_path,
            file_data=file_data,
            user_id=user_id,
        )
        return self._process(workbook)

    def _process(self, workbook: Dict[str, Any]) -> Dict[str, Any]:
        """Run the processing pipeline and record the result."""
        workbook_id = workbook["id"]
        storage_path = workbook["storage_path"]

        self.store.update_workbook(workbook_id, status="processing")

        temporary_path = None
        try:
            source_path = storage_path
            if workbook.get("file_data") is not None:
                with tempfile.NamedTemporaryFile(
                    suffix=Path(workbook["file_name"]).suffix,
                    delete=False,
                ) as temporary:
                    temporary.write(workbook["file_data"])
                    temporary_path = Path(temporary.name)
                source_path = str(temporary_path)
            result = process_workbook(source_path)
        except Exception as exc:  # noqa: BLE001 - the record must survive any failure
            logger.exception("Processing failed for workbook %s", workbook_id)
            return self.store.update_workbook(
                workbook_id,
                status=STORE_NEEDS_ATTENTION,
                error_reason=str(exc),
            ) or self._require(workbook_id)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

        # Cache the cleaned frames, so the consumers never re-parse.
        for sheet_id, frame in result["frames"].items():
            self.cache.put(workbook_id, sheet_id, frame)

        status = (
            STORE_PARSED
            if result["status"] == "parsed"
            else STORE_PARTIALLY_PARSED
            if result["status"] == "partially_parsed"
            else STORE_NEEDS_ATTENTION
        )

        return self.store.update_workbook(
            workbook_id,
            status=status,
            sheets=result["sheets"],
            active_sheet_id=result.get("active_sheet_id"),
            error_reason=result.get("error_reason"),
        ) or self._require(workbook_id)

    def replace(
        self,
        workbook_id: str,
        file_name: str,
        storage_path: str,
        file_type: str = "csv",
        file_data: Optional[bytes] = None,
    ) -> Dict[str, Any]:
        """
        Replace a workbook's file and re-run the pipeline.

        The cached frames are dropped first, so nothing can be computed
        against the old file, and the new file's derived records are built
        from scratch.
        """
        workbook = self._require(workbook_id)

        self.cache.invalidate(workbook_id)

        updated = self.store.update_workbook(
            workbook_id,
            file_name=file_name,
            file_type=file_type,
            storage_path=storage_path,
            file_data=file_data,
            status="processing",
            error_reason=None,
        )

        return self._process(updated or workbook)

    def set_active_sheet(self, workbook_id: str, sheet_id: str) -> Dict[str, Any]:
        """Choose which sheet the consumers work with by default."""
        workbook = self._require(workbook_id)

        known = {sheet["id"] for sheet in workbook.get("sheets", [])}
        if sheet_id not in known:
            raise ValueError(
                f"'{sheet_id}' is not a sheet of this workbook. "
                f"It has: {', '.join(sorted(known)) or 'none'}."
            )

        updated = self.store.update_workbook(workbook_id, active_sheet_id=sheet_id)
        return updated or workbook

    def delete(self, workbook_id: str) -> None:
        """Remove a workbook, its raw file and its cache entry."""
        workbook = self._require(workbook_id)

        self.cache.invalidate(workbook_id)
        self.store.delete_workbook(workbook_id)

        # The raw file goes too, but a failure to remove it must not fail
        # the delete: the record is already gone.
        storage_path = workbook["storage_path"]
        if not storage_path.startswith("db://"):
            try:
                path = Path(storage_path)
                if path.exists() and path.is_file():
                    path.unlink()
                    logger.info("Removed the raw file for workbook %s", workbook_id)
            except OSError as exc:
                logger.warning(
                    "Could not remove the file for workbook %s: %s", workbook_id, exc
                )

    def delete_all(self) -> int:
        """
        Remove every workbook, its raw file and its cache entry.

        This is the destructive action behind "Clear all workbooks" in
        Settings. It returns how many workbooks were removed. A failure to
        remove one raw file does not stop the rest: the records are what
        matter, and the file is already orphaned at that point.
        """
        workbooks = self.store.list_workbooks()
        removed = 0

        for workbook in workbooks:
            workbook_id = workbook["id"]
            self.cache.invalidate(workbook_id)
            if self.store.delete_workbook(workbook_id):
                removed += 1

            try:
                path = Path(workbook["storage_path"])
                if path.exists() and path.is_file():
                    path.unlink()
            except OSError as exc:
                logger.warning(
                    "Could not remove the file for workbook %s: %s", workbook_id, exc
                )

        logger.info("Removed %d workbook(s) in a bulk delete.", removed)
        return removed

    def purge_older_than(self, retention_days: int) -> List[str]:
        """
        Remove the workbooks uploaded longer ago than the retention window.

        The window is in days, counted from the upload time. A retention of
        zero or less is meaningless, so it is ignored rather than purging
        everything.

        Returns:
            The ids of the workbooks that were removed.
        """
        if retention_days is None or retention_days <= 0:
            return []

        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=retention_days)
        removed: List[str] = []

        for workbook in self.store.list_workbooks():
            uploaded_at = workbook.get("uploaded_at")
            if not uploaded_at:
                continue
            try:
                stamp = datetime.fromisoformat(uploaded_at)
            except (TypeError, ValueError):
                continue
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            if stamp > cutoff:
                continue

            self.cache.invalidate(workbook["id"])
            if self.store.delete_workbook(workbook["id"]):
                removed.append(workbook["id"])

            try:
                path = Path(workbook["storage_path"])
                if path.exists() and path.is_file():
                    path.unlink()
            except OSError as exc:
                logger.warning(
                    "Could not remove the file for workbook %s: %s", workbook["id"], exc
                )

        logger.info(
            "Purged %d workbook(s) older than %d day(s).", len(removed), retention_days
        )
        return removed

    # -- reads --------------------------------------------------------------

    def list(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """The workbooks, newest first, in the shape the list page needs."""
        return [
            self._public_workbook(workbook)
            for workbook in self.store.list_workbooks(user_id)
        ]

    def get(self, workbook_id: str) -> Dict[str, Any]:
        """One workbook, with its sheets in full."""
        workbook = self._require(workbook_id)
        return self._public_workbook(workbook, include_detail=True)

    def search(self, keyword: str, limit: int = SEARCH_RESULT_LIMIT) -> Dict[str, Any]:
        """
        Search across the workbooks, from the outside in.

        The search runs in three passes, and reports what it found in each:

        1. the workbook itself — its file name and the summary of its first
           sheet;
        2. the sheets inside it — their names;
        3. the rows inside those sheets — the column names and the values.

        Only the third pass needs the data, so the workbooks are read one
        at a time and the first that answers the question is enough to
        show the caller where to look.

        The keyword is matched case-insensitively, and a value counts as a
        match when it contains the keyword as a substring. A number is
        matched as written, so "1213" finds 1213.48 but not 12.13.
        """
        needle = (keyword or "").strip().lower()
        if not needle:
            return {"keyword": keyword, "workbooks": [], "matches": [], "total": 0}

        matches: List[Dict[str, Any]] = []
        workbooks = self.store.list_workbooks()

        for workbook in workbooks:
            found = self._search_workbook(workbook, needle, limit)
            if found:
                matches.extend(found)

        return {
            "keyword": keyword,
            "workbooks": [
                {
                    "id": workbook["id"],
                    "file_name": workbook["file_name"],
                    "file_type": workbook["file_type"],
                    "status": workbook["status"],
                    "match_count": sum(
                        1 for match in matches if match["workbook_id"] == workbook["id"]
                    ),
                }
                for workbook in workbooks
                if any(match["workbook_id"] == workbook["id"] for match in matches)
            ],
            "matches": matches[:limit],
            "total": len(matches),
        }

    def _search_workbook(
        self, workbook: Dict[str, Any], needle: str, limit: int
    ) -> List[Dict[str, Any]]:
        """Search one workbook, from its name down into its rows."""
        found: List[Dict[str, Any]] = []
        workbook_id = workbook["id"]

        # Pass 1: the workbook itself.
        file_name = str(workbook.get("file_name") or "")
        if needle in file_name.lower():
            found.append(
                {
                    "workbook_id": workbook_id,
                    "file_name": file_name,
                    "scope": "workbook",
                    "sheet_id": None,
                    "sheet_name": None,
                    "field": "file name",
                    "value": file_name,
                }
            )

        sheets = workbook.get("sheets", []) or []

        # Pass 2: the sheets inside it.
        for sheet in sheets:
            sheet_name = str(sheet.get("name") or "")
            if needle in sheet_name.lower():
                found.append(
                    {
                        "workbook_id": workbook_id,
                        "file_name": file_name,
                        "scope": "sheet",
                        "sheet_id": sheet.get("id"),
                        "sheet_name": sheet_name,
                        "field": "sheet name",
                        "value": sheet_name,
                    }
                )

        # Pass 3: the rows inside the sheets. This needs the data, so a
        # sheet that cannot be read is skipped rather than failing the
        # whole search.
        for sheet in sheets:
            if len(found) >= limit:
                break

            sheet_id = sheet.get("id")
            if not sheet_id:
                continue

            try:
                frame = self.get_frame(workbook_id, sheet_id)
            except Exception:  # noqa: BLE001 - an unreadable sheet is skipped
                logger.warning(
                    "Could not read sheet %s of workbook %s while searching.",
                    sheet_id,
                    workbook_id,
                    exc_info=True,
                )
                continue

            found.extend(
                self._search_frame(
                    workbook_id, file_name, sheet, frame, needle, limit
                )
            )

        return found[:limit]

    @staticmethod
    def _search_frame(
        workbook_id: str,
        file_name: str,
        sheet: Dict[str, Any],
        frame: pd.DataFrame,
        needle: str,
        limit: int,
    ) -> List[Dict[str, Any]]:
        """Search one sheet's rows for the keyword."""
        found: List[Dict[str, Any]] = []
        sheet_id = sheet.get("id")
        sheet_name = str(sheet.get("name") or "")

        # The column names are worth matching on their own: someone looking
        # for "revenue" wants the column that holds it, even when no row
        # currently has that word in it.
        for column in frame.columns:
            if len(found) >= limit:
                break
            if needle in str(column).lower():
                found.append(
                    {
                        "workbook_id": workbook_id,
                        "file_name": file_name,
                        "scope": "column",
                        "sheet_id": sheet_id,
                        "sheet_name": sheet_name,
                        "field": "column",
                        "value": str(column),
                        "row_index": None,
                        "row": None,
                    }
                )

        # Then the values themselves.
        for index, record in frame.iterrows():
            if len(found) >= limit:
                break

            for column, value in record.items():
                if value is None:
                    continue
                if isinstance(value, float) and value != value:
                    continue  # NaN

                text = str(value)
                if needle not in text.lower():
                    continue

                found.append(
                    {
                        "workbook_id": workbook_id,
                        "file_name": file_name,
                        "scope": "row",
                        "sheet_id": sheet_id,
                        "sheet_name": sheet_name,
                        "field": str(column),
                        "value": text,
                        "row_index": int(index) if isinstance(index, (int,)) else str(index),
                        "row": {
                            str(key): (None if _is_missing(item) else str(item))
                            for key, item in record.items()
                        },
                    }
                )
                break  # One hit per row is enough to show where it is.

        return found

    def get_frame(
        self, workbook_id: str, sheet_id: Optional[str] = None
    ) -> pd.DataFrame:
        """
        The dataframe for a sheet, from the cache when it is there.

        A sheet that is not cached is re-read from the file, so a workbook
        whose cache was emptied by a restart still works.
        """
        workbook = self._require(workbook_id)

        target = sheet_id or workbook.get("active_sheet_id")
        if not target:
            raise ValueError("This workbook has no sheet to work with.")

        cached = self.cache.get(workbook_id, target)
        if cached is not None:
            return cached

        # Not cached: re-parse the file and cache what comes out.
        logger.info("Workbook %s sheet %s is not cached; re-parsing.", workbook_id, target)
        temporary_path = None
        source_path = workbook["storage_path"]
        if workbook.get("file_data") is not None:
            with tempfile.NamedTemporaryFile(
                suffix=Path(workbook["file_name"]).suffix,
                delete=False,
            ) as temporary:
                temporary.write(workbook["file_data"])
                temporary_path = Path(temporary.name)
            source_path = str(temporary_path)
        try:
            result = process_workbook(source_path)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
        for sheet_key, frame in result["frames"].items():
            self.cache.put(workbook_id, sheet_key, frame)

        frame = self.cache.get(workbook_id, target)
        if frame is None:
            raise ValueError(
                f"Sheet '{target}' could not be read from this workbook."
            )
        return frame

    def get_sheet(self, workbook_id: str, sheet_id: str) -> Dict[str, Any]:
        """One sheet's record, in full."""
        workbook = self._require(workbook_id)
        for sheet in workbook.get("sheets", []):
            if sheet["id"] == sheet_id:
                return self._public_sheet(sheet, include_detail=True)
        raise ValueError(f"'{sheet_id}' is not a sheet of this workbook.")

    def mark_stale(self) -> int:
        """Mark every parsed workbook stale, and empty the cache."""
        self.cache.clear()
        return self.store.mark_all_stale()

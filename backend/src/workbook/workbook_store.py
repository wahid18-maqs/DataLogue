"""The SQLite store for workbook metadata and uploaded file contents."""

import json
import logging
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# The lifecycle states a workbook can be in.
STATUS_UPLOADING = "uploading"
STATUS_PROCESSING = "processing"
STATUS_PARSED = "parsed"
STATUS_PARTIALLY_PARSED = "partially_parsed"
STATUS_NEEDS_ATTENTION = "needs_attention"
STATUS_STALE = "stale"

VALID_STATUSES = {
    STATUS_UPLOADING,
    STATUS_PROCESSING,
    STATUS_PARSED,
    STATUS_PARTIALLY_PARSED,
    STATUS_NEEDS_ATTENTION,
    STATUS_STALE,
}

# The schema of the metadata database. Sheets are stored as JSON on the
# workbook row, because they are always read and written together.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS workbooks (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL DEFAULT 'local',
    file_name       TEXT NOT NULL,
    file_type       TEXT NOT NULL,
    uploaded_at     TEXT NOT NULL,
    storage_path    TEXT NOT NULL,
    file_data       BLOB,
    status          TEXT NOT NULL,
    sheets          TEXT NOT NULL DEFAULT '[]',
    active_sheet_id TEXT,
    error_reason    TEXT
);

CREATE INDEX IF NOT EXISTS idx_workbooks_uploaded_at
    ON workbooks (uploaded_at DESC);
"""


def _now() -> str:
    """The current time, as an ISO-8601 string."""
    return datetime.now(tz=timezone.utc).isoformat()


class WorkbookStore:
    """
    The workbook and sheet records.

    A single connection is shared, guarded by a lock: SQLite writes are
    serialised, and the API is called from request threads as well as from
    the background thread that runs the processing pipeline.
    """

    def __init__(self, database_path: Path):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            str(self.database_path), check_same_thread=False
        )
        self._connection.row_factory = sqlite3.Row
        with self._lock:
            self._connection.executescript(_SCHEMA)
            columns = {
                row["name"]
                for row in self._connection.execute("PRAGMA table_info(workbooks)")
            }
            if "file_data" not in columns:
                self._connection.execute("ALTER TABLE workbooks ADD COLUMN file_data BLOB")
            self._connection.commit()

    # -- row helpers --------------------------------------------------------

    @staticmethod
    def _row_to_workbook(row: sqlite3.Row) -> Dict[str, Any]:
        """Turn a database row into a workbook dict."""
        try:
            sheets = json.loads(row["sheets"])
        except (TypeError, ValueError):
            sheets = []

        return {
            "id": row["id"],
            "user_id": row["user_id"],
            "file_name": row["file_name"],
            "file_type": row["file_type"],
            "uploaded_at": row["uploaded_at"],
            "storage_path": row["storage_path"],
            "file_data": row["file_data"],
            "status": row["status"],
            "sheets": sheets,
            "active_sheet_id": row["active_sheet_id"],
            "error_reason": row["error_reason"],
        }

    # -- writes -------------------------------------------------------------

    def create_workbook(
        self,
        file_name: str,
        file_type: str,
        storage_path: str,
        file_data: Optional[bytes] = None,
        user_id: str = "local",
        workbook_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a workbook record in the ``uploading`` state."""
        record = {
            "id": workbook_id or uuid.uuid4().hex,
            "user_id": user_id,
            "file_name": file_name,
            "file_type": file_type,
            "uploaded_at": _now(),
            "storage_path": str(storage_path),
            "file_data": file_data,
            "status": STATUS_UPLOADING,
            "sheets": [],
            "active_sheet_id": None,
            "error_reason": None,
        }

        with self._lock:
            self._connection.execute(
                """
                INSERT INTO workbooks
                    (id, user_id, file_name, file_type, uploaded_at,
                     storage_path, file_data, status, sheets, active_sheet_id, error_reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["id"],
                    record["user_id"],
                    record["file_name"],
                    record["file_type"],
                    record["uploaded_at"],
                    record["storage_path"],
                    file_data,
                    record["status"],
                    json.dumps([]),
                    None,
                    None,
                ),
            )
            self._connection.commit()

        logger.info("Created workbook %s for '%s'", record["id"], file_name)
        return record

    def update_workbook(self, workbook_id: str, **fields: Any) -> Optional[Dict[str, Any]]:
        """
        Update a workbook's fields and return the updated record.

        ``sheets`` may be given as a list, which is stored as JSON.
        """
        allowed = {
            "status",
            "sheets",
            "active_sheet_id",
            "error_reason",
            "file_name",
            "file_type",
            "storage_path",
            "file_data",
        }

        assignments: List[str] = []
        values: List[Any] = []

        for key, value in fields.items():
            if key not in allowed:
                continue
            assignments.append(f"{key} = ?")
            if key == "sheets":
                values.append(json.dumps(value, default=str))
            else:
                values.append(value)

        if not assignments:
            return self.get_workbook(workbook_id)

        with self._lock:
            self._connection.execute(
                f"UPDATE workbooks SET {', '.join(assignments)} WHERE id = ?",
                (*values, workbook_id),
            )
            self._connection.commit()

        return self.get_workbook(workbook_id)

    def delete_workbook(self, workbook_id: str) -> bool:
        """Remove a workbook record. Returns whether anything was removed."""
        with self._lock:
            cursor = self._connection.execute(
                "DELETE FROM workbooks WHERE id = ?", (workbook_id,)
            )
            self._connection.commit()
            return cursor.rowcount > 0

    # -- reads --------------------------------------------------------------

    def get_workbook(self, workbook_id: str) -> Optional[Dict[str, Any]]:
        """One workbook, or None when it does not exist."""
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM workbooks WHERE id = ?", (workbook_id,)
            ).fetchone()

        if row is None:
            return None
        return self._row_to_workbook(row)

    def list_workbooks(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Every workbook, newest first."""
        query = "SELECT * FROM workbooks"
        values: List[Any] = []
        if user_id is not None:
            query += " WHERE user_id = ?"
            values.append(user_id)

        query += " ORDER BY uploaded_at DESC"

        with self._lock:
            rows = self._connection.execute(query, values).fetchall()

        return [self._row_to_workbook(row) for row in rows]

    def find_by_storage_path(self, storage_path: str) -> Optional[Dict[str, Any]]:
        """The workbook that owns a given file, if there is one."""
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM workbooks WHERE storage_path = ?", (storage_path,)
            ).fetchone()

        if row is None:
            return None
        return self._row_to_workbook(row)

    def mark_all_stale(self) -> int:
        """Mark every parsed workbook stale. Used when the app starts up."""
        with self._lock:
            cursor = self._connection.execute(
                """
                UPDATE workbooks SET status = ?
                WHERE status IN (?, ?)
                """,
                (STATUS_STALE, STATUS_PARSED, STATUS_PROCESSING),
            )
            self._connection.commit()
            return cursor.rowcount

    def close(self) -> None:
        """Close the underlying connection."""
        with self._lock:
            self._connection.close()

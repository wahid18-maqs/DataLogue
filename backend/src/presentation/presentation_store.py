"""SQLite storage for generated PowerPoint artifacts and deck plans."""

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


class PresentationStore:
    """Persists PPTX bytes and their structured plans in one SQLite database."""

    def __init__(self, database_path: Path):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            str(self.database_path), check_same_thread=False
        )
        self._connection.row_factory = sqlite3.Row
        with self._lock:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS presentations (
                    filename TEXT PRIMARY KEY,
                    workbook_id TEXT,
                    sheet_id TEXT,
                    pptx_data BLOB NOT NULL,
                    plan_json TEXT NOT NULL,
                    settings_json TEXT NOT NULL DEFAULT '{}',
                    feedback_json TEXT NOT NULL DEFAULT '[]',
                    stale INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                )
                """
            )
            columns = {
                row["name"]
                for row in self._connection.execute("PRAGMA table_info(presentations)")
            }
            for name, definition in (
                ("workbook_id", "TEXT"),
                ("sheet_id", "TEXT"),
                ("settings_json", "TEXT NOT NULL DEFAULT '{}'"),
                ("feedback_json", "TEXT NOT NULL DEFAULT '[]'"),
                ("stale", "INTEGER NOT NULL DEFAULT 0"),
            ):
                if name not in columns:
                    self._connection.execute(
                        f"ALTER TABLE presentations ADD COLUMN {name} {definition}"
                    )
            self._connection.commit()

    def save(
        self,
        filename: str,
        pptx_data: bytes,
        plan: Dict[str, Any],
        workbook_id: Optional[str] = None,
        sheet_id: Optional[str] = None,
        settings: Optional[Dict[str, Any]] = None,
        feedback: Optional[list] = None,
    ) -> None:
        """Insert or replace one generated presentation artifact."""
        with self._lock:
            self._connection.execute(
                """
                INSERT OR REPLACE INTO presentations
                    (filename, workbook_id, sheet_id, pptx_data, plan_json,
                     settings_json, feedback_json, stale, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (
                    filename,
                    workbook_id,
                    sheet_id,
                    pptx_data,
                    json.dumps(plan, default=str),
                    json.dumps(settings or {}, default=str),
                    json.dumps(feedback or [], default=str),
                    _now(),
                ),
            )
            self._connection.commit()

    def get_for_workbook(self, workbook_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM presentations WHERE workbook_id = ? "
                "ORDER BY created_at DESC LIMIT 1",
                (workbook_id,),
            ).fetchone()
        if row is None:
            return None
        try:
            return {
                "filename": row["filename"],
                "workbook_id": row["workbook_id"],
                "sheet_id": row["sheet_id"],
                "deck": json.loads(row["plan_json"]),
                "settings": json.loads(row["settings_json"] or "{}"),
                "feedback": json.loads(row["feedback_json"] or "[]"),
                "stale": bool(row["stale"]),
                "created_at": row["created_at"],
            }
        except (TypeError, ValueError, json.JSONDecodeError):
            return None

    def mark_workbook_stale(self, workbook_id: str) -> None:
        with self._lock:
            self._connection.execute(
                "UPDATE presentations SET stale = 1 WHERE workbook_id = ?",
                (workbook_id,),
            )
            self._connection.commit()

    def update_feedback(self, filename: str, feedback: list) -> None:
        with self._lock:
            self._connection.execute(
                "UPDATE presentations SET feedback_json = ? WHERE filename = ?",
                (json.dumps(feedback, default=str), filename),
            )
            self._connection.commit()

    def get_workbook_id_for_filename(self, filename: str) -> Optional[str]:
        with self._lock:
            row = self._connection.execute(
                "SELECT workbook_id FROM presentations WHERE filename = ?",
                (filename,),
            ).fetchone()
        return None if row is None else row["workbook_id"]

    def get_pptx(self, filename: str) -> Optional[bytes]:
        """Return the rendered PPTX bytes for a filename."""
        with self._lock:
            row = self._connection.execute(
                "SELECT pptx_data FROM presentations WHERE filename = ?",
                (filename,),
            ).fetchone()
        return None if row is None else bytes(row["pptx_data"])

    def get_plan(self, filename: str) -> Optional[Dict[str, Any]]:
        """Return the structured plan for a filename."""
        with self._lock:
            row = self._connection.execute(
                "SELECT plan_json FROM presentations WHERE filename = ?",
                (filename,),
            ).fetchone()
        if row is None:
            return None
        try:
            return json.loads(row["plan_json"])
        except (TypeError, ValueError):
            return None

    def get(self, filename: str) -> Optional[Tuple[bytes, Dict[str, Any]]]:
        """Return both artifact parts, or None when it is unknown."""
        with self._lock:
            row = self._connection.execute(
                "SELECT pptx_data, plan_json FROM presentations WHERE filename = ?",
                (filename,),
            ).fetchone()
        if row is None:
            return None
        try:
            plan = json.loads(row["plan_json"])
        except (TypeError, ValueError):
            return None
        return bytes(row["pptx_data"]), plan

    def import_legacy_directory(self, directory: Path) -> int:
        """Import existing PPTX/plan sidecars from the former folder store."""
        imported = 0
        for pptx_path in directory.glob("*.pptx"):
            plan_path = pptx_path.with_suffix(".plan.json")
            if not plan_path.exists():
                continue
            try:
                plan = json.loads(plan_path.read_text(encoding="utf-8"))
                self.save(pptx_path.name, pptx_path.read_bytes(), plan)
                imported += 1
            except (OSError, ValueError):
                continue
        return imported

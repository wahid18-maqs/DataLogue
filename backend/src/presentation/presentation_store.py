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
                    pptx_data BLOB NOT NULL,
                    plan_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            self._connection.commit()

    def save(self, filename: str, pptx_data: bytes, plan: Dict[str, Any]) -> None:
        """Insert or replace one generated presentation artifact."""
        with self._lock:
            self._connection.execute(
                """
                INSERT OR REPLACE INTO presentations
                    (filename, pptx_data, plan_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (filename, pptx_data, json.dumps(plan, default=str), _now()),
            )
            self._connection.commit()

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

"""The parsed-dataframe cache."""

import logging
import threading
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

# How many workbooks are kept in the cache. The least recently used is
# evicted first; its uploaded bytes remain in SQLite, so it can be re-parsed.
DEFAULT_MAX_WORKBOOKS = 16


class WorkbookCache:
    """
    A bounded, in-memory cache of parsed dataframes.

    Keyed by workbook id, holding one dataframe per sheet.
    """

    def __init__(self, max_workbooks: int = DEFAULT_MAX_WORKBOOKS):
        self.max_workbooks = max_workbooks
        self._lock = threading.RLock()
        # workbook id -> {sheet id -> dataframe}
        self._frames: "OrderedDict[str, Dict[str, pd.DataFrame]]" = OrderedDict()

    def put(self, workbook_id: str, sheet_id: str, frame: pd.DataFrame) -> None:
        """Cache one sheet's dataframe."""
        with self._lock:
            sheets = self._frames.get(workbook_id)
            if sheets is None:
                sheets = {}
                self._frames[workbook_id] = sheets
            sheets[sheet_id] = frame
            self._frames.move_to_end(workbook_id)
            self._evict()

    def get(self, workbook_id: str, sheet_id: str) -> Optional[pd.DataFrame]:
        """One sheet's dataframe, or None when it is not cached."""
        with self._lock:
            sheets = self._frames.get(workbook_id)
            if not sheets:
                return None
            frame = sheets.get(sheet_id)
            if frame is None:
                return None
            # Touch it: it is now the most recently used.
            self._frames.move_to_end(workbook_id)
            return frame

    def get_workbook(self, workbook_id: str) -> Optional[Dict[str, pd.DataFrame]]:
        """Every cached sheet of a workbook, or None when it is not cached."""
        with self._lock:
            sheets = self._frames.get(workbook_id)
            return dict(sheets) if sheets else None

    def invalidate(self, workbook_id: str) -> None:
        """Drop a workbook's cached frames — used when a file is replaced."""
        with self._lock:
            if self._frames.pop(workbook_id, None) is not None:
                logger.info("Invalidated the cache for workbook %s", workbook_id)

    def clear(self) -> None:
        """Drop every cached frame."""
        with self._lock:
            self._frames.clear()

    def is_cached(self, workbook_id: str, sheet_id: Optional[str] = None) -> bool:
        """Whether a workbook (or one of its sheets) is cached."""
        with self._lock:
            sheets = self._frames.get(workbook_id)
            if not sheets:
                return False
            if sheet_id is None:
                return True
            return sheet_id in sheets

    def _evict(self) -> None:
        """Drop the least recently used workbooks over the limit."""
        while len(self._frames) > self.max_workbooks:
            evicted_id, _ = self._frames.popitem(last=False)
            logger.info("Evicted workbook %s from the dataframe cache", evicted_id)

    def stats(self) -> Dict[str, Any]:
        """A summary of what is cached, for the diagnostics endpoint."""
        with self._lock:
            return {
                "workbooks": len(self._frames),
                "sheets": sum(len(sheets) for sheets in self._frames.values()),
                "max_workbooks": self.max_workbooks,
            }

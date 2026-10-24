"""Shared SQLite cache of the Arbeitnow feed, geocoding results and the shared request-rate slot.

The feed is large (megabytes per page), so it is downloaded once and shared between processes:
``ensure_feed`` is single-flight via ``BEGIN IMMEDIATE`` (other processes wait on the write lock, then
find a fresh feed). Per row, title+tags and the plain-text description are stored so matching never
re-parses HTML.
"""

import json
import logging
import re
import sqlite3
import time
from collections.abc import Callable, Iterable
from pathlib import Path

from .mapping import F_DESCRIPTION, F_SLUG, html_to_text, title_and_tags

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1
MISSING = object()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS feed_item (
    position INTEGER PRIMARY KEY,
    slug TEXT UNIQUE,
    title_tags TEXT,
    description TEXT,
    data TEXT
);
CREATE TABLE IF NOT EXISTS feed_meta (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    fetched_at REAL
);
CREATE TABLE IF NOT EXISTS geocode (
    key TEXT PRIMARY KEY,
    lat REAL,
    lon REAL,
    looked_up_at REAL
);
CREATE TABLE IF NOT EXISTS rate (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    last_request REAL
);
"""


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def _now() -> float:
    return time.time()


_LOCK_CODES = {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}
_CORRUPT_CODES = {sqlite3.SQLITE_NOTADB, sqlite3.SQLITE_CORRUPT}


class _Unusable(Exception):
    """The cache file has a foreign/old schema and must be recreated."""


class Cache:
    def __init__(self, path: Path, busy_timeout: float = 300.0) -> None:
        self.path = Path(path)
        self.busy_timeout = busy_timeout
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = self._open_with_recovery()

    def _open_with_recovery(self) -> sqlite3.Connection:
        """Open the cache; recreate the file only if it is genuinely unusable.

        Busy/locked errors (another process initialising or holding the file) are retried until the busy
        timeout is used up and then propagate; they never delete the file. Only a corrupt/foreign file
        (NOTADB/CORRUPT) or an outdated schema is deleted and recreated.
        """
        deadline = time.monotonic() + self.busy_timeout
        recreated = False
        while True:
            try:
                return self._open()
            except _Unusable:
                unusable = True
            except sqlite3.DatabaseError as exc:
                code = getattr(exc, "sqlite_errorcode", None)
                if code in _LOCK_CODES or (code is None and "locked" in str(exc)):
                    if time.monotonic() >= deadline:
                        raise
                    _sleep(0.05)
                    continue
                if code not in _CORRUPT_CODES:
                    raise
                unusable = True
            if unusable and recreated:
                raise sqlite3.DatabaseError("Arbeitnow cache cannot be recreated")
            recreated = True
            self._delete_files()

    # --- connection handling -----------------------------------------------------------

    def _open(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=self.busy_timeout, isolation_level=None)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version == SCHEMA_VERSION:
                return conn
            if version == 0 and conn.execute("SELECT count(*) FROM sqlite_master").fetchone()[0] == 0:
                self._init_schema(conn)  # brand-new file (possibly raced by another process)
                return conn
            raise _Unusable
        except BaseException:
            conn.close()
            raise

    @staticmethod
    def _init_schema(conn: sqlite3.Connection) -> None:
        conn.execute("BEGIN IMMEDIATE")
        try:
            if conn.execute("PRAGMA user_version").fetchone()[0] == 0:
                for statement in _SCHEMA.split(";"):
                    if statement.strip():
                        conn.execute(statement)
                conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise

    def _delete_files(self) -> None:
        for suffix in ("", "-wal", "-shm"):
            Path(str(self.path) + suffix).unlink(missing_ok=True)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Cache":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # --- feed ----------------------------------------------------------------------------

    def _fetched_at(self) -> float | None:
        row = self._conn.execute("SELECT fetched_at FROM feed_meta WHERE id = 1").fetchone()
        return row[0] if row else None

    def _is_fresh(self, fetched_at: float | None, max_age_seconds: float) -> bool:
        return fetched_at is not None and 0 <= _now() - fetched_at < max_age_seconds

    def ensure_feed(self, max_age_seconds: float, fetch: Callable[[], Iterable[dict]]) -> None:
        """Make sure the cached feed is younger than ``max_age_seconds``; reload via ``fetch`` otherwise.

        Single-flight across processes. If the reload fails and an older feed exists, that one is kept.
        """
        if self._is_fresh(self._fetched_at(), max_age_seconds):
            return
        conn = self._conn
        conn.execute("BEGIN IMMEDIATE")
        previous: float | None = None
        try:
            previous = self._fetched_at()
            if self._is_fresh(previous, max_age_seconds):
                conn.execute("COMMIT")
                return
            conn.execute("DELETE FROM feed_item")
            inserted = 0
            for item in fetch():
                slug = item.get(F_SLUG)
                if not isinstance(slug, str) or not slug:
                    continue  # unusable without a slug (would collapse into one row)
                cursor = conn.execute(
                    "INSERT OR IGNORE INTO feed_item (slug, title_tags, description, data) VALUES (?, ?, ?, ?)",
                    (
                        slug,
                        title_and_tags(item),
                        html_to_text(item.get(F_DESCRIPTION)),
                        json.dumps(item),
                    ),
                )
                inserted += cursor.rowcount
            if inserted == 0 and previous is not None:
                conn.execute("ROLLBACK")
                log.warning("Arbeitnow feed refresh returned no items, keeping the cached feed")
                return
            conn.execute(
                "INSERT INTO feed_meta (id, fetched_at) VALUES (1, ?) "
                "ON CONFLICT(id) DO UPDATE SET fetched_at = excluded.fetched_at",
                (_now(),),
            )
            conn.execute("COMMIT")
        except Exception as exc:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            if previous is None:
                raise
            log.warning("Arbeitnow feed refresh failed, using the cached feed: %s", exc)
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise

    def matching(self, pattern: re.Pattern[str], include_description: bool) -> list[tuple[dict, str | None]]:
        """Postings whose title/tags (or, optionally, description) match, in feed order."""
        hits: list[tuple[dict, str | None]] = []
        cursor = self._conn.execute("SELECT title_tags, description, data FROM feed_item ORDER BY position")
        for title_tags, description, data in cursor:
            if pattern.search(title_tags or "") or (
                include_description and description and pattern.search(description)
            ):
                hits.append((json.loads(data), description))
        return hits

    # --- geocoding -----------------------------------------------------------------------

    def geocode_get(self, key: str) -> "tuple[float, float] | None | object":
        """Cached coordinates; ``None`` for a stored 'no result'; ``MISSING`` if never looked up."""
        row = self._conn.execute("SELECT lat, lon FROM geocode WHERE key = ?", (key,)).fetchone()
        if row is None:
            return MISSING
        lat, lon = row
        return None if lat is None or lon is None else (lat, lon)

    def geocode_put(self, key: str, coords: tuple[float, float] | None) -> None:
        lat, lon = coords if coords is not None else (None, None)
        conn = self._conn
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                "INSERT INTO geocode (key, lat, lon, looked_up_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET lat = excluded.lat, lon = excluded.lon, "
                "looked_up_at = excluded.looked_up_at",
                (key, lat, lon, _now()),
            )
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise

    # --- shared request rate -------------------------------------------------------------

    def wait_rate_slot(self, interval: float = 1.0) -> None:
        """Block until ``interval`` seconds passed since the last request of any process, then claim the slot.

        The write lock is held while sleeping, so concurrent processes queue up behind each other.
        """
        conn = self._conn
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute("SELECT last_request FROM rate WHERE id = 1").fetchone()
            if row is not None and row[0] is not None:
                remaining = interval - (_now() - row[0])
                if 0 < remaining <= interval:  # a last_request in the future (clock jump) is ignored
                    _sleep(remaining)
            conn.execute(
                "INSERT INTO rate (id, last_request) VALUES (1, ?) "
                "ON CONFLICT(id) DO UPDATE SET last_request = excluded.last_request",
                (_now(),),
            )
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise

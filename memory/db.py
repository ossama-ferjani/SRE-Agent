"""SQLite database initialisation and connection management for the SRE agent.

Supports two backends selected by environment variable:

  • Local SQLite file (default) — standard library sqlite3, no extra deps.
  • Docker sqld server (libSQL)  — set SQLITE_URL=http://localhost:8082
    Requires: pip install libsql-experimental

FTS5 availability is auto-detected; falls back to LIKE queries silently.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default local DB path — can be patched in tests
DB_PATH: Path = Path.home() / ".sre_agent" / "memory.db"

# Tracks FTS5 availability — set during init_db()
FTS5_AVAILABLE: bool = True

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


# ── Backend detection ──────────────────────────────────────────────────────────

def _sqld_url() -> str | None:
    """Return the sqld server URL from SQLITE_URL env var, or None for local mode."""
    return os.environ.get("SQLITE_URL") or None


def _using_sqld() -> bool:
    """True when SQLITE_URL is configured and libsql should be used."""
    return _sqld_url() is not None


# ── libSQL / sqld connection ───────────────────────────────────────────────────

def _get_sqld_conn():
    """Open an embedded-replica libsql connection synced with the Docker sqld server.

    The local file under DB_PATH acts as a read cache; writes go to sqld.
    """
    try:
        import libsql_experimental as libsql  # type: ignore[import]
    except ImportError as exc:
        raise ImportError(
            "libsql-experimental is required for Docker SQLite mode. "
            "Run: pip install libsql-experimental"
        ) from exc

    url = _sqld_url()
    auth_token = os.environ.get("SQLITE_AUTH_TOKEN", "")

    db_file = DB_PATH if isinstance(DB_PATH, Path) else Path(DB_PATH)
    if str(db_file) != ":memory:":
        db_file.parent.mkdir(parents=True, exist_ok=True)

    conn = libsql.connect(str(db_file), sync_url=url, auth_token=auth_token)
    try:
        conn.sync()
    except Exception as exc:
        logger.warning("sqld sync warning (non-fatal): %s", exc)

    return conn


# ── Local sqlite3 connection ───────────────────────────────────────────────────

def _get_local_conn() -> sqlite3.Connection:
    """Open a standard sqlite3 connection with Row factory."""
    db_file = DB_PATH if isinstance(DB_PATH, Path) else Path(DB_PATH)
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    return conn


# ── Row normalisation ──────────────────────────────────────────────────────────

def row_to_dict(row: Any) -> dict[str, Any]:
    """Convert a sqlite3.Row or libsql row to a plain Python dict.

    libsql rows expose columns via .keys() / index access; sqlite3.Row
    supports dict() directly. Both paths are handled here.
    """
    if row is None:
        return {}
    try:
        return dict(row)
    except (TypeError, ValueError):
        pass
    # libsql fallback: rows support column-name indexing
    if hasattr(row, "keys"):
        return {k: row[k] for k in row.keys()}
    # Last resort: assume it's index-addressable with a description
    raise TypeError(f"Cannot convert row of type {type(row)} to dict")


# ── Schema initialisation ──────────────────────────────────────────────────────

def init_db() -> None:
    """Initialise the database schema. Safe to call multiple times (idempotent)."""
    global FTS5_AVAILABLE

    db_file = DB_PATH if isinstance(DB_PATH, Path) else Path(DB_PATH)
    if str(db_file) != ":memory:" and not _using_sqld():
        db_file.parent.mkdir(parents=True, exist_ok=True)

    schema_sql = _SCHEMA_PATH.read_text()

    conn = get_conn()
    try:
        try:
            _exec_script(conn, schema_sql)
            FTS5_AVAILABLE = True
        except Exception as exc:
            if "fts5" in str(exc).lower():
                logger.warning(
                    "FTS5 not available in this SQLite build — "
                    "falling back to LIKE queries for memory search."
                )
                FTS5_AVAILABLE = False
                _init_without_fts5(conn)
            else:
                raise
    finally:
        conn.close()


def _exec_script(conn: Any, sql: str) -> None:
    """Execute a multi-statement SQL script on either a sqlite3 or libsql connection."""
    if hasattr(conn, "executescript"):
        conn.executescript(sql)
        if hasattr(conn, "commit"):
            conn.commit()
    else:
        # libsql connections may only expose execute()
        for statement in sql.split(";"):
            stmt = statement.strip()
            if stmt:
                conn.execute(stmt)
        if hasattr(conn, "commit"):
            conn.commit()


def _init_without_fts5(conn: Any) -> None:
    """Initialise schema without FTS5 virtual table and triggers."""
    basic_sql = """
    CREATE TABLE IF NOT EXISTS incidents (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        ts          TEXT    NOT NULL,
        title       TEXT    NOT NULL,
        severity    TEXT    NOT NULL DEFAULT 'unknown',
        service     TEXT    DEFAULT '',
        namespace   TEXT    DEFAULT '',
        symptoms    TEXT    DEFAULT '',
        root_cause  TEXT    DEFAULT '',
        resolution  TEXT    DEFAULT '',
        tags        TEXT    DEFAULT '[]',
        resolved    INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS patterns (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        pattern     TEXT    NOT NULL UNIQUE,
        frequency   INTEGER DEFAULT 1,
        last_seen   TEXT    NOT NULL,
        example_ids TEXT    DEFAULT '[]'
    );

    CREATE TABLE IF NOT EXISTS context (
        key         TEXT PRIMARY KEY,
        value       TEXT NOT NULL,
        updated_at  TEXT NOT NULL
    );
    """
    _exec_script(conn, basic_sql)


# ── Public API ─────────────────────────────────────────────────────────────────

def get_conn() -> Any:
    """Return a database connection — sqld (Docker) or local sqlite3 based on SQLITE_URL.

    Always call .close() when done, or use as a context manager.
    """
    if _using_sqld():
        return _get_sqld_conn()
    return _get_local_conn()

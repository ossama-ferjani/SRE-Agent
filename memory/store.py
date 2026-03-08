"""Incident store — CRUD operations, pattern tracking, and memory summarisation.

All writes are transactional. FTS5 search with LIKE fallback.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

from memory.db import FTS5_AVAILABLE, get_conn, init_db, row_to_dict

logger = logging.getLogger(__name__)

_ALLOWED_UPDATE_FIELDS = {
    "severity", "service", "namespace", "root_cause",
    "resolution", "resolved", "tags",
}


def _now_iso() -> str:
    """Return current UTC time as ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row) -> dict[str, Any]:
    """Convert a db row (sqlite3.Row or libsql row) to a plain dict, deserialising JSON fields."""
    d = row_to_dict(row)
    # Deserialise tags
    if isinstance(d.get("tags"), str):
        try:
            d["tags"] = json.loads(d["tags"])
        except (json.JSONDecodeError, TypeError):
            d["tags"] = []
    return d


def save_incident(
    title: str,
    severity: str = "unknown",
    service: str = "",
    namespace: str = "",
    symptoms: str = "",
    root_cause: str = "",
    resolution: str = "",
    tags: list[str] | None = None,
) -> int:
    """Insert a new incident row and return its integer id.

    If root_cause is set, also bumps the patterns table atomically.
    """
    init_db()
    tags_json = json.dumps(tags or [])
    ts = _now_iso()

    conn = get_conn()
    try:
        with conn:
            cursor = conn.execute(
                """
                INSERT INTO incidents
                    (ts, title, severity, service, namespace, symptoms,
                     root_cause, resolution, tags, resolved)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (ts, title, severity, service, namespace, symptoms,
                 root_cause, resolution, tags_json),
            )
            incident_id = cursor.lastrowid

            if root_cause:
                _bump_pattern(root_cause, incident_id, conn=conn)

        return incident_id
    finally:
        conn.close()


def update_incident(incident_id: int, **fields) -> None:
    """Partially update an incident. Ignores unknown fields silently."""
    valid = {k: v for k, v in fields.items() if k in _ALLOWED_UPDATE_FIELDS}
    if not valid:
        return

    # Serialise tags if provided
    if "tags" in valid and isinstance(valid["tags"], list):
        valid["tags"] = json.dumps(valid["tags"])

    set_clause = ", ".join(f"{col} = ?" for col in valid)
    values = list(valid.values()) + [incident_id]

    conn = get_conn()
    try:
        with conn:
            conn.execute(
                f"UPDATE incidents SET {set_clause} WHERE id = ?",
                values,
            )
    finally:
        conn.close()


def search_incidents(
    query: str = "",
    service: str = "",
    namespace: str = "",
    resolved: bool | None = None,
    limit: int = 10,
) -> list[dict]:
    """Search incidents using FTS5 (or LIKE fallback) plus column filters."""
    init_db()
    conn = get_conn()
    try:
        conditions: list[str] = []
        params: list[Any] = []

        if query:
            if FTS5_AVAILABLE:
                conditions.append(
                    "id IN (SELECT rowid FROM incidents_fts WHERE incidents_fts MATCH ?)"
                )
                params.append(query)
            else:
                like = f"%{query}%"
                conditions.append(
                    "(title LIKE ? OR symptoms LIKE ? OR root_cause LIKE ? OR resolution LIKE ?)"
                )
                params.extend([like, like, like, like])

        if service:
            conditions.append("service = ?")
            params.append(service)

        if namespace:
            conditions.append("namespace = ?")
            params.append(namespace)

        if resolved is not None:
            conditions.append("resolved = ?")
            params.append(1 if resolved else 0)

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        sql = f"SELECT * FROM incidents {where} ORDER BY id DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def get_incident(incident_id: int) -> dict | None:
    """Return a single incident by id, or None if not found."""
    init_db()
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM incidents WHERE id = ?", (incident_id,)
        ).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def get_recent_incidents(limit: int = 10) -> list[dict]:
    """Return the most recent incidents ordered by id descending."""
    init_db()
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM incidents ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def get_top_patterns(limit: int = 10) -> list[dict]:
    """Return failure patterns sorted by frequency descending."""
    init_db()
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM patterns ORDER BY frequency DESC LIMIT ?", (limit,)
        ).fetchall()
        return [row_to_dict(r) for r in rows]
    finally:
        conn.close()


def set_context(key: str, value: Any) -> None:
    """Persist a JSON-serialisable value under key in the context table."""
    init_db()
    conn = get_conn()
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO context (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
                """,
                (key, json.dumps(value), _now_iso()),
            )
    finally:
        conn.close()


def get_context(key: str, default: Any = None) -> Any:
    """Retrieve and JSON-deserialise a context value, returning default if missing."""
    init_db()
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT value FROM context WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return default
        return json.loads(row["value"])
    finally:
        conn.close()


def memory_summary() -> str:
    """Return a markdown string summarising recent incidents and top patterns."""
    init_db()
    incidents = get_recent_incidents(limit=5)
    patterns = get_top_patterns(limit=5)

    if not incidents and not patterns:
        return "No incident history yet."

    lines: list[str] = []

    if incidents:
        lines.append("### Recent Incidents")
        for inc in incidents:
            emoji = "✅" if inc.get("resolved") else "🔥"
            ts = inc.get("ts", "")[:10]
            title = inc.get("title", "")
            severity = inc.get("severity", "unknown")
            service = inc.get("service", "")
            rc = (inc.get("root_cause") or "")[:80]
            lines.append(f"{emoji} [{ts}] **{title}** | {severity} | {service} | {rc}")

    if patterns:
        lines.append("")
        lines.append("### Common Failure Patterns")
        for pat in patterns:
            freq = pat.get("frequency", 1)
            pattern = (pat.get("pattern") or "")[:120]
            lines.append(f"- (x{freq}) {pattern}")

    return "\n".join(lines)


def _bump_pattern(root_cause: str, incident_id: int, conn=None) -> None:
    """Upsert pattern row, incrementing frequency and tracking example_ids."""
    pattern = root_cause[:200]
    ts = _now_iso()

    close_after = conn is None
    if conn is None:
        conn = get_conn()

    try:
        row = conn.execute(
            "SELECT id, frequency, example_ids FROM patterns WHERE pattern = ?",
            (pattern,),
        ).fetchone()

        if row:
            freq = row["frequency"] + 1
            example_ids: list[int] = json.loads(row["example_ids"] or "[]")
            example_ids.append(incident_id)
            example_ids = example_ids[-20:]  # keep max 20
            conn.execute(
                "UPDATE patterns SET frequency=?, last_seen=?, example_ids=? WHERE pattern=?",
                (freq, ts, json.dumps(example_ids), pattern),
            )
        else:
            conn.execute(
                "INSERT INTO patterns (pattern, frequency, last_seen, example_ids) VALUES (?, 1, ?, ?)",
                (pattern, ts, json.dumps([incident_id])),
            )
    finally:
        if close_after:
            conn.close()

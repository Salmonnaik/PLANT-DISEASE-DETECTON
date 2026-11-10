"""
db.py
=====
SQLite connection management.

One connection per request, stored on Flask's ``g`` and closed automatically
when the request ends. ``sqlite3.Row`` is used as the row factory so query
results behave like dictionaries.

WAL journalling is enabled because the capture flow can have a device upload
writing while the dashboard is polling ``/api/stats``; WAL lets those overlap
instead of raising "database is locked".
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Union

from flask import Flask, current_app, g

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"
_G_KEY = "_plant_disease_db"


# --------------------------------------------------------------------------- #
# Timestamps
# --------------------------------------------------------------------------- #

DB_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def utc_now_string() -> str:
    """Current UTC time in the schema's canonical format."""
    return datetime.now(timezone.utc).strftime(DB_TIME_FORMAT)


def to_iso8601(db_timestamp: Optional[str]) -> Optional[str]:
    """``'2026-11-10 09:15:00'`` -> ``'2026-11-10T09:15:00Z'`` for the API."""
    if not db_timestamp:
        return None
    text = str(db_timestamp).strip()
    if text.endswith("Z") or "+" in text[10:]:
        return text
    return text.replace(" ", "T") + "Z"


# --------------------------------------------------------------------------- #
# Connections
# --------------------------------------------------------------------------- #

def connect(database_path: Union[str, Path], timeout: float = 15.0) -> sqlite3.Connection:
    """Open a tuned SQLite connection (also used by standalone scripts)."""
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(
        str(path),
        timeout=timeout,
        detect_types=sqlite3.PARSE_DECLTYPES,
        check_same_thread=False,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")
    connection.execute("PRAGMA busy_timeout = 8000")
    return connection


def get_db() -> sqlite3.Connection:
    """Request-scoped connection, created on first use."""
    connection = getattr(g, _G_KEY, None)
    if connection is None:
        connection = connect(current_app.config["DATABASE_PATH"])
        setattr(g, _G_KEY, connection)
    return connection


def close_db(_exception: Optional[BaseException] = None) -> None:
    connection = getattr(g, _G_KEY, None)
    if connection is not None:
        setattr(g, _G_KEY, None)
        try:
            connection.close()
        except sqlite3.Error as exc:  # pragma: no cover
            logger.warning("Error while closing the database connection: %s", exc)


@contextmanager
def standalone_connection(database_path: Union[str, Path]) -> Iterator[sqlite3.Connection]:
    """Context-managed connection for CLI scripts outside a Flask request."""
    connection = connect(database_path)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


# --------------------------------------------------------------------------- #
# Schema
# --------------------------------------------------------------------------- #

def read_schema(schema_path: Union[str, Path] = SCHEMA_PATH) -> str:
    path = Path(schema_path)
    if not path.is_file():
        raise FileNotFoundError(f"schema.sql not found at {path}")
    return path.read_text(encoding="utf-8")


def apply_schema(connection: sqlite3.Connection, schema_path: Union[str, Path] = SCHEMA_PATH) -> None:
    """Run schema.sql. Every statement is ``IF NOT EXISTS``, so this is idempotent."""
    connection.executescript(read_schema(schema_path))
    connection.commit()


def init_database(
    database_path: Union[str, Path],
    schema_path: Union[str, Path] = SCHEMA_PATH,
) -> Dict[str, Any]:
    """
    Create the database file and tables if they are missing, then migrate.

    Order matters: the schema runs first so a fresh database has every table,
    then the migrations bring an *existing* database up to the same shape. Both
    are idempotent, so this is safe on every start.
    """
    from database.migrations import run_migrations  # noqa: PLC0415 (avoids a cycle)

    path = Path(database_path)
    existed = path.is_file()

    with standalone_connection(path) as connection:
        apply_schema(connection, schema_path)
        migration_report = run_migrations(connection)
        tables = [
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        ]
        counts = {
            table: connection.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
            for table in tables
        }

    return {
        "database_path": str(path.resolve()),
        "already_existed": existed,
        "tables": tables,
        "row_counts": counts,
        "migrations": migration_report,
    }


def table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?", (table_name,)
    ).fetchone()
    return row is not None


# --------------------------------------------------------------------------- #
# Query helpers
# --------------------------------------------------------------------------- #

def query_all(sql: str, params: Sequence[Any] = ()) -> List[Dict[str, Any]]:
    return [dict(row) for row in get_db().execute(sql, tuple(params)).fetchall()]


def query_one(sql: str, params: Sequence[Any] = ()) -> Optional[Dict[str, Any]]:
    row = get_db().execute(sql, tuple(params)).fetchone()
    return dict(row) if row is not None else None


def query_scalar(sql: str, params: Sequence[Any] = (), default: Any = 0) -> Any:
    row = get_db().execute(sql, tuple(params)).fetchone()
    if row is None:
        return default
    value = row[0]
    return default if value is None else value


def execute(sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
    connection = get_db()
    cursor = connection.execute(sql, tuple(params))
    connection.commit()
    return cursor


def execute_many(sql: str, seq_of_params: Iterable[Sequence[Any]]) -> None:
    connection = get_db()
    connection.executemany(sql, [tuple(params) for params in seq_of_params])
    connection.commit()


def insert_returning_id(sql: str, params: Sequence[Any] = ()) -> int:
    return int(execute(sql, params).lastrowid or 0)


# --------------------------------------------------------------------------- #
# Flask wiring
# --------------------------------------------------------------------------- #

def init_app(app: Flask) -> Dict[str, Any]:
    """Attach connection teardown to ``app`` and make sure the schema exists."""
    app.teardown_appcontext(close_db)
    report = init_database(app.config["DATABASE_PATH"], app.config.get("SCHEMA_PATH", SCHEMA_PATH))
    logger.info(
        "SQLite ready at %s (tables: %s)",
        report["database_path"],
        ", ".join(report["tables"]) or "none",
    )

    applied = report.get("migrations", {}).get("applied") or []
    if applied:
        for migration in applied:
            logger.info(
                "Migration %03d applied (%s): %s",
                migration["version"],
                migration["name"],
                migration["detail"],
            )
    else:
        logger.debug("No pending database migrations.")

    return report


__all__ = [
    "SCHEMA_PATH",
    "DB_TIME_FORMAT",
    "utc_now_string",
    "to_iso8601",
    "connect",
    "get_db",
    "close_db",
    "standalone_connection",
    "apply_schema",
    "init_database",
    "init_app",
    "table_exists",
    "query_all",
    "query_one",
    "query_scalar",
    "execute",
    "execute_many",
    "insert_returning_id",
]

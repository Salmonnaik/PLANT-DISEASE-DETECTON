"""
init_db.py
==========
Database initialisation script.

Run it once before starting the backend for the first time (``app.py`` also
calls the same code on startup, so this is mainly for explicit setup, CI and
resetting a development database)::

    python database/init_db.py                 # create tables if missing
    python database/init_db.py --reset         # DROP everything and recreate
    python database/init_db.py --show          # print tables and row counts
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional, Sequence

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from config import Config  # noqa: E402
from database.db import (  # noqa: E402
    SCHEMA_PATH,
    apply_schema,
    init_database,
    standalone_connection,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
logger = logging.getLogger("init_db")


def reset_database(database_path: Path) -> None:
    """Drop the project's tables, then recreate them from schema.sql."""
    with standalone_connection(database_path) as connection:
        tables = [
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        ]
        for table in tables:
            logger.warning("Dropping table %s", table)
            connection.execute(f"DROP TABLE IF EXISTS {table}")
        triggers = [
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'"
            ).fetchall()
        ]
        for trigger in triggers:
            connection.execute(f"DROP TRIGGER IF EXISTS {trigger}")
        apply_schema(connection, SCHEMA_PATH)
    logger.info("Database reset complete.")


def show_database(database_path: Path) -> None:
    with standalone_connection(database_path) as connection:
        tables = [
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        ]
        if not tables:
            logger.warning("No tables found in %s", database_path)
            return
        print(f"\nDatabase: {database_path}")
        print("-" * 60)
        for table in tables:
            count = connection.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
            print(f"  {table:<22} {count:>8} rows")
            columns = connection.execute(f"PRAGMA table_info({table})").fetchall()
            for column in columns:
                print(f"      - {column['name']:<22} {column['type']}")
            print()


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Initialise the SQLite database.")
    parser.add_argument(
        "--database",
        type=Path,
        default=Config.DATABASE_PATH,
        help=f"Database file path (default: {Config.DATABASE_PATH})",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="DESTRUCTIVE: drop all existing tables and recreate them",
    )
    parser.add_argument("--show", action="store_true", help="Print tables, columns and row counts")
    parser.add_argument("--yes", action="store_true", help="Skip the --reset confirmation prompt")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    database_path = Path(args.database)

    if args.reset:
        if not args.yes:
            logger.warning(
                "--reset will DELETE every detection record and device row in %s",
                database_path,
            )
            answer = input("Type 'reset' to confirm: ").strip().lower()
            if answer != "reset":
                logger.info("Aborted; nothing was changed.")
                return 1
        reset_database(database_path)
    else:
        report = init_database(database_path)
        if report["already_existed"]:
            logger.info("Database already existed at %s; schema verified.", report["database_path"])
        else:
            logger.info("Created a new database at %s", report["database_path"])
        logger.info("Tables: %s", ", ".join(report["tables"]))

    if args.show or args.reset:
        show_database(database_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

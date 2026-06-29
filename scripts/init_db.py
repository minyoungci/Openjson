from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import DEFAULT_DB_PATH, connect, get_schema_migration_status, init_db


def initialize(db_path: str) -> dict[str, object]:
    init_db(db_path)
    with connect(db_path) as conn:
        tables = sorted(
            row["name"]
            for row in conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                ORDER BY name
                """
            ).fetchall()
        )
        foreign_keys_enabled = conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    return {
        "status": "initialized",
        "db_path": db_path,
        "foreign_keys_enabled": foreign_keys_enabled,
        "tables": tables,
        "migrations": get_schema_migration_status(db_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize the OpenJson SQLite database schema.")
    parser.add_argument(
        "--db-path",
        default=os.environ.get("OPENJSON_DB_PATH", DEFAULT_DB_PATH),
        help="SQLite DB path. Defaults to OPENJSON_DB_PATH or ./openjson.sqlite3.",
    )
    args = parser.parse_args()
    print(json.dumps(initialize(args.db_path), indent=2))


if __name__ == "__main__":
    main()

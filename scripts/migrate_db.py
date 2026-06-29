from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import DEFAULT_DB_PATH, KNOWN_SCHEMA_MIGRATIONS, get_schema_migration_status, init_db


def migrate(db_path: str) -> dict[str, object]:
    init_db(db_path)
    return {
        "status": "migrated",
        "db_path": db_path,
        "migrations": get_schema_migration_status(db_path),
    }


def status(db_path: str) -> dict[str, object]:
    path = Path(db_path)
    if not path.exists():
        expected = [migration_id for migration_id, _ in KNOWN_SCHEMA_MIGRATIONS]
        return {
            "status": "missing",
            "db_path": db_path,
            "migrations": {
                "status": "pending",
                "current_schema_version": expected[-1],
                "expected_migrations": expected,
                "applied_migrations": [],
                "applied_count": 0,
                "pending_migrations": expected,
                "unknown_migrations": [],
            },
        }
    return {
        "status": "checked",
        "db_path": db_path,
        "migrations": get_schema_migration_status(db_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply or inspect OpenJson SQLite schema migrations.")
    parser.add_argument(
        "--db-path",
        default=os.environ.get("OPENJSON_DB_PATH", DEFAULT_DB_PATH),
        help="SQLite DB path. Defaults to OPENJSON_DB_PATH or ./openjson.sqlite3.",
    )
    parser.add_argument("--status", action="store_true", help="Only inspect migration status; do not initialize.")
    args = parser.parse_args()
    result = status(args.db_path) if args.status else migrate(args.db_path)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    migration_state = result["migrations"]["status"]
    if migration_state not in {"ok", "pending"}:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import DEFAULT_DB_PATH, init_db
from app.errors import AppError
from app.snapshot_compaction_service import (
    compact_document_snapshot,
    compact_due_document_snapshots,
    list_document_snapshots,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Create derived compacted document snapshots.")
    parser.add_argument(
        "--db-path",
        default=os.environ.get("OPENJSON_DB_PATH", DEFAULT_DB_PATH),
        help="SQLite DB path. Defaults to OPENJSON_DB_PATH or ./openjson.sqlite3.",
    )
    parser.add_argument("--document-id", help="Limit compaction to one document.")
    parser.add_argument("--version", type=int, help="Compact exactly one document version.")
    parser.add_argument(
        "--every-versions",
        type=int,
        default=100,
        help="Create snapshots at this accepted-version interval. Defaults to 100.",
    )
    parser.add_argument(
        "--skip-latest",
        action="store_true",
        help="Do not include each document's current latest version.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List compacted snapshots for --document-id instead of writing new rows.",
    )
    args = parser.parse_args()

    try:
        init_db(args.db_path)
        if args.list:
            if not args.document_id:
                parser.error("--list requires --document-id")
            result = list_document_snapshots(args.db_path, document_id=args.document_id)
        elif args.version is not None:
            if not args.document_id:
                parser.error("--version requires --document-id")
            result = compact_document_snapshot(
                args.db_path,
                document_id=args.document_id,
                version=args.version,
            )
        else:
            result = compact_due_document_snapshots(
                args.db_path,
                document_id=args.document_id,
                every_versions=args.every_versions,
                include_latest=not args.skip_latest,
            )
    except AppError as exc:
        print(json.dumps(exc.as_response(), indent=2, ensure_ascii=False))
        raise SystemExit(1) from exc

    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

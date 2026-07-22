from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.settings.config import get_settings


def database_summary(path: Path) -> dict[str, object]:
    with sqlite3.connect(path) as connection:
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        tables = [
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        ]
        counts = {
            table: int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
            for table in tables
        }
    return {"integrity": integrity, "table_counts": counts}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Create and verify a consistent TWC Workbench SQLite backup.")
    parser.add_argument("--source", type=Path, help="SQLite source path; defaults to configured Workbench database.")
    parser.add_argument("--output", type=Path, help="Backup path; defaults to data/backups with a UTC timestamp.")
    args = parser.parse_args()

    settings = get_settings()
    source = (args.source or settings.resolved_database_path).resolve()
    if not source.is_file():
        raise SystemExit(f"Database does not exist: {source}")
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output = (args.output or settings.resolved_data_dir / "backups" / f"twc_workbench-{timestamp}.sqlite3").resolve()
    if output.exists():
        raise SystemExit(f"Refusing to overwrite existing backup: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)

    source_summary = database_summary(source)
    with sqlite3.connect(source) as source_connection, sqlite3.connect(output) as backup_connection:
        source_connection.backup(backup_connection)
    backup_summary = database_summary(output)
    verified = source_summary == backup_summary and backup_summary["integrity"] == "ok"
    report = {
        "verified": verified,
        "source": str(source),
        "backup": str(output),
        "backup_sha256": file_sha256(output),
        "source_summary": source_summary,
        "backup_summary": backup_summary,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if verified else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""
Remove scenes_files links (and orphan files rows) for video files that do not
exist on disk, only when the same scene still has at least one file that exists.

Skips zip-based files (zip_file_id IS NOT NULL). Windows: uses os.path.exists.

Usage:
  python remove_missing_scene_file_links.py [path-to-stash-go.sqlite]
"""

from __future__ import annotations

import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path


def file_still_referenced(conn: sqlite3.Connection, file_id: int) -> bool:
    checks = [
        ("SELECT 1 FROM scenes_files WHERE file_id = ? LIMIT 1", (file_id,)),
        ("SELECT 1 FROM galleries_files WHERE file_id = ? LIMIT 1", (file_id,)),
        ("SELECT 1 FROM images_files WHERE file_id = ? LIMIT 1", (file_id,)),
        ("SELECT 1 FROM files WHERE zip_file_id = ? LIMIT 1", (file_id,)),
        ("SELECT 1 FROM folders WHERE zip_file_id = ? LIMIT 1", (file_id,)),
    ]
    for sql, args in checks:
        if conn.execute(sql, args).fetchone() is not None:
            return True
    return False


def main() -> int:
    default_db = Path(os.environ.get("STASH_DB", r"c:\Users\areks\.stash\bin\clips"))
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else default_db
    if not db_path.is_file():
        print(f"Database not found: {db_path}", file=sys.stderr)
        return 1

    backup_dir = db_path.parent / "db_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"{db_path.name}_before_remove_missing_{ts}.sqlite"
    import shutil

    shutil.copy2(db_path, backup_path)
    print(f"Backup: {backup_path}")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # Only scenes with 2+ file links (single-file scenes cannot be "one missing, one ok").
    rows = conn.execute(
        """
        SELECT sf.scene_id AS scene_id,
               sf.file_id AS file_id,
               sf.[primary] AS is_primary,
               (fol.path || CHAR(92) || f.basename) AS full_path
        FROM scenes_files AS sf
        INNER JOIN files AS f ON f.id = sf.file_id
        INNER JOIN folders AS fol ON fol.id = f.parent_folder_id
        WHERE f.zip_file_id IS NULL
          AND sf.scene_id IN (
            SELECT sf2.scene_id
            FROM scenes_files AS sf2
            INNER JOIN files AS f2 ON f2.id = sf2.file_id
            WHERE f2.zip_file_id IS NULL
            GROUP BY sf2.scene_id
            HAVING COUNT(*) >= 2
          )
        """
    ).fetchall()

    by_scene: dict[int, list[sqlite3.Row]] = defaultdict(list)
    for r in rows:
        by_scene[int(r["scene_id"])].append(r)

    to_remove: list[tuple[int, int]] = []
    for scene_id, lst in by_scene.items():
        existing = [r for r in lst if os.path.exists(r["full_path"])]
        missing = [r for r in lst if not os.path.exists(r["full_path"])]
        if existing and missing:
            for m in missing:
                to_remove.append((scene_id, int(m["file_id"])))

    print(
        f"Pairs (scene_id, file_id) to unlink (missing on disk, scene has other file(s)): {len(to_remove)}"
    )
    if not to_remove:
        conn.close()
        return 0

    removing = set(to_remove)
    scenes_touched = {s for s, _ in to_remove}

    conn.execute("BEGIN IMMEDIATE")
    try:
        # If we remove the primary file, promote another file that exists on disk.
        for scene_id in scenes_touched:
            members = by_scene[scene_id]
            removing_ids = {fid for (sid, fid) in to_remove if sid == scene_id}
            primary_fid = None
            for m in members:
                if int(m["is_primary"]) == 1:
                    primary_fid = int(m["file_id"])
                    break
            if primary_fid is None or primary_fid not in removing_ids:
                continue
            candidates = [
                int(m["file_id"])
                for m in members
                if int(m["file_id"]) not in removing_ids and os.path.exists(m["full_path"])
            ]
            if not candidates:
                continue
            new_primary = min(candidates)
            conn.execute(
                "UPDATE scenes_files SET [primary] = 0 WHERE scene_id = ?", (scene_id,)
            )
            conn.execute(
                "UPDATE scenes_files SET [primary] = 1 WHERE scene_id = ? AND file_id = ?",
                (scene_id, new_primary),
            )

        conn.executemany(
            "DELETE FROM scenes_files WHERE scene_id = ? AND file_id = ?",
            to_remove,
        )

        # Any scene left without a primary row (safety net).
        conn.execute(
            """
            UPDATE scenes_files
            SET [primary] = 1
            WHERE (scene_id, file_id) IN (
                SELECT scene_id, MIN(file_id)
                FROM scenes_files
                GROUP BY scene_id
                HAVING SUM(CASE WHEN [primary] = 1 THEN 1 ELSE 0 END) = 0
            )
            """
        )

        orphan_ids = sorted({fid for _, fid in to_remove})
        deleted_files = 0
        for fid in orphan_ids:
            if file_still_referenced(conn, fid):
                continue
            conn.execute("DELETE FROM files WHERE id = ?", (fid,))
            deleted_files += 1

        conn.commit()
        print(f"Deleted orphan rows from files: {deleted_files}")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

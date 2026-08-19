"""Punktowa kontrola: czy dane z poprzedniego scalenia są w aktualnej bazie."""

import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

live = sqlite3.connect("file:C:/Users/areks/.stash/bin/clips?mode=ro", uri=True)
live.row_factory = sqlite3.Row

NEEDLE = "Belle Claire - Handyman"

rows = live.execute(
    """
    SELECT s.id, s.title, s.date, st.name AS studio, f.basename
    FROM scenes s
    JOIN scenes_files sf ON sf.scene_id = s.id
    JOIN files f ON f.id = sf.file_id
    LEFT JOIN studios st ON st.id = s.studio_id
    WHERE f.basename LIKE ?
    """,
    (f"%{NEEDLE}%",),
).fetchall()

for row in rows:
    print(f"scena #{row['id']}  {row['basename']}")
    print(f"  tytuł  : {row['title']}")
    print(f"  data   : {row['date']}")
    print(f"  studio : {row['studio']}")
    tags = [
        r[0]
        for r in live.execute(
            "SELECT t.name FROM scenes_tags st JOIN tags t ON t.id = st.tag_id"
            " WHERE st.scene_id = ? ORDER BY t.name",
            (row["id"],),
        )
    ]
    print(f"  tagi   : {tags}")
    perf = [
        r[0]
        for r in live.execute(
            "SELECT p.name FROM performers_scenes ps JOIN performers p ON p.id = ps.performer_id"
            " WHERE ps.scene_id = ?",
            (row["id"],),
        )
    ]
    print(f"  aktorzy: {perf}")

print("\n--- statystyki biblioteki z:\\ClipsStudiosSet4 w aktualnej bazie ---")
print(
    "  sceny z tytułem:",
    live.execute(
        """
        SELECT COUNT(*) FROM scenes s WHERE s.title IS NOT NULL AND s.id IN (
          SELECT sf.scene_id FROM scenes_files sf JOIN files f ON f.id = sf.file_id
          JOIN folders fo ON fo.id = f.parent_folder_id
          WHERE fo.path LIKE 'z:\\ClipsStudiosSet4%'
        )
        """
    ).fetchone()[0],
)
print(
    "  wszystkie sceny w bibliotece:",
    live.execute(
        """
        SELECT COUNT(DISTINCT sf.scene_id) FROM scenes_files sf JOIN files f ON f.id = sf.file_id
        JOIN folders fo ON fo.id = f.parent_folder_id
        WHERE fo.path LIKE 'z:\\ClipsStudiosSet4%'
        """
    ).fetchone()[0],
)

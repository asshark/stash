"""Weryfikacja bazy odzyskanej przez .recover."""

import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REC = "C:/Users/areks/.stash/bin/clips_recovered"
CORRUPT = "C:/Users/areks/.stash/bin/clips.CORRUPT_20260727_0940"

rec = sqlite3.connect(f"file:{REC}?mode=ro", uri=True)
rec.row_factory = sqlite3.Row

print("--- integralność ---")
print(rec.execute("PRAGMA integrity_check(5)").fetchall())
fk = rec.execute("PRAGMA foreign_key_check").fetchall()
print("foreign_key_check:", len(fk), "naruszeń")

print("\n--- schemat / dodatkowe tabele ---")
extra = [
    r[0]
    for r in rec.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%lost%'"
    )
]
print("lost_and_found:", extra)
try:
    print("schema_migrations:", rec.execute("SELECT * FROM schema_migrations").fetchall())
except sqlite3.Error as exc:
    print("schema_migrations:", exc)

print("\n--- liczności (odzyskane vs czytelne w uszkodzonej) ---")
corrupt = sqlite3.connect(f"file:{CORRUPT}?mode=ro", uri=True)
tables = [
    r[0]
    for r in rec.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        " AND name NOT LIKE '%lost%' ORDER BY name"
    )
]
for table in tables:
    try:
        after = rec.execute(f"SELECT COUNT(*) FROM `{table}`").fetchone()[0]
    except sqlite3.Error as exc:
        after = f"BŁĄD {exc}"
    try:
        before = corrupt.execute(f"SELECT COUNT(*) FROM `{table}`").fetchone()[0]
    except sqlite3.Error:
        before = "nieczytelne"
    mark = "" if before == after else "   <-- różnica"
    if before or after:
        print(f"  {table:<28} przed={before!s:<12} po={after}{mark}")

print("\n--- spójność scen i plików ---")
print(
    "  scenes:",
    rec.execute("SELECT COUNT(*) FROM scenes").fetchone()[0],
)
print(
    "  scenes_files (unikalnych scene_id):",
    rec.execute("SELECT COUNT(DISTINCT scene_id) FROM scenes_files").fetchone()[0],
)
print(
    "  scenes_files bez sceny:",
    rec.execute(
        "SELECT COUNT(*) FROM scenes_files sf LEFT JOIN scenes s ON s.id = sf.scene_id"
        " WHERE s.id IS NULL"
    ).fetchone()[0],
)
print(
    "  sceny bez pliku:",
    rec.execute(
        "SELECT COUNT(*) FROM scenes s LEFT JOIN scenes_files sf ON sf.scene_id = s.id"
        " WHERE sf.scene_id IS NULL"
    ).fetchone()[0],
)

print("\n--- ślady scalenia (dane przywrócone przez skrypt) ---")
print(
    "  sceny z tytułem:",
    rec.execute("SELECT COUNT(*) FROM scenes WHERE title IS NOT NULL").fetchone()[0],
)
print(
    "  powiązania aktorów:",
    rec.execute("SELECT COUNT(*) FROM performers_scenes").fetchone()[0],
)
print("  scenes_o_dates:", rec.execute("SELECT COUNT(*) FROM scenes_o_dates").fetchone()[0])
print(
    "  scenes_view_dates:",
    rec.execute("SELECT COUNT(*) FROM scenes_view_dates").fetchone()[0],
)

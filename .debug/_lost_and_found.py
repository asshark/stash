import sqlite3
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

rec = sqlite3.connect("file:C:/Users/areks/.stash/bin/clips_recovered?mode=ro", uri=True)
rec.row_factory = sqlite3.Row

print("--- schemat lost_and_found ---")
print(rec.execute("SELECT sql FROM sqlite_master WHERE name='lost_and_found'").fetchone()[0][:600])

total = rec.execute("SELECT COUNT(*) FROM lost_and_found").fetchone()[0]
print("\nwierszy:", total)

print("\n--- rozkład wg rootpgno / liczby kolumn ---")
for row in rec.execute(
    "SELECT rootpgno, nfield, COUNT(*) c FROM lost_and_found GROUP BY rootpgno, nfield"
    " ORDER BY c DESC LIMIT 15"
):
    print(dict(row))

print("\n--- brakujące sceny ---")
missing = [
    int(r[0])
    for r in rec.execute(
        "SELECT DISTINCT sf.scene_id FROM scenes_files sf"
        " LEFT JOIN scenes s ON s.id = sf.scene_id WHERE s.id IS NULL ORDER BY sf.scene_id"
    )
]
print("liczba:", len(missing))
print("zakres id:", missing[0], "-", missing[-1])
print("pierwsze 10:", missing[:10])

missing_set = set(missing)
hits = [
    dict(r)
    for r in rec.execute(
        "SELECT * FROM lost_and_found WHERE id IN ({})".format(
            ",".join("?" * min(len(missing), 900))
        ),
        missing[:900],
    )
]
print("\nwierszy w lost_and_found o id pasującym do brakujących scen:", len(hits))
for h in hits[:3]:
    print({k: v for k, v in list(h.items())[:14]})

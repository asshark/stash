import sqlite3
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

rec = sqlite3.connect("file:C:/Users/areks/.stash/bin/clips_recovered?mode=ro", uri=True)
rec.row_factory = sqlite3.Row

missing = {
    int(r[0])
    for r in rec.execute(
        "SELECT DISTINCT sf.scene_id FROM scenes_files sf"
        " LEFT JOIN scenes s ON s.id = sf.scene_id WHERE s.id IS NULL"
    )
}
print("brakujących scen:", len(missing))

print("\n--- wiersze lost_and_found z nfield = 15 (tyle kolumn ma scenes) ---")
rows = rec.execute("SELECT * FROM lost_and_found WHERE nfield = 15").fetchall()
print("wierszy:", len(rows))
ids = [int(r["id"]) for r in rows]
print("unikalnych id:", len(set(ids)))
print("duplikatów id:", len(ids) - len(set(ids)))
print("z tego w zbiorze brakujących:", len(set(ids) & missing))
print("kolidujących z istniejącymi scenami:", len(set(ids) - missing))
print("rootpgno:", Counter(int(r["rootpgno"]) for r in rows).most_common(5))

print("\n--- czy c0 zawsze NULL (kolumna id) ---")
print(Counter(r["c0"] is None for r in rows))

print("\n--- kontrola typów w kluczowych kolumnach ---")
bad = 0
for r in rows:
    if r["c7"] is None or r["c8"] is None:
        bad += 1
print("wierszy bez created_at/updated_at:", bad)

print("\n--- pozostałe nfield ---")
print(
    Counter(
        int(r["nfield"])
        for r in rec.execute("SELECT nfield FROM lost_and_found WHERE nfield <> 15")
    ).most_common()
)

print("\n--- ile brakujących scen NIE ma odpowiednika w lost_and_found ---")
print(len(missing - set(ids)))

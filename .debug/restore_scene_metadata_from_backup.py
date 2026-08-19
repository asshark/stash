#!/usr/bin/env python3
"""
Odzyskiwanie metadanych scen ze starszej kopii zapasowej bazy Stash.

Scenariusz: sceny z jednej biblioteki zostały usunięte i ponownie
zeskanowane, przez co utraciły metadane (aktorów, studia, tagi, daty,
O count...). Skrypt odszukuje te same pliki w starej kopii bazy i dopisuje
brakujące dane.

Przebieg:
  1. wybór bazy docelowej BA1 i biblioteki BI1,
  2. wybór bazy z kopii zapasowej BA2 i biblioteki BI2,
  3. dopasowanie scen po odcisku pliku (oshash, w razie braku md5),
  4. podsumowanie i sekwencyjne zatwierdzanie różnic (z opcją "wszystkie"),
  5. zapis do NOWEGO pliku obok BA1, z dopiskiem "restored" w nazwie.

Zasada scalania: dane są wyłącznie dopisywane. Pola skalarne uzupełniane są
tylko wtedy, gdy w BA1 są puste; listy (aktorzy, tagi, URL-e, daty O, ...)
scalane są sumą. Nic nie jest nadpisywane ani usuwane.

Ani BA1, ani BA2 nie są modyfikowane - zmiany trafiają do kopii roboczej.

Użycie:
  python restore_scene_metadata_from_backup.py
  python restore_scene_metadata_from_backup.py --target clips --backup backup/clips
  python restore_scene_metadata_from_backup.py --yes        # bez pytań
  python restore_scene_metadata_from_backup.py --dry-run    # tylko raport
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sqlite3
import sys
import tempfile
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

# ---------------------------------------------------------------------------
# Pomocnicze
# ---------------------------------------------------------------------------

MATCH_TYPES = ("oshash", "md5")

CAPS_LABELS = {
    "o_dates": "O count",
    "view_dates": "historia odtwarzania",
    "custom_fields": "pola własne",
    "markers": "znaczniki",
    "marker_end_seconds": "koniec znacznika",
    "groups": "grupy",
    "stash_ids": "StashDB ID",
    "urls": "adresy URL",
    "date_precision": "dokładność daty",
    "play_stats": "statystyki odtwarzania",
}

SCALAR_FIELDS: tuple[tuple[str, str], ...] = (
    ("title", "tytuł"),
    ("details", "opis"),
    ("code", "kod (studio code)"),
    ("director", "reżyser"),
)


def out_encoding_fix() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def now_rfc3339() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def low(value: Any) -> str:
    return (value or "").strip().lower()


def is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    return False


def as_bool(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() not in ("", "0", "false", "FALSE")
    return bool(value)


def as_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def shorten(value: Any, width: int = 70) -> str:
    if value is None:
        return "(brak)"
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    if text == "":
        return "(puste)"
    if len(text) > width:
        text = text[: width - 1] + "…"
    return text


def join_path(folder_path: str, basename: str) -> str:
    if re.match(r"^[A-Za-z]:", folder_path) or "\\" in folder_path:
        sep = "\\"
    elif folder_path.startswith("/"):
        sep = "/"
    else:
        sep = os.sep
    return folder_path.rstrip("\\/") + sep + basename


def fingerprint_text(value: Any) -> str:
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).hex()
    return str(value)


# ---------------------------------------------------------------------------
# Dostęp do bazy
# ---------------------------------------------------------------------------


class TempCopy:
    """Kopia bazy w katalogu tymczasowym - awaryjnie, gdy nie da się otworzyć
    pliku tylko do odczytu (np. baza ma nieprzetworzony dziennik WAL)."""

    def __init__(self) -> None:
        self.dirs: list[tempfile.TemporaryDirectory] = []

    def make(self, path: Path) -> Path:
        holder = tempfile.TemporaryDirectory(prefix="stash_restore_")
        self.dirs.append(holder)
        target = Path(holder.name) / path.name
        shutil.copy2(path, target)
        for suffix in ("-wal", "-shm"):
            side = Path(str(path) + suffix)
            if side.is_file():
                shutil.copy2(side, Path(str(target) + suffix))
        return target

    def cleanup(self) -> None:
        for holder in self.dirs:
            holder.cleanup()
        self.dirs.clear()


TEMP_COPIES = TempCopy()


def open_ro(path: Path) -> sqlite3.Connection:
    """Otwiera bazę tylko do odczytu; w razie potrzeby na kopii tymczasowej."""
    try:
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
    except sqlite3.Error:
        print(f"  ! Nie można otworzyć {path} tylko do odczytu - pracuję na kopii tymczasowej.")
        conn = sqlite3.connect(str(TEMP_COPIES.make(path)))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA temp_store = MEMORY")
    return conn


def schema_version(conn: sqlite3.Connection) -> int | None:
    try:
        row = conn.execute("SELECT version FROM schema_migrations LIMIT 1").fetchone()
    except sqlite3.Error:
        return None
    return int(row[0]) if row else None


_TABLE_CACHE: dict[int, set[str]] = {}


def has_table(conn: sqlite3.Connection, name: str) -> bool:
    tables = _TABLE_CACHE.get(id(conn))
    if tables is None:
        tables = {
            r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        _TABLE_CACHE[id(conn)] = tables
    return name in tables


_COLUMN_CACHE: dict[tuple[int, str], list[str]] = {}


def columns(conn: sqlite3.Connection, table: str) -> list[str]:
    key = (id(conn), table)
    cached = _COLUMN_CACHE.get(key)
    if cached is None:
        cached = [r[1] for r in conn.execute(f"PRAGMA table_info(`{table}`)")]
        _COLUMN_CACHE[key] = cached
    return cached


def has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return column in columns(conn, table)


@dataclass
class Caps:
    """Możliwości konkretnej bazy - schematy BA1 i BA2 mogą się różnić."""

    o_dates: bool
    view_dates: bool
    custom_fields: bool
    markers: bool
    marker_end_seconds: bool
    groups: bool
    stash_ids: bool
    urls: bool
    date_precision: bool
    play_stats: bool

    @classmethod
    def detect(cls, conn: sqlite3.Connection) -> "Caps":
        return cls(
            o_dates=has_table(conn, "scenes_o_dates"),
            view_dates=has_table(conn, "scenes_view_dates"),
            custom_fields=has_table(conn, "scene_custom_fields"),
            markers=has_table(conn, "scene_markers"),
            marker_end_seconds=has_table(conn, "scene_markers")
            and has_column(conn, "scene_markers", "end_seconds"),
            groups=has_table(conn, "groups_scenes") and has_table(conn, "groups"),
            stash_ids=has_table(conn, "scene_stash_ids"),
            urls=has_table(conn, "scene_urls"),
            date_precision=has_column(conn, "scenes", "date_precision"),
            play_stats=has_column(conn, "scenes", "play_duration"),
        )

    def common(self, other: "Caps") -> "Caps":
        return Caps(
            **{
                name: getattr(self, name) and getattr(other, name)
                for name in self.__dataclass_fields__
            }
        )


# ---------------------------------------------------------------------------
# Wybór bazy i biblioteki
# ---------------------------------------------------------------------------


def prompt(text: str) -> str:
    try:
        return input(text).strip()
    except EOFError:
        raise SystemExit("\nPrzerwano.")


def ask_database(role: str, preset: str | None) -> tuple[Path, sqlite3.Connection]:
    while True:
        raw = preset or prompt(f"Ścieżka do bazy {role}: ")
        preset = None
        if not raw:
            continue
        path = Path(raw.strip('"').strip("'")).expanduser()
        if not path.is_file():
            print(f"  ! Nie znaleziono pliku: {path}")
            continue
        try:
            conn = open_ro(path)
        except sqlite3.Error as exc:
            print(f"  ! Nie udało się otworzyć bazy: {exc}")
            continue
        version = schema_version(conn)
        if version is None or not has_table(conn, "scenes"):
            print("  ! To nie wygląda na bazę Stash (brak tabeli scenes / schema_migrations).")
            conn.close()
            continue
        scenes = f"{conn.execute('SELECT COUNT(*) FROM scenes').fetchone()[0]:,}".replace(",", " ")
        print(f"  → {path}  (schemat v{version}, scen: {scenes})")
        return path, conn


@dataclass
class Root:
    folder_id: int
    path: str
    scenes: int


def list_roots(conn: sqlite3.Connection) -> list[Root]:
    folders = {
        int(r["id"]): (r["parent_folder_id"], r["path"])
        for r in conn.execute("SELECT id, parent_folder_id, path FROM folders")
    }

    def root_of(folder_id: int) -> int | None:
        seen: set[int] = set()
        current = folder_id
        while current is not None and current not in seen:
            seen.add(current)
            parent = folders.get(current, (None, ""))[0]
            if parent is None:
                return current
            current = int(parent)
        return None

    root_cache: dict[int, int | None] = {}
    per_root: dict[int, set[int]] = defaultdict(set)
    for scene_id, folder_id in conn.execute(
        """
        SELECT sf.scene_id, f.parent_folder_id
        FROM scenes_files sf
        JOIN files f ON f.id = sf.file_id
        """
    ):
        folder_id = int(folder_id)
        if folder_id not in root_cache:
            root_cache[folder_id] = root_of(folder_id)
        root = root_cache[folder_id]
        if root is not None:
            per_root[root].add(int(scene_id))

    roots = [
        Root(fid, meta[1], len(per_root.get(fid, ())))
        for fid, meta in folders.items()
        if meta[0] is None
    ]
    roots.sort(key=lambda r: (-r.scenes, r.path.lower()))
    return roots


def choose_root(conn: sqlite3.Connection, role: str, preset: str | None) -> Root | None:
    roots = list_roots(conn)
    if not roots:
        print(f"  ! W bazie {role} nie znaleziono żadnych bibliotek.")
        raise SystemExit(1)

    if preset:
        wanted = low(preset)
        exact = [r for r in roots if low(r.path) == wanted]
        if len(exact) == 1:
            print(f"  → biblioteka {role}: {exact[0].path}")
            return exact[0]
        print(f"  ! Nie dopasowano biblioteki '{preset}' - wybierz z listy.")

    print(f"\nBiblioteki w bazie {role}:")
    for index, root in enumerate(roots, start=1):
        print(f"  {index:2}) {root.path}   ({root.scenes} scen)")
    print("   0) wszystkie biblioteki")

    while True:
        raw = prompt(f"Wybierz bibliotekę {role} [numer]: ")
        if not raw.isdigit():
            continue
        choice = int(raw)
        if choice == 0:
            return None
        if 1 <= choice <= len(roots):
            return roots[choice - 1]


# ---------------------------------------------------------------------------
# Wczytywanie danych
# ---------------------------------------------------------------------------


@dataclass
class Side:
    """Zbiór danych o scenach z jednej bazy, ograniczony do jednej biblioteki."""

    label: str
    caps: Caps
    scenes: dict[int, dict] = field(default_factory=dict)
    paths: dict[int, str] = field(default_factory=dict)
    fingerprints: dict[int, set[tuple[str, str]]] = field(default_factory=dict)
    performers: dict[int, list[tuple[int, str, str | None]]] = field(default_factory=dict)
    tags: dict[int, list[tuple[int, str]]] = field(default_factory=dict)
    # Aliasy już powiązanych aktorów / tagów - pozwalają rozpoznać, że dana
    # osoba jest przy scenie obecna, tylko pod inną nazwą główną.
    performer_aliases: dict[int, set[str]] = field(default_factory=dict)
    tag_aliases: dict[int, set[str]] = field(default_factory=dict)
    studio_names: dict[int, str] = field(default_factory=dict)
    urls: dict[int, list[str]] = field(default_factory=dict)
    o_dates: dict[int, list[str]] = field(default_factory=dict)
    view_dates: dict[int, list[str]] = field(default_factory=dict)
    stash_ids: dict[int, dict[str, tuple[str, str | None]]] = field(default_factory=dict)
    markers: dict[int, list[dict]] = field(default_factory=dict)
    groups: dict[int, list[tuple[int, str, Any]]] = field(default_factory=dict)
    custom_fields: dict[int, dict[str, Any]] = field(default_factory=dict)
    galleries: dict[int, list[int]] = field(default_factory=dict)
    gallery_keys: dict[int, list[tuple]] = field(default_factory=dict)


def make_scope(conn: sqlite3.Connection, root: Root | None) -> int:
    conn.execute("DROP TABLE IF EXISTS temp.scope")
    conn.execute("CREATE TEMP TABLE scope (id INTEGER PRIMARY KEY)")
    if root is None:
        conn.execute("INSERT INTO temp.scope (id) SELECT id FROM scenes")
    else:
        conn.execute(
            """
            INSERT OR IGNORE INTO temp.scope (id)
            WITH RECURSIVE tree(id) AS (
                SELECT ?
                UNION ALL
                SELECT f.id FROM folders f JOIN tree ON f.parent_folder_id = tree.id
            )
            SELECT DISTINCT sf.scene_id
            FROM tree
            JOIN files fi ON fi.parent_folder_id = tree.id
            JOIN scenes_files sf ON sf.file_id = fi.id
            """,
            (root.folder_id,),
        )
    return int(conn.execute("SELECT COUNT(*) FROM temp.scope").fetchone()[0])


def load_side(conn: sqlite3.Connection, label: str, root: Root | None) -> Side:
    caps = Caps.detect(conn)
    side = Side(label=label, caps=caps)
    make_scope(conn, root)

    scene_cols = columns(conn, "scenes")
    for row in conn.execute("SELECT s.* FROM scenes s JOIN temp.scope sc ON sc.id = s.id"):
        side.scenes[int(row["id"])] = {c: row[c] for c in scene_cols}

    folders = {
        int(r["id"]): r["path"] for r in conn.execute("SELECT id, path FROM folders")
    }
    for row in conn.execute(
        """
        SELECT sf.scene_id, sf.[primary] AS is_primary, f.id AS file_id,
               f.basename, f.parent_folder_id
        FROM scenes_files sf
        JOIN temp.scope sc ON sc.id = sf.scene_id
        JOIN files f ON f.id = sf.file_id
        """
    ):
        scene_id = int(row["scene_id"])
        path = join_path(folders.get(int(row["parent_folder_id"]), ""), row["basename"])
        if as_bool(row["is_primary"]) or scene_id not in side.paths:
            side.paths[scene_id] = path

    for row in conn.execute(
        """
        SELECT sf.scene_id, fp.type, fp.fingerprint
        FROM scenes_files sf
        JOIN temp.scope sc ON sc.id = sf.scene_id
        JOIN files_fingerprints fp ON fp.file_id = sf.file_id
        WHERE fp.type IN ('oshash', 'md5')
        """
    ):
        side.fingerprints.setdefault(int(row["scene_id"]), set()).add(
            (row["type"], fingerprint_text(row["fingerprint"]))
        )

    for row in conn.execute(
        """
        SELECT ps.scene_id, p.id, p.name, p.disambiguation
        FROM performers_scenes ps
        JOIN temp.scope sc ON sc.id = ps.scene_id
        JOIN performers p ON p.id = ps.performer_id
        """
    ):
        side.performers.setdefault(int(row["scene_id"]), []).append(
            (int(row["id"]), row["name"], row["disambiguation"])
        )

    for row in conn.execute(
        """
        SELECT st.scene_id, t.id, t.name
        FROM scenes_tags st
        JOIN temp.scope sc ON sc.id = st.scene_id
        JOIN tags t ON t.id = st.tag_id
        """
    ):
        side.tags.setdefault(int(row["scene_id"]), []).append((int(row["id"]), row["name"]))

    for target_map, link_table, alias_table, fk in (
        (side.performer_aliases, "performers_scenes", "performer_aliases", "performer_id"),
        (side.tag_aliases, "scenes_tags", "tag_aliases", "tag_id"),
    ):
        if not has_table(conn, alias_table):
            continue
        for row in conn.execute(
            f"""
            SELECT l.scene_id, a.alias
            FROM `{link_table}` l
            JOIN temp.scope sc ON sc.id = l.scene_id
            JOIN `{alias_table}` a ON a.{fk} = l.{fk}
            """
        ):
            target_map.setdefault(int(row["scene_id"]), set()).add(low(row["alias"]))

    side.studio_names = {
        int(r["id"]): r["name"] for r in conn.execute("SELECT id, name FROM studios")
    }

    if caps.urls:
        for row in conn.execute(
            """
            SELECT u.scene_id, u.url
            FROM scene_urls u
            JOIN temp.scope sc ON sc.id = u.scene_id
            ORDER BY u.scene_id, u.position
            """
        ):
            side.urls.setdefault(int(row["scene_id"]), []).append(row["url"])

    if caps.o_dates:
        for row in conn.execute(
            """
            SELECT o.scene_id, o.o_date
            FROM scenes_o_dates o JOIN temp.scope sc ON sc.id = o.scene_id
            """
        ):
            side.o_dates.setdefault(int(row["scene_id"]), []).append(row["o_date"])

    if caps.view_dates:
        for row in conn.execute(
            """
            SELECT v.scene_id, v.view_date
            FROM scenes_view_dates v JOIN temp.scope sc ON sc.id = v.scene_id
            """
        ):
            side.view_dates.setdefault(int(row["scene_id"]), []).append(row["view_date"])

    if caps.stash_ids:
        has_updated = has_column(conn, "scene_stash_ids", "updated_at")
        select_updated = "si.updated_at" if has_updated else "NULL AS updated_at"
        for row in conn.execute(
            f"""
            SELECT si.scene_id, si.endpoint, si.stash_id, {select_updated}
            FROM scene_stash_ids si JOIN temp.scope sc ON sc.id = si.scene_id
            """
        ):
            side.stash_ids.setdefault(int(row["scene_id"]), {})[row["endpoint"]] = (
                row["stash_id"],
                row["updated_at"],
            )

    if caps.markers:
        marker_tags: dict[int, list[int]] = defaultdict(list)
        for row in conn.execute(
            """
            SELECT mt.scene_marker_id, mt.tag_id
            FROM scene_markers_tags mt
            JOIN scene_markers m ON m.id = mt.scene_marker_id
            JOIN temp.scope sc ON sc.id = m.scene_id
            """
        ):
            marker_tags[int(row["scene_marker_id"])].append(int(row["tag_id"]))
        marker_cols = columns(conn, "scene_markers")
        for row in conn.execute(
            """
            SELECT m.* FROM scene_markers m JOIN temp.scope sc ON sc.id = m.scene_id
            """
        ):
            marker = {c: row[c] for c in marker_cols}
            marker["tag_ids"] = marker_tags.get(int(row["id"]), [])
            side.markers.setdefault(int(row["scene_id"]), []).append(marker)

    if has_table(conn, "groups_scenes"):
        for row in conn.execute(
            """
            SELECT gs.scene_id, g.id, g.name, gs.scene_index
            FROM groups_scenes gs
            JOIN temp.scope sc ON sc.id = gs.scene_id
            JOIN groups g ON g.id = gs.group_id
            """
        ):
            side.groups.setdefault(int(row["scene_id"]), []).append(
                (int(row["id"]), row["name"], row["scene_index"])
            )

    if caps.custom_fields:
        for row in conn.execute(
            """
            SELECT cf.scene_id, cf.field, cf.value
            FROM scene_custom_fields cf JOIN temp.scope sc ON sc.id = cf.scene_id
            """
        ):
            side.custom_fields.setdefault(int(row["scene_id"]), {})[row["field"]] = row["value"]

    for row in conn.execute(
        """
        SELECT sg.scene_id, sg.gallery_id
        FROM scenes_galleries sg JOIN temp.scope sc ON sc.id = sg.scene_id
        """
    ):
        side.galleries.setdefault(int(row["scene_id"]), []).append(int(row["gallery_id"]))

    side.gallery_keys = load_gallery_keys(conn)
    return side


def load_gallery_keys(conn: sqlite3.Connection) -> dict[int, list[tuple]]:
    """Klucze pozwalające rozpoznać tę samą galerię w obu bazach."""
    keys: dict[int, list[tuple]] = defaultdict(list)
    folder_basename = has_column(conn, "folders", "basename")
    basename_expr = "fo.basename" if folder_basename else "fo.path"
    for row in conn.execute(
        f"""
        SELECT g.id, g.title, {basename_expr} AS folder_name
        FROM galleries g LEFT JOIN folders fo ON fo.id = g.folder_id
        """
    ):
        gallery_id = int(row["id"])
        if row["folder_name"]:
            keys[gallery_id].append(("folder", low(row["folder_name"])))
        if row["title"]:
            keys[gallery_id].append(("title", low(row["title"])))
    for row in conn.execute(
        """
        SELECT gf.gallery_id, fp.type, fp.fingerprint
        FROM galleries_files gf
        JOIN files_fingerprints fp ON fp.file_id = gf.file_id
        WHERE fp.type IN ('oshash', 'md5')
        """
    ):
        keys[int(row["gallery_id"])].append(
            ("fp", row["type"], fingerprint_text(row["fingerprint"]))
        )
    return dict(keys)


# ---------------------------------------------------------------------------
# Dopasowanie i różnice
# ---------------------------------------------------------------------------


@dataclass
class Change:
    kind: str
    label: str
    detail: str
    payload: Any


@dataclass
class Plan:
    scene_id: int
    backup_scene_id: int
    path: str
    backup_path: str
    match_type: str
    changes: list[Change]


def index_by_fingerprint(side: Side) -> dict[tuple[str, str], set[int]]:
    index: dict[tuple[str, str], set[int]] = defaultdict(set)
    for scene_id, prints in side.fingerprints.items():
        for item in prints:
            index[item].add(scene_id)
    return index


def find_candidates(
    scene_id: int, side: Side, index: dict[tuple[str, str], set[int]]
) -> tuple[str | None, set[int]]:
    prints = side.fingerprints.get(scene_id, set())
    for kind in MATCH_TYPES:
        hits: set[int] = set()
        for item in prints:
            if item[0] == kind:
                hits |= index.get(item, set())
        if hits:
            return kind, hits
    return None, set()


def gallery_lookup(target: Side) -> dict[tuple, int]:
    lookup: dict[tuple, int] = {}
    for gallery_id, keys in target.gallery_keys.items():
        for key in keys:
            lookup.setdefault(key, gallery_id)
    return lookup


def build_plan(
    target: Side,
    backup: Side,
    scene_id: int,
    backup_scene_id: int,
    match_type: str,
    caps: Caps,
    galleries: dict[tuple, int],
) -> Plan:
    dst = target.scenes[scene_id]
    src = backup.scenes[backup_scene_id]
    changes: list[Change] = []

    for column, label in SCALAR_FIELDS:
        if column not in src or column not in dst:
            continue
        if is_empty(dst[column]) and not is_empty(src[column]):
            changes.append(
                Change(f"field:{column}", label, f"(brak) → {shorten(src[column])}", src[column])
            )

    if is_empty(dst.get("date")) and not is_empty(src.get("date")):
        precision = src.get("date_precision") if caps.date_precision else None
        changes.append(
            Change("field:date", "data", f"(brak) → {src['date']}", (src["date"], precision))
        )

    if dst.get("rating") is None and src.get("rating") is not None:
        changes.append(
            Change("field:rating", "ocena", f"(brak) → {src['rating']}", src["rating"])
        )

    if not as_bool(dst.get("organized")) and as_bool(src.get("organized")):
        changes.append(Change("field:organized", "organized", "nie → tak", 1))

    if caps.play_stats:
        for column, label in (("play_duration", "czas odtwarzania"), ("resume_time", "wznowienie")):
            old, new = as_float(dst.get(column)), as_float(src.get(column))
            if old == 0 and new > 0:
                changes.append(
                    Change(f"field:{column}", label, f"0 → {new:.0f} s", new)
                )

    if dst.get("studio_id") is None and src.get("studio_id") is not None:
        name = backup.studio_names.get(int(src["studio_id"]), "?")
        changes.append(
            Change("studio", "studio", f"(brak) → {name}", int(src["studio_id"]))
        )

    have = {low(f"{n}\x00{d}") for _, n, d in target.performers.get(scene_id, [])}
    have |= {low(n) for _, n, _ in target.performers.get(scene_id, [])}
    have |= target.performer_aliases.get(scene_id, set())
    missing_performers = [
        (pid, name, disambiguation)
        for pid, name, disambiguation in backup.performers.get(backup_scene_id, [])
        if low(f"{name}\x00{disambiguation}") not in have and low(name) not in have
    ]
    if missing_performers:
        names = ", ".join(
            n if not d else f"{n} ({d})" for _, n, d in missing_performers
        )
        changes.append(
            Change("performers", "aktorzy", f"+ {shorten(names, 90)}", missing_performers)
        )

    have_tags = {low(name) for _, name in target.tags.get(scene_id, [])}
    have_tags |= target.tag_aliases.get(scene_id, set())
    missing_tags = [
        (tid, name)
        for tid, name in backup.tags.get(backup_scene_id, [])
        if low(name) not in have_tags
    ]
    if missing_tags:
        names = ", ".join(name for _, name in missing_tags)
        changes.append(Change("tags", "tagi", f"+ {shorten(names, 90)}", missing_tags))

    if caps.urls:
        have_urls = set(target.urls.get(scene_id, []))
        missing_urls = [u for u in backup.urls.get(backup_scene_id, []) if u not in have_urls]
        if missing_urls:
            changes.append(
                Change(
                    "urls",
                    "adresy URL",
                    f"+ {shorten(', '.join(missing_urls), 90)}",
                    missing_urls,
                )
            )

    if caps.o_dates:
        have_o = set(target.o_dates.get(scene_id, []))
        missing_o = [d for d in backup.o_dates.get(backup_scene_id, []) if d not in have_o]
        if missing_o:
            total = len(have_o) + len(missing_o)
            changes.append(
                Change(
                    "o_dates",
                    "O count",
                    f"{len(have_o)} → {total} (+{len(missing_o)})",
                    missing_o,
                )
            )

    if caps.view_dates:
        have_v = set(target.view_dates.get(scene_id, []))
        missing_v = [d for d in backup.view_dates.get(backup_scene_id, []) if d not in have_v]
        if missing_v:
            total = len(have_v) + len(missing_v)
            changes.append(
                Change(
                    "view_dates",
                    "historia odtwarzania",
                    f"{len(have_v)} → {total} (+{len(missing_v)})",
                    missing_v,
                )
            )

    if caps.stash_ids:
        have_ids = target.stash_ids.get(scene_id, {})
        missing_ids = {
            endpoint: value
            for endpoint, value in backup.stash_ids.get(backup_scene_id, {}).items()
            if endpoint not in have_ids
        }
        if missing_ids:
            summary = ", ".join(f"{e}: {v[0]}" for e, v in missing_ids.items())
            changes.append(Change("stash_ids", "StashDB ID", f"+ {shorten(summary, 90)}", missing_ids))

    if caps.markers:
        have_markers = {
            (round(as_float(m["seconds"]), 2), low(m["title"]))
            for m in target.markers.get(scene_id, [])
        }
        missing_markers = [
            m
            for m in backup.markers.get(backup_scene_id, [])
            if (round(as_float(m["seconds"]), 2), low(m["title"])) not in have_markers
        ]
        if missing_markers:
            summary = ", ".join(
                f"{m['title']} @ {as_float(m['seconds']):.0f}s" for m in missing_markers
            )
            changes.append(
                Change("markers", "znaczniki", f"+ {shorten(summary, 90)}", missing_markers)
            )

    if caps.groups:
        have_groups = {low(name) for _, name, _ in target.groups.get(scene_id, [])}
        missing_groups = [
            entry
            for entry in backup.groups.get(backup_scene_id, [])
            if low(entry[1]) not in have_groups
        ]
        if missing_groups:
            summary = ", ".join(name for _, name, _ in missing_groups)
            changes.append(Change("groups", "grupy", f"+ {shorten(summary, 90)}", missing_groups))

    if caps.custom_fields:
        have_fields = target.custom_fields.get(scene_id, {})
        missing_fields = {
            key: value
            for key, value in backup.custom_fields.get(backup_scene_id, {}).items()
            if key not in have_fields
        }
        if missing_fields:
            changes.append(
                Change(
                    "custom_fields",
                    "pola własne",
                    f"+ {shorten(', '.join(missing_fields), 90)}",
                    missing_fields,
                )
            )

    linked = set(target.galleries.get(scene_id, []))
    missing_galleries: list[int] = []
    for backup_gallery in backup.galleries.get(backup_scene_id, []):
        for key in backup.gallery_keys.get(backup_gallery, []):
            resolved = galleries.get(key)
            if resolved is not None and resolved not in linked:
                missing_galleries.append(resolved)
                linked.add(resolved)
                break
    if missing_galleries:
        changes.append(
            Change(
                "galleries",
                "galerie",
                f"+ {len(missing_galleries)}",
                missing_galleries,
            )
        )

    return Plan(
        scene_id=scene_id,
        backup_scene_id=backup_scene_id,
        path=target.paths.get(scene_id, f"scene #{scene_id}"),
        backup_path=backup.paths.get(backup_scene_id, f"scene #{backup_scene_id}"),
        match_type=match_type,
        changes=changes,
    )


@dataclass
class Analysis:
    plans: list[Plan]
    matched: dict[str, int]
    unmatched: list[str]
    ambiguous: list[str]
    identical: int


def analyse(target: Side, backup: Side, caps: Caps) -> Analysis:
    index = index_by_fingerprint(backup)
    galleries = gallery_lookup(target)
    plans: list[Plan] = []
    matched: dict[str, int] = defaultdict(int)
    unmatched: list[str] = []
    ambiguous: list[str] = []
    identical = 0

    for scene_id in sorted(target.scenes):
        match_type, candidates = find_candidates(scene_id, target, index)
        if not candidates:
            unmatched.append(target.paths.get(scene_id, f"scene #{scene_id}"))
            continue
        matched[match_type] += 1

        built = [
            build_plan(target, backup, scene_id, candidate, match_type, caps, galleries)
            for candidate in sorted(candidates)
        ]
        built.sort(key=lambda p: len(p.changes), reverse=True)
        best = built[0]
        if len(built) > 1 and len(built[1].changes) == len(best.changes) and best.changes:
            ambiguous.append(
                f"{target.paths.get(scene_id, scene_id)} → {len(built)} kandydatów w kopii"
            )
            continue
        if not best.changes:
            identical += 1
            continue
        plans.append(best)

    return Analysis(plans, dict(matched), unmatched, ambiguous, identical)


# ---------------------------------------------------------------------------
# Mapowanie encji między bazami
# ---------------------------------------------------------------------------


class EntityMapper:
    """Odwzorowuje aktorów / studia / tagi / grupy z BA2 na BA1 (po nazwie),
    tworząc brakujące wpisy."""

    BLOB_COLUMNS = ("image_blob", "cover_blob", "front_image_blob", "back_image_blob")

    def __init__(self, out: sqlite3.Connection, src: sqlite3.Connection) -> None:
        self.out = out
        self.src = src
        self.created: dict[str, int] = defaultdict(int)
        self.cache: dict[str, dict[int, int | None]] = {
            "performers": {},
            "tags": {},
            "studios": {},
            "groups": {},
        }
        self.by_name: dict[str, dict[str, int]] = {
            "performers": {},
            "tags": {},
            "studios": {},
            "groups": {},
        }
        self.performers_by_key: dict[tuple[str, str], int] = {}
        self.ambiguous_performers: set[str] = set()
        self._build_indexes()

    def _build_indexes(self) -> None:
        counts: dict[str, int] = defaultdict(int)
        for row in self.out.execute(
            "SELECT id, name, disambiguation FROM performers ORDER BY id"
        ):
            pid = int(row["id"])
            name = low(row["name"])
            self.performers_by_key[(name, low(row["disambiguation"]))] = pid
            counts[name] += 1
            self.by_name["performers"].setdefault(name, pid)
        self.ambiguous_performers = {name for name, count in counts.items() if count > 1}

        for table in ("tags", "studios", "groups"):
            if not has_table(self.out, table):
                continue
            for row in self.out.execute(f"SELECT id, name FROM `{table}` ORDER BY id"):
                self.by_name[table].setdefault(low(row["name"]), int(row["id"]))

        for kind, alias_table, alias_fk in (
            ("performers", "performer_aliases", "performer_id"),
            ("tags", "tag_aliases", "tag_id"),
            ("studios", "studio_aliases", "studio_id"),
        ):
            self._index_aliases(kind, alias_table, alias_fk)

    def _index_aliases(self, kind: str, alias_table: str, alias_fk: str) -> None:
        """Aliasy są traktowane jak dodatkowe nazwy, ale tylko gdy jednoznacznie
        wskazują jeden wpis. W bazach Stash aliasy aktorów bywają wspólne dla
        wielu osób ('Kenna', 'Rikki'), więc takie zbitki trzeba pominąć."""
        if not has_table(self.out, alias_table):
            return
        owners: dict[str, set[int]] = defaultdict(set)
        # Złączenie z tabelą nadrzędną odsiewa osierocone wiersze aliasów.
        for row in self.out.execute(
            f"SELECT a.{alias_fk} AS owner_id, a.alias AS alias FROM `{alias_table}` a"
            f" JOIN `{kind}` t ON t.id = a.{alias_fk}"
        ):
            alias = low(row["alias"])
            if alias:
                owners[alias].add(int(row["owner_id"]))
        for alias, ids in owners.items():
            if len(ids) == 1:
                self.by_name[kind].setdefault(alias, next(iter(ids)))

    def _src_row(self, table: str, row_id: int) -> sqlite3.Row | None:
        return self.src.execute(f"SELECT * FROM `{table}` WHERE id = ?", (row_id,)).fetchone()

    def _copy_row(
        self,
        table: str,
        row: sqlite3.Row,
        overrides: dict[str, Any] | None = None,
    ) -> int:
        available = set(columns(self.out, table))
        pairs: list[tuple[str, Any]] = [
            (name, row[name])
            for name in row.keys()
            if name in available and name != "id" and name not in self.BLOB_COLUMNS
        ]
        keys = [name for name, _ in pairs]
        for name, value in (overrides or {}).items():
            if name not in available:
                continue
            if name in keys:
                pairs[keys.index(name)] = (name, value)
            else:
                pairs.append((name, value))
                keys.append(name)
        placeholders = ", ".join("?" for _ in pairs)
        column_list = ", ".join(f"`{name}`" for name, _ in pairs)
        cursor = self.out.execute(
            f"INSERT INTO `{table}` ({column_list}) VALUES ({placeholders})",
            [value for _, value in pairs],
        )
        self.created[table] += 1
        return int(cursor.lastrowid)

    def _copy_children(self, table: str, fk: str, src_id: int, new_id: int) -> None:
        if not has_table(self.src, table) or not has_table(self.out, table):
            return
        available = set(columns(self.out, table))
        for row in self.src.execute(f"SELECT * FROM `{table}` WHERE {fk} = ?", (src_id,)).fetchall():
            values = {name: row[name] for name in row.keys() if name in available}
            values[fk] = new_id
            column_list = ", ".join(f"`{name}`" for name in values)
            placeholders = ", ".join("?" for _ in values)
            self.out.execute(
                f"INSERT OR IGNORE INTO `{table}` ({column_list}) VALUES ({placeholders})",
                list(values.values()),
            )

    # -- konkretne encje ----------------------------------------------------

    def tag(self, src_id: int) -> int | None:
        cached = self.cache["tags"].get(src_id)
        if cached is not None:
            return cached
        row = self._src_row("tags", src_id)
        if row is None:
            return None
        existing = self.by_name["tags"].get(low(row["name"]))
        if existing is not None:
            self.cache["tags"][src_id] = existing
            return existing

        new_id = self._copy_row("tags", row)
        self.cache["tags"][src_id] = new_id
        self.by_name["tags"].setdefault(low(row["name"]), new_id)
        self._copy_children("tag_aliases", "tag_id", src_id, new_id)
        self._copy_children("tag_stash_ids", "tag_id", src_id, new_id)
        if has_table(self.src, "tags_relations") and has_table(self.out, "tags_relations"):
            for relation in self.src.execute(
                "SELECT parent_id FROM tags_relations WHERE child_id = ?", (src_id,)
            ).fetchall():
                parent = self.tag(int(relation["parent_id"]))
                if parent is not None:
                    self.out.execute(
                        "INSERT OR IGNORE INTO tags_relations (parent_id, child_id) VALUES (?, ?)",
                        (parent, new_id),
                    )
        return new_id

    def studio(self, src_id: int, _guard: set[int] | None = None) -> int | None:
        cached = self.cache["studios"].get(src_id)
        if cached is not None:
            return cached
        row = self._src_row("studios", src_id)
        if row is None:
            return None
        existing = self.by_name["studios"].get(low(row["name"]))
        if existing is not None:
            self.cache["studios"][src_id] = existing
            return existing

        guard = _guard or set()
        parent = None
        if row["parent_id"] is not None and int(row["parent_id"]) not in guard:
            parent = self.studio(int(row["parent_id"]), guard | {src_id})

        new_id = self._copy_row("studios", row, overrides={"parent_id": parent})
        self.cache["studios"][src_id] = new_id
        self.by_name["studios"].setdefault(low(row["name"]), new_id)
        self._copy_children("studio_aliases", "studio_id", src_id, new_id)
        self._copy_children("studio_urls", "studio_id", src_id, new_id)
        self._copy_children("studio_stash_ids", "studio_id", src_id, new_id)
        self._copy_tag_links("studios_tags", "studio_id", src_id, new_id)
        return new_id

    def performer(self, src_id: int) -> int | None:
        cached = self.cache["performers"].get(src_id)
        if cached is not None:
            return cached
        row = self._src_row("performers", src_id)
        if row is None:
            return None
        name = low(row["name"])
        key = (name, low(row["disambiguation"]))
        existing = self.performers_by_key.get(key)
        if existing is None and name not in self.ambiguous_performers:
            existing = self.by_name["performers"].get(name)
        if existing is not None:
            self.cache["performers"][src_id] = existing
            return existing

        new_id = self._copy_row("performers", row)
        self.cache["performers"][src_id] = new_id
        self.performers_by_key[key] = new_id
        if name in self.by_name["performers"]:
            # Ta sama nazwa, inne rozróżnienie - od teraz nie zgadujemy.
            self.ambiguous_performers.add(name)
        else:
            self.by_name["performers"][name] = new_id
        self._copy_children("performer_aliases", "performer_id", src_id, new_id)
        self._copy_children("performer_urls", "performer_id", src_id, new_id)
        self._copy_children("performer_stash_ids", "performer_id", src_id, new_id)
        self._copy_tag_links("performers_tags", "performer_id", src_id, new_id)
        return new_id

    def group(self, src_id: int) -> int | None:
        cached = self.cache["groups"].get(src_id)
        if cached is not None:
            return cached
        row = self._src_row("groups", src_id)
        if row is None:
            return None
        existing = self.by_name["groups"].get(low(row["name"]))
        if existing is not None:
            self.cache["groups"][src_id] = existing
            return existing
        studio = self.studio(int(row["studio_id"])) if row["studio_id"] is not None else None
        new_id = self._copy_row("groups", row, overrides={"studio_id": studio})
        self.cache["groups"][src_id] = new_id
        self.by_name["groups"].setdefault(low(row["name"]), new_id)
        self._copy_children("group_urls", "group_id", src_id, new_id)
        self._copy_tag_links("groups_tags", "group_id", src_id, new_id)
        return new_id

    def _copy_tag_links(self, table: str, fk: str, src_id: int, new_id: int) -> None:
        if not has_table(self.src, table) or not has_table(self.out, table):
            return
        for row in self.src.execute(f"SELECT tag_id FROM `{table}` WHERE {fk} = ?", (src_id,)).fetchall():
            tag_id = self.tag(int(row["tag_id"]))
            if tag_id is not None:
                self.out.execute(
                    f"INSERT OR IGNORE INTO `{table}` ({fk}, tag_id) VALUES (?, ?)",
                    (new_id, tag_id),
                )


# ---------------------------------------------------------------------------
# Zapis
# ---------------------------------------------------------------------------


def restored_path(source: Path) -> Path:
    if source.suffix:
        return source.with_name(f"{source.stem}_restored{source.suffix}")
    return source.with_name(f"{source.name}_restored")


def copy_database(source: sqlite3.Connection, destination: Path) -> sqlite3.Connection:
    if destination.exists():
        raise FileExistsError(destination)
    out = sqlite3.connect(str(destination))
    source.backup(out)
    out.row_factory = sqlite3.Row
    out.isolation_level = None
    out.execute("PRAGMA foreign_keys = ON")
    return out


def apply_change(out: sqlite3.Connection, mapper: EntityMapper, plan: Plan, change: Change) -> None:
    scene_id = plan.scene_id
    kind = change.kind

    if kind == "field:date":
        date, precision = change.payload
        if precision is not None and has_column(out, "scenes", "date_precision"):
            out.execute(
                "UPDATE scenes SET date = ?, date_precision = ? WHERE id = ?",
                (date, precision, scene_id),
            )
        else:
            out.execute("UPDATE scenes SET date = ? WHERE id = ?", (date, scene_id))
        return

    if kind.startswith("field:"):
        column = kind.split(":", 1)[1]
        out.execute(f"UPDATE scenes SET `{column}` = ? WHERE id = ?", (change.payload, scene_id))
        return

    if kind == "studio":
        studio_id = mapper.studio(int(change.payload))
        if studio_id is not None:
            out.execute("UPDATE scenes SET studio_id = ? WHERE id = ?", (studio_id, scene_id))
        return

    if kind == "performers":
        for src_performer_id, _, _ in change.payload:
            performer_id = mapper.performer(int(src_performer_id))
            if performer_id is not None:
                out.execute(
                    "INSERT OR IGNORE INTO performers_scenes (performer_id, scene_id) VALUES (?, ?)",
                    (performer_id, scene_id),
                )
        return

    if kind == "tags":
        for src_tag_id, _ in change.payload:
            tag_id = mapper.tag(int(src_tag_id))
            if tag_id is not None:
                out.execute(
                    "INSERT OR IGNORE INTO scenes_tags (scene_id, tag_id) VALUES (?, ?)",
                    (scene_id, tag_id),
                )
        return

    if kind == "urls":
        row = out.execute(
            "SELECT COALESCE(MAX(position), -1) FROM scene_urls WHERE scene_id = ?", (scene_id,)
        ).fetchone()
        position = int(row[0]) + 1
        for url in change.payload:
            out.execute(
                "INSERT OR IGNORE INTO scene_urls (scene_id, position, url) VALUES (?, ?, ?)",
                (scene_id, position, url),
            )
            position += 1
        return

    if kind == "o_dates":
        for value in change.payload:
            exists = out.execute(
                "SELECT 1 FROM scenes_o_dates WHERE scene_id = ? AND o_date = ?",
                (scene_id, value),
            ).fetchone()
            if exists is None:
                out.execute(
                    "INSERT INTO scenes_o_dates (scene_id, o_date) VALUES (?, ?)",
                    (scene_id, value),
                )
        return

    if kind == "view_dates":
        for value in change.payload:
            exists = out.execute(
                "SELECT 1 FROM scenes_view_dates WHERE scene_id = ? AND view_date = ?",
                (scene_id, value),
            ).fetchone()
            if exists is None:
                out.execute(
                    "INSERT INTO scenes_view_dates (scene_id, view_date) VALUES (?, ?)",
                    (scene_id, value),
                )
        return

    if kind == "stash_ids":
        has_updated = has_column(out, "scene_stash_ids", "updated_at")
        for endpoint, (stash_id, updated_at) in change.payload.items():
            if has_updated:
                out.execute(
                    "INSERT OR IGNORE INTO scene_stash_ids (scene_id, endpoint, stash_id, updated_at)"
                    " VALUES (?, ?, ?, ?)",
                    (scene_id, endpoint, stash_id, updated_at or now_rfc3339()),
                )
            else:
                out.execute(
                    "INSERT OR IGNORE INTO scene_stash_ids (scene_id, endpoint, stash_id)"
                    " VALUES (?, ?, ?)",
                    (scene_id, endpoint, stash_id),
                )
        return

    if kind == "markers":
        has_end = has_column(out, "scene_markers", "end_seconds")
        for marker in change.payload:
            primary_tag = mapper.tag(int(marker["primary_tag_id"]))
            if primary_tag is None:
                continue
            fields = {
                "title": marker["title"],
                "seconds": marker["seconds"],
                "primary_tag_id": primary_tag,
                "scene_id": scene_id,
                "created_at": marker.get("created_at") or now_rfc3339(),
                "updated_at": marker.get("updated_at") or now_rfc3339(),
            }
            if has_end:
                fields["end_seconds"] = marker.get("end_seconds")
            column_list = ", ".join(f"`{name}`" for name in fields)
            placeholders = ", ".join("?" for _ in fields)
            cursor = out.execute(
                f"INSERT INTO scene_markers ({column_list}) VALUES ({placeholders})",
                list(fields.values()),
            )
            marker_id = int(cursor.lastrowid)
            for src_tag_id in marker.get("tag_ids", []):
                tag_id = mapper.tag(int(src_tag_id))
                if tag_id is not None:
                    out.execute(
                        "INSERT OR IGNORE INTO scene_markers_tags (scene_marker_id, tag_id)"
                        " VALUES (?, ?)",
                        (marker_id, tag_id),
                    )
        return

    if kind == "groups":
        for src_group_id, _, scene_index in change.payload:
            group_id = mapper.group(int(src_group_id))
            if group_id is not None:
                out.execute(
                    "INSERT OR IGNORE INTO groups_scenes (group_id, scene_id, scene_index)"
                    " VALUES (?, ?, ?)",
                    (group_id, scene_id, scene_index),
                )
        return

    if kind == "custom_fields":
        for name, value in change.payload.items():
            out.execute(
                "INSERT OR IGNORE INTO scene_custom_fields (scene_id, field, value) VALUES (?, ?, ?)",
                (scene_id, name, value),
            )
        return

    if kind == "galleries":
        for gallery_id in change.payload:
            out.execute(
                "INSERT OR IGNORE INTO scenes_galleries (scene_id, gallery_id) VALUES (?, ?)",
                (scene_id, gallery_id),
            )
        return

    raise ValueError(f"Nieznany rodzaj zmiany: {kind}")


def apply_plans(
    out: sqlite3.Connection,
    backup_conn: sqlite3.Connection,
    plans: Sequence[Plan],
    touch_updated_at: bool,
) -> tuple[int, int, dict[str, int], list[str]]:
    mapper = EntityMapper(out, backup_conn)
    errors: list[str] = []
    applied_scenes = 0
    applied_changes = 0
    stamp = now_rfc3339()

    out.execute("BEGIN")
    try:
        for plan in plans:
            for change in plan.changes:
                try:
                    apply_change(out, mapper, plan, change)
                    applied_changes += 1
                except sqlite3.Error as exc:
                    errors.append(f"{plan.path} [{change.kind}]: {exc}")
            if touch_updated_at:
                out.execute("UPDATE scenes SET updated_at = ? WHERE id = ?", (stamp, plan.scene_id))
            applied_scenes += 1
        out.commit()
    except Exception:
        out.rollback()
        raise

    return applied_scenes, applied_changes, dict(mapper.created), errors


# ---------------------------------------------------------------------------
# Interfejs
# ---------------------------------------------------------------------------


def print_plan(plan: Plan, position: int, total: int) -> None:
    print()
    print("─" * 78)
    print(f"[{position}/{total}] {plan.path}")
    if plan.backup_path != plan.path:
        print(f"          kopia: {plan.backup_path}")
    print(f"          dopasowanie: {plan.match_type}, scena #{plan.backup_scene_id} w kopii")
    for change in plan.changes:
        print(f"    {change.label:<22} {change.detail}")


def review(plans: list[Plan], auto: bool) -> tuple[list[Plan], bool]:
    """Zwraca zatwierdzone plany oraz informację, czy zapisywać wynik."""
    if auto:
        return list(plans), True

    approved: list[Plan] = []
    total = len(plans)
    print(
        "\nKlawisze: [t] zastosuj  [n] pomiń  [w] zastosuj wszystkie pozostałe"
        "\n          [p] zakończ przegląd i zapisz zatwierdzone  [q] anuluj bez zapisu"
    )
    for position, plan in enumerate(plans, start=1):
        print_plan(plan, position, total)
        while True:
            answer = prompt("    Zastosować? [t/n/w/p/q]: ").lower()
            if answer in ("", "t", "tak", "y", "yes"):
                approved.append(plan)
                break
            if answer in ("n", "nie", "no"):
                break
            if answer in ("w", "wszystkie", "a", "all"):
                approved.extend(plans[position - 1 :])
                print(f"\n  → Automatyczne zatwierdzenie pozostałych ({total - position + 1}).")
                return approved, True
            if answer in ("p", "koniec"):
                return approved, True
            if answer in ("q", "anuluj"):
                return [], False
            print("    Nieznana odpowiedź.")
    return approved, True


def write_report(
    path: Path,
    target_path: Path,
    backup_path: Path,
    target_root: Root | None,
    backup_root: Root | None,
    analysis: Analysis,
    approved: Sequence[Plan],
    created: dict[str, int],
    errors: Sequence[str],
) -> None:
    lines: list[str] = []
    lines.append(f"Raport odzyskiwania metadanych - {now_rfc3339()}")
    lines.append(f"Baza docelowa : {target_path}")
    lines.append(f"Biblioteka    : {target_root.path if target_root else '(wszystkie)'}")
    lines.append(f"Kopia zapasowa: {backup_path}")
    lines.append(f"Biblioteka    : {backup_root.path if backup_root else '(wszystkie)'}")
    lines.append("")
    lines.append(f"Dopasowania    : {analysis.matched}")
    lines.append(f"Bez zmian      : {analysis.identical}")
    lines.append(f"Niedopasowane  : {len(analysis.unmatched)}")
    lines.append(f"Niejednoznaczne: {len(analysis.ambiguous)}")
    lines.append(f"Zastosowane    : {len(approved)}")
    lines.append(f"Utworzone wpisy: {created}")
    lines.append("")

    if errors:
        lines.append("BŁĘDY:")
        lines.extend(f"  {item}" for item in errors)
        lines.append("")

    lines.append("ZASTOSOWANE ZMIANY:")
    for plan in approved:
        lines.append(f"  {plan.path}")
        for change in plan.changes:
            lines.append(f"      {change.label}: {change.detail}")

    if analysis.ambiguous:
        lines.append("")
        lines.append("NIEJEDNOZNACZNE (pominięte):")
        lines.extend(f"  {item}" for item in analysis.ambiguous)

    if analysis.unmatched:
        lines.append("")
        lines.append("NIEDOPASOWANE (brak odpowiednika w kopii):")
        lines.extend(f"  {item}" for item in analysis.unmatched)

    path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> int:
    out_encoding_fix()

    parser = argparse.ArgumentParser(
        description="Odzyskiwanie metadanych scen ze starszej kopii bazy Stash."
    )
    parser.add_argument("--target", help="ścieżka do bazy docelowej BA1")
    parser.add_argument("--target-library", help="ścieżka biblioteki BI1 (pomija pytanie)")
    parser.add_argument("--backup", help="ścieżka do bazy z kopii zapasowej BA2")
    parser.add_argument("--backup-library", help="ścieżka biblioteki BI2 (pomija pytanie)")
    parser.add_argument("--output", help="ścieżka wynikowej bazy (domyślnie BA1 + '_restored')")
    parser.add_argument(
        "--yes", action="store_true", help="zastosuj wszystkie różnice bez pytania"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="tylko analiza i raport, bez zapisu bazy"
    )
    parser.add_argument(
        "--keep-updated-at",
        action="store_true",
        help="nie zmieniaj scenes.updated_at dla zmodyfikowanych scen",
    )
    args = parser.parse_args()

    print("=" * 78)
    print(" Odzyskiwanie metadanych scen ze starszej kopii bazy Stash")
    print("=" * 78)

    target_conn: sqlite3.Connection | None = None
    backup_conn: sqlite3.Connection | None = None
    try:
        print("\n[1/4] Baza docelowa (BA1) - ta, do której chcemy przywrócić dane")
        target_path, target_conn = ask_database("BA1", args.target)

        print("\n[2/4] Biblioteka w bazie docelowej (BI1)")
        target_root = choose_root(target_conn, "BI1", args.target_library)

        print("\n[3/4] Baza z kopii zapasowej (BA2) - źródło utraconych danych")
        backup_path, backup_conn = ask_database("BA2", args.backup)

        print("\n[4/4] Biblioteka w kopii zapasowej (BI2)")
        backup_root = choose_root(backup_conn, "BI2", args.backup_library)

        if target_path.resolve() == backup_path.resolve():
            print("\n! BA1 i BA2 wskazują ten sam plik. Przerywam.")
            return 1

        target_version = schema_version(target_conn)
        backup_version = schema_version(backup_conn)
        if backup_version and target_version and backup_version > target_version:
            print(
                f"\n! Uwaga: kopia ma nowszy schemat (v{backup_version}) niż baza docelowa"
                f" (v{target_version}). Część danych może zostać pominięta."
            )

        print("\nWczytuję dane...")
        target = load_side(target_conn, "BA1", target_root)
        print(f"  BA1/BI1: {len(target.scenes)} scen")
        backup = load_side(backup_conn, "BA2", backup_root)
        print(f"  BA2/BI2: {len(backup.scenes)} scen")

        caps = target.caps.common(backup.caps)
        skipped = [
            CAPS_LABELS.get(name, name)
            for name in caps.__dataclass_fields__
            if not getattr(caps, name)
        ]
        if skipped:
            print(f"  Pomijane (brak w którejś z baz): {', '.join(skipped)}")
        if not backup.caps.o_dates and has_column(backup_conn, "scenes", "o_counter"):
            print(
                "  ! Kopia przechowuje O count jako licznik (scenes.o_counter), bez dat."
                "\n    Tej wartości nie da się wiernie odtworzyć w nowym schemacie - pomijam."
            )

        print("\nDopasowuję sceny po odcisku pliku...")
        analysis = analyse(target, backup, caps)

        print("\n" + "=" * 78)
        print(" PODSUMOWANIE ANALIZY")
        print("=" * 78)
        for kind in MATCH_TYPES:
            if analysis.matched.get(kind):
                print(f"  Dopasowane po {kind:<7}: {analysis.matched[kind]}")
        print(f"  Bez odpowiednika w kopii: {len(analysis.unmatched)}")
        print(f"  Niejednoznaczne (pominięte): {len(analysis.ambiguous)}")
        print(f"  Dopasowane, brak nowych danych: {analysis.identical}")
        print(f"  SCEN Z RÓŻNICAMI DO PRZYWRÓCENIA: {len(analysis.plans)}")

        change_counts: dict[str, int] = defaultdict(int)
        for plan in analysis.plans:
            for change in plan.changes:
                change_counts[change.label] += 1
        if change_counts:
            print("\n  Różnice wg rodzaju:")
            for label, count in sorted(change_counts.items(), key=lambda kv: -kv[1]):
                print(f"    {label:<24} {count}")

        if not analysis.plans:
            print("\nNie ma czego przywracać. Koniec.")
            return 0

        output_path = Path(args.output) if args.output else restored_path(target_path)
        print(f"\n  Plik wynikowy: {output_path}")
        if output_path.exists():
            print("  ! Plik wynikowy już istnieje - usuń go lub podaj --output. Przerywam.")
            return 1

        if not args.yes and not args.dry_run:
            if prompt("\nRozpocząć przegląd różnic? [T/n]: ").lower() in ("n", "nie"):
                return 0

        approved, save = review(analysis.plans, auto=args.yes or args.dry_run)

        if not save or not approved:
            print("\nNic nie zatwierdzono - nie zapisuję.")
            return 0

        report_path = output_path.with_name(output_path.name + "_report.txt")

        if args.dry_run:
            write_report(
                report_path, target_path, backup_path, target_root, backup_root,
                analysis, approved, {}, [],
            )
            print(f"\n[dry-run] Raport: {report_path}")
            return 0

        print(f"\nTworzę kopię roboczą bazy: {output_path}")
        out = copy_database(target_conn, output_path)
        try:
            print(f"Stosuję zmiany dla {len(approved)} scen...")
            scenes, changes, created, errors = apply_plans(
                out, backup_conn, approved, touch_updated_at=not args.keep_updated_at
            )
            out.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            out.close()

        write_report(
            report_path, target_path, backup_path, target_root, backup_root,
            analysis, approved, created, errors,
        )

        print("\n" + "=" * 78)
        print(" GOTOWE")
        print("=" * 78)
        print(f"  Zaktualizowane sceny : {scenes}")
        print(f"  Zastosowane zmiany   : {changes}")
        if created:
            print(f"  Utworzone wpisy      : {created}")
        if errors:
            print(f"  BŁĘDY                : {len(errors)} (szczegóły w raporcie)")
        print(f"  Nowa baza            : {output_path}")
        print(f"  Raport               : {report_path}")
        print(
            "\n  BA1 i BA2 pozostały nietknięte. Aby użyć wyniku, zatrzymaj Stash"
            "\n  i wskaż nową bazę w config.yml (albo podmień plik po zrobieniu kopii)."
        )
        return 0
    finally:
        for conn in (target_conn, backup_conn):
            if conn is not None:
                conn.close()
        TEMP_COPIES.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())

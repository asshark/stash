#!/usr/bin/env python3
"""Convert a native Stash JSON export (Settings > Tasks > Export) into an
Open Knowledge Format (OKF v0.2) bundle for use as an agent-searchable
knowledge base.

Usage:
    python stash_export_to_okf.py --export-dir L:\\stash\\metadata --out .

The export dir is the Stash "metadata" path (see config.yml -> metadata),
which after running a full export contains: performers/, scenes/, tags/,
studios/, movies/ (= groups), galleries/, images/ -- one JSON file per
entity, in the format documented in pkg/models/jsonschema.

The output bundle is written as:
    <out>/index.md               bundle root (okf_version: "0.2")
    <out>/log.md
    <out>/performers/<slug>.md
    <out>/scenes/<slug>.md
    <out>/tags/<slug>.md
    <out>/studios/<slug>.md
    <out>/groups/<slug>.md
    <out>/galleries/<slug>.md

Cross-references (scene <-> performer/tag/studio/group) are resolved by
name, matching Stash's own export/import convention. Performer, tag,
studio and group pages include a reverse-link section built from the
scene data (e.g. a performer page lists the scenes they appear in).

Re-running the script clears and regenerates each concept subdirectory, so
it is safe to run repeatedly after refreshing the Stash export.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

GENERATOR_ID = "process:stash-okf-export"


# ---------------------------------------------------------------------------
# generic helpers
# ---------------------------------------------------------------------------


def load_json_dir(dir_path: Path) -> list[dict]:
    if not dir_path.is_dir():
        return []
    records = []
    for f in sorted(dir_path.glob("*.json")):
        try:
            with f.open("r", encoding="utf-8") as fh:
                records.append(json.load(fh))
        except (OSError, json.JSONDecodeError) as e:
            print(f"  ! skipping {f}: {e}")
    return records


def slugify(text: str, fallback: str) -> str:
    text = text or ""
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_text).strip("-").lower()
    return slug or fallback


def unique_slug(base: str, used: set[str]) -> str:
    slug = base
    n = 2
    while slug in used:
        slug = f"{base}-{n}"
        n += 1
    used.add(slug)
    return slug


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def frontmatter(fields: dict[str, Any]) -> str:
    clean = {k: v for k, v in fields.items() if v not in (None, "", [], {})}
    dumped = yaml.safe_dump(clean, sort_keys=False, allow_unicode=True, width=4096)
    return f"---\n{dumped}---\n"


def write_concept(path: Path, fields: dict[str, Any], body: str) -> None:
    path.write_text(frontmatter(fields) + "\n" + body.strip() + "\n", encoding="utf-8")


def md_link(title: str, href: str) -> str:
    return f"[{title}]({href})"


def links_section(heading: str, items: list[str]) -> str:
    if not items:
        return ""
    body = f"## {heading}\n\n"
    body += "\n".join(f"- {item}" for item in items)
    return body + "\n\n"


def table_section(heading: str, rows: list[tuple[str, Any]]) -> str:
    rows = [(k, v) for k, v in rows if v not in (None, "", [], {}, 0, False)]
    if not rows:
        return ""
    body = f"## {heading}\n\n| Pole | Wartość |\n|---|---|\n"
    for k, v in rows:
        body += f"| {k} | {v} |\n"
    return body + "\n"


def reset_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# name -> slug index (handles duplicate names, e.g. performers with the same
# stage name disambiguated by the `disambiguation` field)
# ---------------------------------------------------------------------------


class NameIndex:
    def __init__(self, dir_name: str):
        self.dir_name = dir_name
        self.by_name: dict[str, list[str]] = defaultdict(list)

    def add(self, name: str, slug: str) -> None:
        self.by_name[name].append(slug)

    def links(self, name: str) -> list[str]:
        slugs = self.by_name.get(name)
        if not slugs:
            return [f"{name} _(brak dopasowania w eksporcie)_"]
        return [md_link(name, f"/{self.dir_name}/{s}.md") for s in slugs]

    def link(self, name: str) -> str:
        return self.links(name)[0]

    def href(self, name: str) -> str | None:
        slugs = self.by_name.get(name)
        return f"/{self.dir_name}/{slugs[0]}.md" if slugs else None


# ---------------------------------------------------------------------------
# phase 1: slug assignment (no cross-references needed yet)
# ---------------------------------------------------------------------------


def assign_performers(records: list[dict]) -> tuple[NameIndex, list[tuple[str, dict]]]:
    index = NameIndex("performers")
    used: set[str] = set()
    slugged = []
    for rec in records:
        name = rec.get("name", "")
        disamb = rec.get("disambiguation", "")
        base = slugify(f"{name}-{disamb}" if disamb else name, fallback="performer")
        slug = unique_slug(base, used)
        index.add(name, slug)
        slugged.append((slug, rec))
    return index, slugged


def assign_tags(records: list[dict]) -> tuple[NameIndex, list[tuple[str, dict]]]:
    index = NameIndex("tags")
    used: set[str] = set()
    slugged = []
    for rec in records:
        slug = unique_slug(slugify(rec.get("name", ""), fallback="tag"), used)
        index.add(rec.get("name", ""), slug)
        slugged.append((slug, rec))
    return index, slugged


def assign_studios(records: list[dict]) -> tuple[NameIndex, list[tuple[str, dict]]]:
    index = NameIndex("studios")
    used: set[str] = set()
    slugged = []
    for rec in records:
        slug = unique_slug(slugify(rec.get("name", ""), fallback="studio"), used)
        index.add(rec.get("name", ""), slug)
        slugged.append((slug, rec))
    return index, slugged


def assign_groups(records: list[dict]) -> tuple[NameIndex, list[tuple[str, dict]]]:
    index = NameIndex("groups")
    used: set[str] = set()
    slugged = []
    for rec in records:
        slug = unique_slug(slugify(rec.get("name", ""), fallback="group"), used)
        index.add(rec.get("name", ""), slug)
        slugged.append((slug, rec))
    return index, slugged


def assign_galleries(records: list[dict]) -> tuple[NameIndex, list[tuple[str, dict]]]:
    index = NameIndex("galleries")
    used: set[str] = set()
    slugged = []
    for i, rec in enumerate(records):
        title = rec.get("title") or rec.get("folder_path") or f"gallery-{i}"
        slug = unique_slug(slugify(title, fallback=f"gallery-{i}"), used)
        index.add(rec.get("title", ""), slug)
        slugged.append((slug, rec))
    return index, slugged


def assign_scenes(records: list[dict]) -> tuple[NameIndex, list[tuple[str, dict]]]:
    index = NameIndex("scenes")
    used: set[str] = set()
    slugged = []
    for i, rec in enumerate(records):
        title = rec.get("title") or ""
        base = slugify(title, fallback="") or slugify(
            Path(rec.get("files", [""])[0]).stem if rec.get("files") else "", fallback=f"scene-{i}"
        )
        slug = unique_slug(base, used)
        index.add(title, slug)
        slugged.append((slug, rec))
    return index, slugged


# ---------------------------------------------------------------------------
# phase 2: reverse indices, derived from scene/group/gallery records
# ---------------------------------------------------------------------------


def build_reverse_indices(
    scenes: list[tuple[str, dict]],
    groups_raw: list[dict],
    galleries_raw: list[dict],
    performers_raw: list[dict],
    studios_raw: list[dict],
):
    performer_scenes: dict[str, list[dict]] = defaultdict(list)
    group_scenes: dict[str, list[dict]] = defaultdict(list)
    tag_usage: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    studio_usage: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for slug, rec in scenes:
        title = rec.get("title") or f"Scena bez tytułu ({slug})"
        date = rec.get("date")
        studio = rec.get("studio")
        for p in rec.get("performers", []):
            performer_scenes[p].append({"slug": slug, "title": title, "date": date, "studio": studio})
        for t in rec.get("tags", []):
            tag_usage[t]["scenes"] += 1
        if studio:
            studio_usage[studio]["scenes"] += 1
        for g in rec.get("movies", []):
            gname = g.get("movieName", "")
            if gname:
                group_scenes[gname].append({"slug": slug, "title": title, "scene_index": g.get("scene_index")})

    for name, buckets in performer_scenes.items():
        buckets.sort(key=lambda s: s.get("date") or "", reverse=True)
    for name, buckets in group_scenes.items():
        buckets.sort(key=lambda s: s.get("scene_index") or 0)

    for rec in performers_raw:
        for t in rec.get("tags", []):
            tag_usage[t]["performers"] += 1

    for rec in studios_raw:
        for t in rec.get("tags", []):
            tag_usage[t]["studios"] += 1

    for rec in groups_raw:
        for t in rec.get("tags", []):
            tag_usage[t]["groups"] += 1
        studio = rec.get("studio")
        if studio:
            studio_usage[studio]["groups"] += 1

    for rec in galleries_raw:
        for t in rec.get("tags", []):
            tag_usage[t]["galleries"] += 1
        studio = rec.get("studio")
        if studio:
            studio_usage[studio]["galleries"] += 1

    return performer_scenes, group_scenes, tag_usage, studio_usage


# ---------------------------------------------------------------------------
# phase 3: writers
# ---------------------------------------------------------------------------


def scene_line(s: dict) -> str:
    extra = ", ".join(x for x in (s.get("date"), s.get("studio")) if x)
    link = md_link(s["title"], f"/scenes/{s['slug']}.md")
    return f"{link} — {extra}" if extra else link


def write_performers(
    slugged: list[tuple[str, dict]], out_dir: Path, tags_idx: NameIndex, performer_scenes: dict[str, list[dict]]
) -> None:
    reset_dir(out_dir)
    for slug, rec in slugged:
        name = rec.get("name", "")
        disamb = rec.get("disambiguation", "")
        title = f"{name} ({disamb})" if disamb else name
        tags = rec.get("tags", [])
        scenes = performer_scenes.get(name, [])

        fm = {
            "type": "Performer",
            "title": title,
            "tags": tags,
            "gender": rec.get("gender"),
            "country": rec.get("country"),
            "favorite": rec.get("favorite") or None,
            "rating100": rec.get("rating") or None,
            "scene_count": len(scenes) or None,
            "status": "stable",
            "generated": {"by": GENERATOR_ID, "at": now_iso()},
        }

        body = f"# {title}\n\n"
        if rec.get("details"):
            body += rec["details"].strip() + "\n\n"

        body += table_section(
            "Atrybuty",
            [
                ("Płeć", rec.get("gender")),
                ("Data urodzenia", rec.get("birthdate")),
                ("Data śmierci", rec.get("death_date")),
                ("Kraj", rec.get("country")),
                ("Narodowość/etniczność", rec.get("ethnicity")),
                ("Kolor oczu", rec.get("eye_color")),
                ("Kolor włosów", rec.get("hair_color")),
                ("Wzrost (cm)", rec.get("height")),
                ("Waga (kg)", rec.get("weight")),
                ("Wymiary", rec.get("measurements")),
                ("Kariera od", rec.get("career_start")),
                ("Kariera do", rec.get("career_end")),
                ("Ulubiony", rec.get("favorite")),
                ("Ocena (1-100)", rec.get("rating")),
            ],
        )

        if rec.get("aliases"):
            body += links_section("Aliasy", rec["aliases"])

        if tags:
            body += links_section("Tagi", [tags_idx.link(t) for t in tags])

        if scenes:
            body += links_section(f"Sceny ({len(scenes)})", [scene_line(s) for s in scenes])

        if rec.get("urls"):
            body += links_section("Linki", rec["urls"])

        write_concept(out_dir / f"{slug}.md", fm, body)


def write_tags(slugged: list[tuple[str, dict]], out_dir: Path, tag_usage: dict[str, dict[str, int]]) -> None:
    reset_dir(out_dir)

    children_of: dict[str, list[str]] = defaultdict(list)
    for _, rec in slugged:
        for parent in rec.get("parents", []):
            children_of[parent].append(rec.get("name", ""))

    index = NameIndex("tags")
    for slug, rec in slugged:
        index.add(rec.get("name", ""), slug)

    for slug, rec in slugged:
        name = rec.get("name", "")
        usage = tag_usage.get(name, {})
        scene_count = usage.get("scenes", 0)

        fm = {
            "type": "Tag",
            "title": name,
            "description": rec.get("description"),
            "favorite": rec.get("favorite") or None,
            "scene_count": scene_count or None,
            "status": "stable",
            "generated": {"by": GENERATOR_ID, "at": now_iso()},
        }

        body = f"# {name}\n\n"
        if rec.get("description"):
            body += rec["description"].strip() + "\n\n"

        if rec.get("aliases"):
            body += links_section("Aliasy", rec["aliases"])

        if rec.get("parents"):
            body += links_section("Tagi nadrzędne", [index.link(p) for p in rec["parents"]])

        children = children_of.get(name, [])
        if children:
            body += links_section("Tagi podrzędne", [index.link(c) for c in children])

        if usage:
            usage_rows = [
                ("Sceny", usage.get("scenes", 0)),
                ("Wykonawcy", usage.get("performers", 0)),
                ("Studia", usage.get("studios", 0)),
                ("Grupy/filmy", usage.get("groups", 0)),
                ("Galerie", usage.get("galleries", 0)),
            ]
            body += table_section("Wykorzystanie", usage_rows)
            body += (
                "_Aby zobaczyć listę scen z tym tagiem, przeszukaj treść plików w "
                f"`scenes/*.md` pod kątem `/tags/{slug}.md`._\n\n"
            )

        write_concept(out_dir / f"{slug}.md", fm, body)


def write_studios(
    slugged: list[tuple[str, dict]],
    out_dir: Path,
    tags_idx: NameIndex,
    studio_usage: dict[str, dict[str, int]],
) -> None:
    reset_dir(out_dir)

    children_of: dict[str, list[str]] = defaultdict(list)
    for _, rec in slugged:
        parent = rec.get("parent_studio")
        if parent:
            children_of[parent].append(rec.get("name", ""))

    index = NameIndex("studios")
    for slug, rec in slugged:
        index.add(rec.get("name", ""), slug)

    for slug, rec in slugged:
        name = rec.get("name", "")
        tags = rec.get("tags", [])
        usage = studio_usage.get(name, {})
        scene_count = usage.get("scenes", 0)

        fm = {
            "type": "Studio",
            "title": name,
            "tags": tags,
            "favorite": rec.get("favorite") or None,
            "rating100": rec.get("rating") or None,
            "scene_count": scene_count or None,
            "status": "stable",
            "generated": {"by": GENERATOR_ID, "at": now_iso()},
        }

        body = f"# {name}\n\n"
        if rec.get("details"):
            body += rec["details"].strip() + "\n\n"

        if rec.get("parent_studio"):
            body += links_section("Studio nadrzędne", [index.link(rec["parent_studio"])])

        children = children_of.get(name, [])
        if children:
            body += links_section("Studia podrzędne", [index.link(c) for c in children])

        if rec.get("aliases"):
            body += links_section("Aliasy", rec["aliases"])

        if tags:
            body += links_section("Tagi", [tags_idx.link(t) for t in tags])

        if usage:
            usage_rows = [
                ("Sceny", usage.get("scenes", 0)),
                ("Grupy/filmy", usage.get("groups", 0)),
                ("Galerie", usage.get("galleries", 0)),
            ]
            body += table_section("Wykorzystanie", usage_rows)
            body += (
                "_Aby zobaczyć listę scen tego studia, przeszukaj treść plików w "
                f"`scenes/*.md` pod kątem `/studios/{slug}.md`._\n\n"
            )

        if rec.get("urls"):
            body += links_section("Linki", rec["urls"])

        write_concept(out_dir / f"{slug}.md", fm, body)


def write_groups(
    slugged: list[tuple[str, dict]],
    out_dir: Path,
    tags_idx: NameIndex,
    studios_idx: NameIndex,
    group_scenes: dict[str, list[dict]],
) -> None:
    reset_dir(out_dir)
    for slug, rec in slugged:
        name = rec.get("name", "")
        tags = rec.get("tags", [])
        scenes = group_scenes.get(name, [])

        fm = {
            "type": "Group",
            "title": name,
            "tags": tags,
            "date": rec.get("date"),
            "scene_count": len(scenes) or None,
            "status": "stable",
            "generated": {"by": GENERATOR_ID, "at": now_iso()},
        }

        body = f"# {name}\n\n"
        if rec.get("synopsis"):
            body += rec["synopsis"].strip() + "\n\n"

        body += table_section(
            "Atrybuty",
            [
                ("Data", rec.get("date")),
                ("Reżyser", rec.get("director")),
                ("Czas trwania (s)", rec.get("duration")),
                ("Ocena (1-100)", rec.get("rating")),
            ],
        )

        if rec.get("studio"):
            body += links_section("Studio", [studios_idx.link(rec["studio"])])

        if tags:
            body += links_section("Tagi", [tags_idx.link(t) for t in tags])

        if scenes:
            lines = []
            for s in scenes:
                line = md_link(s["title"], f"/scenes/{s['slug']}.md")
                if s.get("scene_index"):
                    line += f" (pozycja {s['scene_index']})"
                lines.append(line)
            body += links_section(f"Sceny ({len(scenes)})", lines)

        write_concept(out_dir / f"{slug}.md", fm, body)


def write_galleries(
    slugged: list[tuple[str, dict]],
    out_dir: Path,
    tags_idx: NameIndex,
    studios_idx: NameIndex,
    performers_idx: NameIndex,
) -> None:
    reset_dir(out_dir)
    for slug, rec in slugged:
        title = rec.get("title") or rec.get("folder_path") or slug
        tags = rec.get("tags", [])
        performers = rec.get("performers", [])

        fm = {
            "type": "Gallery",
            "title": title,
            "tags": tags,
            "resource": rec.get("folder_path"),
            "date": rec.get("date"),
            "status": "stable",
            "generated": {"by": GENERATOR_ID, "at": now_iso()},
        }

        body = f"# {title}\n\n"
        if rec.get("details"):
            body += rec["details"].strip() + "\n\n"

        body += table_section(
            "Atrybuty",
            [
                ("Data", rec.get("date")),
                ("Fotograf", rec.get("photographer")),
                ("Folder", rec.get("folder_path")),
                ("Ocena (1-100)", rec.get("rating")),
            ],
        )

        if rec.get("studio"):
            body += links_section("Studio", [studios_idx.link(rec["studio"])])

        if performers:
            body += links_section("Wykonawcy", [performers_idx.link(p) for p in performers])

        if tags:
            body += links_section("Tagi", [tags_idx.link(t) for t in tags])

        write_concept(out_dir / f"{slug}.md", fm, body)


def write_scenes(
    slugged: list[tuple[str, dict]],
    out_dir: Path,
    performers_idx: NameIndex,
    tags_idx: NameIndex,
    studios_idx: NameIndex,
    groups_idx: NameIndex,
) -> None:
    reset_dir(out_dir)
    total = len(slugged)
    for n, (slug, rec) in enumerate(slugged, start=1):
        title = rec.get("title") or f"Scena bez tytułu ({slug})"
        tags = rec.get("tags", [])
        performers = rec.get("performers", [])
        files = rec.get("files", [])

        fm = {
            "type": "Scene",
            "title": title,
            "tags": tags,
            "resource": files[0] if files else None,
            "date": rec.get("date"),
            "studio": rec.get("studio"),
            "status": "stable",
            "generated": {"by": GENERATOR_ID, "at": now_iso()},
        }

        body = f"# {title}\n\n"
        if rec.get("details"):
            body += rec["details"].strip() + "\n\n"

        body += table_section(
            "Atrybuty",
            [
                ("Data", rec.get("date")),
                ("Kod", rec.get("code")),
                ("Reżyser", rec.get("director")),
                ("Ocena (1-100)", rec.get("rating")),
                ("Zorganizowana", rec.get("organized")),
                ("Interaktywna", rec.get("interactive")),
            ],
        )

        if rec.get("studio"):
            body += links_section("Studio", [studios_idx.link(rec["studio"])])

        if performers:
            body += links_section("Wykonawcy", [performers_idx.link(p) for p in performers])

        if tags:
            body += links_section("Tagi", [tags_idx.link(t) for t in tags])

        groups = rec.get("movies", [])
        if groups:
            group_links = [
                f"{groups_idx.link(g.get('movieName', ''))} (pozycja {g.get('scene_index')})"
                if g.get("scene_index")
                else groups_idx.link(g.get("movieName", ""))
                for g in groups
            ]
            body += links_section("Grupy/filmy", group_links)

        if files:
            body += links_section("Pliki", [f"`{f}`" for f in files])

        markers = rec.get("markers", [])
        if markers:
            marker_lines = []
            for m in markers:
                t = m.get("title", "")
                s = m.get("seconds", "")
                mtags = ", ".join(m.get("tags", []))
                marker_lines.append(f"[{s}s] {t}" + (f" — {mtags}" if mtags else ""))
            body += links_section("Znaczniki (markers)", marker_lines)

        write_concept(out_dir / f"{slug}.md", fm, body)

        if n % 5000 == 0:
            print(f"  ... {n}/{total} scen zapisanych")


# ---------------------------------------------------------------------------
# bundle root
# ---------------------------------------------------------------------------


def write_root(out_dir: Path, counts: dict[str, int]) -> None:
    fm = {
        "okf_version": "0.2",
        "type": "Bundle",
        "title": "Baza wiedzy Stash",
        "description": "Metadane wyeksportowane z lokalnej instalacji Stash (aktorzy, sceny, tagi, studia, grupy, galerie).",
        "generated": {"by": GENERATOR_ID, "at": now_iso()},
    }

    body = "# Baza wiedzy Stash\n\n"
    body += (
        "Baza wiedzy w formacie [Open Knowledge Format (OKF) v0.2]"
        "(https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md), "
        "wygenerowana z natywnego eksportu JSON aplikacji Stash "
        "(`scripts/stash_export_to_okf.py`).\n\n"
    )
    body += "## Sekcje\n\n"
    body += f"* [Performers](performers/) - {counts['performers']} wykonawców\n"
    body += f"* [Scenes](scenes/) - {counts['scenes']} scen/klipów\n"
    body += f"* [Tags](tags/) - {counts['tags']} tagów\n"
    body += f"* [Studios](studios/) - {counts['studios']} studiów\n"
    body += f"* [Groups](groups/) - {counts['groups']} grup/filmów\n"
    body += f"* [Galleries](galleries/) - {counts['galleries']} galerii\n\n"
    body += "## Jak przeszukiwać\n\n"
    body += (
        "Każdy plik to jeden koncept (`type: Performer|Scene|Tag|Studio|Group|Gallery`) "
        "z YAML front matterem i linkami markdown do powiązanych konceptów "
        "(np. scena linkuje do swoich wykonawców, tagów i studia; wykonawca i grupa "
        "linkują z powrotem do swoich scen; tag i studio pokazują liczniki wykorzystania). "
        "Do wyszukiwania po nazwie/tytule użyj wyszukiwania plików po nazwie (Glob), "
        "do wyszukiwania po treści/atrybutach (np. wszystkie sceny danego studia lub taga) "
        "użyj przeszukiwania treści (Grep) w odpowiednim podkatalogu, np. `scenes/*.md`.\n\n"
    )
    body += (
        "Dane są regenerowane ze świeżego eksportu Stash — nie edytuj plików ręcznie, "
        "zmiany zostaną nadpisane przy kolejnym uruchomieniu skryptu.\n"
    )

    write_concept(out_dir / "index.md", fm, body)

    write_log(out_dir, counts)


def write_log(out_dir: Path, counts: dict[str, int]) -> None:
    """Prepend a dated entry to log.md, preserving history from earlier runs."""
    header = "# Log aktualizacji bazy wiedzy\n"
    log_path = out_dir / "log.md"
    existing = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    body = existing[len(header):].lstrip("\n") if existing.startswith(header) else existing.strip()

    label = "Initialization" if not body else "Aktualizacja"
    entry = (
        f"* **{label}**: Wygenerowano bazę OKF z eksportu Stash "
        f"({counts['performers']} performerów, {counts['scenes']} scen, {counts['tags']} tagów, "
        f"{counts['studios']} studiów, {counts['groups']} grup, {counts['galleries']} galerii).\n"
    )

    date_heading = f"## {datetime.now(timezone.utc):%Y-%m-%d}\n"
    if body.startswith(date_heading):
        new_body = date_heading + entry + body[len(date_heading):]
    else:
        new_body = date_heading + entry + (f"\n{body}" if body else "")

    log_path.write_text(header + "\n" + new_body, encoding="utf-8")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--export-dir", required=True, help="Ścieżka do folderu eksportu Stash (config.yml -> metadata)")
    parser.add_argument("--out", default=".", help="Katalog docelowy bundla OKF (domyślnie bieżący katalog)")
    args = parser.parse_args()

    export_dir = Path(args.export_dir)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Wczytywanie eksportu...")
    performers_raw = load_json_dir(export_dir / "performers")
    tags_raw = load_json_dir(export_dir / "tags")
    studios_raw = load_json_dir(export_dir / "studios")
    groups_raw = load_json_dir(export_dir / "movies")
    galleries_raw = load_json_dir(export_dir / "galleries")
    scenes_raw = load_json_dir(export_dir / "scenes")

    print(
        f"  performers={len(performers_raw)} scenes={len(scenes_raw)} tags={len(tags_raw)} "
        f"studios={len(studios_raw)} groups={len(groups_raw)} galleries={len(galleries_raw)}"
    )

    print("Przypisywanie identyfikatorów (slugów)...")
    tags_idx, tags_slugged = assign_tags(tags_raw)
    studios_idx, studios_slugged = assign_studios(studios_raw)
    performers_idx, performers_slugged = assign_performers(performers_raw)
    groups_idx, groups_slugged = assign_groups(groups_raw)
    galleries_idx, galleries_slugged = assign_galleries(galleries_raw)
    scenes_idx, scenes_slugged = assign_scenes(scenes_raw)

    print("Budowanie indeksów odwrotnych (performer/grupa -> sceny, tag/studio -> liczniki)...")
    performer_scenes, group_scenes, tag_usage, studio_usage = build_reverse_indices(
        scenes_slugged, groups_raw, galleries_raw, performers_raw, studios_raw
    )

    print("Zapisywanie tagów...")
    write_tags(tags_slugged, out_dir / "tags", tag_usage)

    print("Zapisywanie studiów...")
    write_studios(studios_slugged, out_dir / "studios", tags_idx, studio_usage)

    print("Zapisywanie wykonawców...")
    write_performers(performers_slugged, out_dir / "performers", tags_idx, performer_scenes)

    print("Zapisywanie grup/filmów...")
    write_groups(groups_slugged, out_dir / "groups", tags_idx, studios_idx, group_scenes)

    print("Zapisywanie galerii...")
    write_galleries(galleries_slugged, out_dir / "galleries", tags_idx, studios_idx, performers_idx)

    print("Zapisywanie scen...")
    write_scenes(scenes_slugged, out_dir / "scenes", performers_idx, tags_idx, studios_idx, groups_idx)

    print("Zapisywanie index.md / log.md...")
    write_root(
        out_dir,
        {
            "performers": len(performers_raw),
            "scenes": len(scenes_raw),
            "tags": len(tags_raw),
            "studios": len(studios_raw),
            "groups": len(groups_raw),
            "galleries": len(galleries_raw),
        },
    )

    print("Gotowe.")


if __name__ == "__main__":
    main()

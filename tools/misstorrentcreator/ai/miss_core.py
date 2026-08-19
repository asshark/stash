#!/usr/bin/env python3
"""
Core CLI for the /misstudio and /misstar Claude Code skills.

This is a NEW, independent implementation — it does not modify
`torrent_stash_missing.py`. It only imports proven low-level bencode /
qBittorrent primitives from it (see the import block below); everything
else (Stash GraphQL client, performer resolution, studio-vs-performer
scope matching, CLI) is written fresh here. Filename -> performer/date/title
extraction is NOT done here — that step is delegated by the Claude skill to
a "fable" subagent; this script only consumes the resulting JSON.

Subcommands (all output JSON on stdout; errors go to stderr with exit code 1):

  list-studios    [--query TEXT] [--limit N]
      -> [{"id": "...", "name": "..."}, ...]

  list-performers [--query TEXT] [--limit N]
      -> [{"id": "...", "name": "...", "alias_list": [...]}, ...]

  list-files <torrent_path>
      -> {
           "torrent": "<path>",
           "is_v2": bool,
           "is_bep47_padded": bool,
           "files": [
             {"index": int, "path": "a/b/c.mp4", "name": "c.mp4",
              "directory": "a/b", "length": int},
             ...   # video files only (VIDEO_EXTENSIONS); .pad entries skipped
           ],
           "skipped_non_video": [{"index": int, "path": "..."}]  # e.g. .zip/.jpg
         }

  match --scope {studio,performer} --scope-id ID --parsed <path-to-json>
      <path-to-json> is a list produced by the skill (via the fable subagent):
        [{"index": int, "performers": ["Name", ...], "date": "YYYY-MM-DD"|null,
          "title": "..."|null, "studio_hint": "..."|null}, ...]
      studio_hint, when present, is resolved against Stash studios (exact
      name/alias match, case-insensitive) and used to prefer scenes tagged
      with that studio among the performer+date candidates; if none of the
      candidates carry it, matching falls back to the unfiltered set (Stash
      scenes aren't always studio-tagged) and the mismatch is noted in
      "detail" instead of silently discarded.
      -> {
           "scope": "studio"|"performer",
           "scope_id": "...",
           "scope_name": "...",
           "results": [
             {"index": int, "path": "...", "status": "present"|"missing"|"unmatched"|"skipped",
              "detail": "...", "matched_performer_names": [...], "matched_scene": {...}|null},
             ...
           ]
         }

  build-torrent <torrent_path> --missing <path-to-json-index-list> --out <path> [--force]
      Writes a v1 subset torrent (original piece hashes, missing files kept,
      everything else replaced by BEP 47 .pad entries). Only works cleanly
      when the source torrent is already BEP 47 padded; use --force to try
      anyway (boundary pieces may fail hash-check in the client).
      -> {"ok": true, "output": "<path>"} or {"ok": false, "reason": "..."}

  qbittorrent-push <torrent_path> --missing <path-to-json-index-list>
      [--qb-url URL] [--qb-user U] [--qb-pass P] [--qb-save-path P]
      [--qb-category C] [--qb-start]
      Adds the FULL torrent to qBittorrent (paused) and sets file priority
      0 (skip) on everything except the missing indices, priority 1 on the
      missing ones.
      -> {"ok": true, "info_hash": "...", "missing_count": N, "kept_paused": bool}
         or {"ok": false, "reason": "..."}

Environment:
  STASH_URL        Stash base URL or GraphQL endpoint (default http://localhost:9999)
  STASH_API_KEY    Optional ApiKey header value
  QB_USER / QB_PASS  qBittorrent Web UI credentials (only if not already authenticated)

Known limitation (documented, not silently skipped): unlike
torrent_stash_missing.py's --size-check mode, this tool does not do greedy
file-size-based dedup of multi-part re-encodes of the same scene. Matching
is by (performer-id-set subset) + (date compatibility) only. See
tools/misstorrentcreator/ai/CLAUDE.md.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# --- reuse of proven low-level helpers from torrent_stash_missing.py -------
# Read-only import. torrent_stash_missing.py is NOT modified by this project.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from torrent_stash_missing import (  # noqa: E402
    QBittorrentClient,
    QBittorrentError,
    bencode_decode,  # noqa: F401  (re-exported for callers that need raw access)
    bencode_encode,  # noqa: F401
    create_v1_subset_torrent_with_padding,
    info_hashes,
    is_bep47_padded,
    iter_torrent_files,
    load_torrent,
    torrent_has_v1_data,
    torrent_is_v2,
)

for _stream_name in ("stdout", "stderr"):
    _stream = getattr(sys, _stream_name, None)
    if _stream is not None and hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass


VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".wmv", ".mov", ".m4v", ".webm", ".mpg", ".mpeg"}


def b2s(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def normalize_name(name: str) -> str:
    cleaned = re.sub(r"\s+", " ", name.strip().lower())
    return cleaned.strip("._-")


def fail(reason: str) -> None:
    print(json.dumps({"ok": False, "reason": reason}, ensure_ascii=False), file=sys.stdout)
    sys.exit(1)


# --- Stash GraphQL client (new; independent of torrent_stash_missing.py) ---


class StashClient:
    def __init__(self, url: str | None = None, api_key: str | None = None) -> None:
        self.url = (url or os.environ.get("STASH_URL") or "http://localhost:9999").rstrip("/")
        if not self.url.endswith("/graphql"):
            self.url = self.url + "/graphql"
        self.api_key = api_key or os.environ.get("STASH_API_KEY")

    def query(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"query": query}
        if variables:
            body["variables"] = variables
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["ApiKey"] = self.api_key
        req = urllib.request.Request(
            self.url, data=json.dumps(body).encode("utf-8"), headers=headers
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Stash HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Nie mogę połączyć się ze Stash ({self.url}): {exc}") from exc
        if payload.get("errors"):
            raise RuntimeError(json.dumps(payload["errors"], indent=2))
        return payload["data"]

    def find_studios(self, search: str = "", limit: int = 25) -> list[dict[str, Any]]:
        data = self.query(
            """
            query FindStudios($filter: FindFilterType) {
              findStudios(filter: $filter) { studios { id name aliases } }
            }
            """,
            {"filter": {"q": search, "per_page": limit, "sort": "name", "direction": "ASC"}},
        )
        return data["findStudios"]["studios"]

    def find_performers(self, search: str = "", limit: int = 25) -> list[dict[str, Any]]:
        data = self.query(
            """
            query FindPerformers($filter: FindFilterType) {
              findPerformers(filter: $filter) { performers { id name alias_list } }
            }
            """,
            {"filter": {"q": search, "per_page": limit, "sort": "name", "direction": "ASC"}},
        )
        return data["findPerformers"]["performers"]

    def _load_scenes(self, scene_filter: dict[str, Any]) -> list["SceneInfo"]:
        result: list[SceneInfo] = []
        page = 1
        per_page = 500
        while True:
            data = self.query(
                """
                query ScopeScenes($filter: FindFilterType, $scene_filter: SceneFilterType) {
                  findScenes(filter: $filter, scene_filter: $scene_filter) {
                    scenes {
                      id
                      title
                      date
                      studio { id name }
                      performers { id name alias_list }
                      files { size }
                    }
                  }
                }
                """,
                {
                    "filter": {"page": page, "per_page": per_page, "sort": "id", "direction": "ASC"},
                    "scene_filter": scene_filter,
                },
            )
            scenes = data["findScenes"]["scenes"]
            if not scenes:
                break
            for scene in scenes:
                performers = scene.get("performers") or []
                ids = frozenset(str(p["id"]) for p in performers)
                names = tuple(p.get("name") or "" for p in performers)
                sizes: list[int] = []
                for f in scene.get("files") or []:
                    try:
                        sizes.append(int(f.get("size") or 0))
                    except (TypeError, ValueError):
                        continue
                date_value = scene.get("date") or None
                if date_value and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_value):
                    date_value = None
                studio = scene.get("studio") or {}
                result.append(
                    SceneInfo(
                        scene_id=str(scene["id"]),
                        title=scene.get("title") or "",
                        date=date_value,
                        studio_id=str(studio["id"]) if studio.get("id") is not None else None,
                        studio_name=studio.get("name"),
                        performer_ids=ids,
                        performer_names=names,
                        file_sizes=sizes,
                    )
                )
            if len(scenes) < per_page:
                break
            page += 1
        return result

    def load_studio_scenes(self, studio_id: str) -> list["SceneInfo"]:
        return self._load_scenes(
            {"studios": {"value": [studio_id], "modifier": "INCLUDES", "depth": 0}}
        )

    def load_performer_scenes(self, performer_id: str) -> list["SceneInfo"]:
        return self._load_scenes(
            {"performers": {"value": [performer_id], "modifier": "INCLUDES"}}
        )


@dataclass
class SceneInfo:
    scene_id: str
    title: str
    date: str | None
    studio_id: str | None
    studio_name: str | None
    performer_ids: frozenset[str]
    performer_names: tuple[str, ...]
    file_sizes: list[int]


def resolve_performer_names(
    stash: StashClient, names: list[str]
) -> dict[str, dict[str, Any] | None]:
    """Resolve free-text names to Stash performers by exact name/alias match
    (case/whitespace-insensitive). Returns normalize_name(name) -> performer|None.
    """
    cache: dict[str, dict[str, Any] | None] = {}
    for name in names:
        key = normalize_name(name)
        if not key or key in cache:
            continue
        candidates = stash.find_performers(name, limit=10)
        match = None
        for p in candidates:
            aliases = p.get("alias_list") or []
            if isinstance(aliases, str):
                aliases = [a.strip() for a in aliases.split(",") if a.strip()]
            names_to_check = [p.get("name") or ""] + list(aliases)
            if any(normalize_name(n) == key for n in names_to_check):
                match = p
                break
        cache[key] = match
    return cache


def resolve_studio_names(
    stash: StashClient, names: list[str]
) -> dict[str, dict[str, Any] | None]:
    """Resolve free-text studio names/hints to Stash studios by exact name/alias
    match (case/whitespace-insensitive). Returns normalize_name(name) -> studio|None.
    """
    cache: dict[str, dict[str, Any] | None] = {}
    for name in names:
        key = normalize_name(name)
        if not key or key in cache:
            continue
        candidates = stash.find_studios(name, limit=10)
        match = None
        for s in candidates:
            names_to_check = [s.get("name") or ""] + list(s.get("aliases") or [])
            if any(normalize_name(n) == key for n in names_to_check):
                match = s
                break
        cache[key] = match
    return cache


# --- list-files --------------------------------------------------------


def cmd_list_files(args: argparse.Namespace) -> None:
    torrent_path = Path(args.torrent)
    if not torrent_path.is_file():
        fail(f"Nie znaleziono pliku torrent: {torrent_path}")
    torrent, info = load_torrent(torrent_path)
    files: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for index, (path_parts, length) in enumerate(iter_torrent_files(info)):
        if any(part.startswith(".pad") for part in path_parts):
            continue
        path = "/".join(path_parts)
        name = path_parts[-1]
        directory = "/".join(path_parts[:-1])
        ext = Path(name).suffix.lower()
        if ext not in VIDEO_EXTENSIONS:
            skipped.append({"index": index, "path": path})
            continue
        files.append(
            {"index": index, "path": path, "name": name, "directory": directory, "length": length}
        )
    print(
        json.dumps(
            {
                "torrent": str(torrent_path),
                "is_v2": torrent_is_v2(info),
                "is_bep47_padded": is_bep47_padded(info),
                "files": files,
                "skipped_non_video": skipped,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


# --- list-studios / list-performers -------------------------------------


def cmd_list_studios(args: argparse.Namespace) -> None:
    stash = StashClient(args.stash_url, args.api_key)
    try:
        studios = stash.find_studios(args.query or "", limit=args.limit)
    except RuntimeError as exc:
        fail(str(exc))
        return
    print(json.dumps(studios, ensure_ascii=False, indent=2))


def cmd_list_performers(args: argparse.Namespace) -> None:
    stash = StashClient(args.stash_url, args.api_key)
    try:
        performers = stash.find_performers(args.query or "", limit=args.limit)
    except RuntimeError as exc:
        fail(str(exc))
        return
    print(json.dumps(performers, ensure_ascii=False, indent=2))


# --- match ---------------------------------------------------------------


def date_compatible(file_date: str | None, scene_date: str | None) -> bool:
    if not file_date or not scene_date:
        return True
    return file_date == scene_date


def normalize_title(text: str | None) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"[^a-z0-9]+", " ", text.lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def title_similar(file_title: str | None, scene_title: str | None) -> bool:
    a, b = normalize_title(file_title), normalize_title(scene_title)
    if not a or not b:
        return False
    return a == b or a in b or b in a


def cmd_match(args: argparse.Namespace) -> None:
    parsed_path = Path(args.parsed)
    if not parsed_path.is_file():
        fail(f"Nie znaleziono pliku z wynikami parsowania: {parsed_path}")
    parsed_entries: list[dict[str, Any]] = json.loads(parsed_path.read_text(encoding="utf-8"))

    stash = StashClient(args.stash_url, args.api_key)
    try:
        if args.scope == "studio":
            scope_data = stash.query(
                "query ($id: ID!) { findStudio(id: $id) { id name } }", {"id": args.scope_id}
            )
            scope_obj = scope_data.get("findStudio")
            if not scope_obj:
                fail(f"Nie znaleziono studia o id={args.scope_id}")
                return
            scope_scenes = stash.load_studio_scenes(args.scope_id)
            scope_performer_id: str | None = None
        else:
            scope_data = stash.query(
                "query ($id: ID!) { findPerformer(id: $id) { id name } }", {"id": args.scope_id}
            )
            scope_obj = scope_data.get("findPerformer")
            if not scope_obj:
                fail(f"Nie znaleziono aktora o id={args.scope_id}")
                return
            scope_scenes = stash.load_performer_scenes(args.scope_id)
            scope_performer_id = str(args.scope_id)
    except RuntimeError as exc:
        fail(str(exc))
        return

    all_names = sorted({n for e in parsed_entries for n in (e.get("performers") or [])})
    name_cache = resolve_performer_names(stash, all_names)

    all_studio_hints = sorted({e["studio_hint"] for e in parsed_entries if e.get("studio_hint")})
    studio_cache = resolve_studio_names(stash, all_studio_hints)

    results: list[dict[str, Any]] = []
    for entry in parsed_entries:
        index = entry["index"]
        names = entry.get("performers") or []
        file_date = entry.get("date")
        file_title = entry.get("title")
        studio_hint = entry.get("studio_hint")
        resolved_studio = studio_cache.get(normalize_name(studio_hint)) if studio_hint else None
        path = entry.get("path", "")

        if not names and scope_performer_id is None:
            results.append(
                {
                    "index": index,
                    "path": path,
                    "status": "skipped",
                    "detail": "Brak wykrytych aktorów w nazwie pliku",
                    "matched_performer_names": [],
                    "matched_scene": None,
                }
            )
            continue

        matched_ids: set[str] = set()
        matched_names: list[str] = []
        unmatched_names: list[str] = []
        for name in names:
            performer = name_cache.get(normalize_name(name))
            if performer:
                matched_ids.add(str(performer["id"]))
                matched_names.append(performer["name"])
            else:
                unmatched_names.append(name)

        if scope_performer_id is not None:
            matched_ids.add(scope_performer_id)
            if scope_obj["name"] not in matched_names:
                matched_names.append(scope_obj["name"])

        if unmatched_names:
            tried = ", ".join(names)
            results.append(
                {
                    "index": index,
                    "path": path,
                    "status": "unmatched",
                    "detail": f"Nieznani w Stash: {', '.join(unmatched_names)} (z pliku: {tried})",
                    "matched_performer_names": matched_names,
                    "matched_scene": None,
                }
            )
            continue

        if not matched_ids:
            results.append(
                {
                    "index": index,
                    "path": path,
                    "status": "unmatched",
                    "detail": "Nie udało się dopasować żadnego aktora do Stash",
                    "matched_performer_names": [],
                    "matched_scene": None,
                }
            )
            continue

        candidates = [s for s in scope_scenes if matched_ids.issubset(s.performer_ids)]
        compatible = [s for s in candidates if date_compatible(file_date, s.date)]

        # Studio is a hard filter, same weight as date: known-and-different
        # disqualifies, unknown-on-either-side doesn't. Explicit user call
        # (found via Leo Ahsoka.torrent's BangBros/My Dirty Maid case): a
        # title match must NOT rescue a *known* studio mismatch into
        # "present" — if Stash has the title under a different studio, that
        # counts as not having *this* release, not as an already-owned dupe.
        # Only the narrowing benefit changes when studio_hint is unresolved
        # (no signal either way, same as a file with no date).
        pool = compatible
        studio_note = ""
        if resolved_studio and compatible:
            pool = [s for s in compatible if s.studio_id == str(resolved_studio["id"])]
            if not pool:
                found_studios = sorted({s.studio_name for s in compatible if s.studio_name})
                studio_note = (
                    f" [studio pliku '{resolved_studio['name']}' nie pasuje do żadnej "
                    "kandydatki (ma: "
                    f"{', '.join(found_studios) if found_studios else 'brak'}) — potraktowano "
                    "jako inne wydanie/brakującą scenę]"
                )

        # Pick a specific scene only when something actually disambiguates the
        # (already studio-filtered) pool: a single candidate, an exact date
        # hit, or a title match. With multiple candidates and none of those,
        # "pick pool[0]" is a coin flip, not a match — first live run
        # (Leo Ahsoka.torrent) showed this silently collapsing over a dozen
        # unrelated files onto the same single scene. Falling through to
        # "missing" (ambiguous) below is the safer failure mode: a false
        # "missing" costs one manual look, a false "present" silently drops
        # content the user doesn't actually have.
        best = None
        if len(pool) == 1:
            best = pool[0]
        elif pool:
            if file_date:
                best = next((s for s in pool if s.date == file_date), None)
            if best is None and file_title:
                best = next((s for s in pool if title_similar(file_title, s.title)), None)

        if best is not None:
            results.append(
                {
                    "index": index,
                    "path": path,
                    "status": "present",
                    "detail": f"Dopasowano scenę '{best.title or best.scene_id}'"
                    + (f" (studio: {best.studio_name})" if best.studio_name else "")
                    + (f", data={best.date}" if best.date else ""),
                    "matched_performer_names": matched_names,
                    "matched_scene": {
                        "scene_id": best.scene_id,
                        "title": best.title,
                        "date": best.date,
                        "studio_name": best.studio_name,
                    },
                }
            )
            continue

        if studio_note:
            detail = (
                f"{', '.join(matched_names)}: jest {len(compatible)} scen z tym zestawem aktorów, "
                f"ale żadna nie ma studia '{resolved_studio['name']}' z pliku"
            )
        elif len(pool) > 1:
            detail = (
                f"{', '.join(matched_names)}: jest {len(pool)} scen z tym zestawem aktorów "
                "bez rozstrzygającej daty/tytułu — za mało sygnału, żeby wskazać jedną"
            )
        elif candidates:
            dates = sorted({s.date for s in candidates if s.date})
            if file_date and dates:
                detail = (
                    f"{', '.join(matched_names)}: są sceny z tym zestawem aktorów, "
                    f"ale nie na datę {file_date} (dostępne: {', '.join(dates[:3])}"
                    + (", ..." if len(dates) > 3 else "") + ")"
                )
            else:
                detail = f"{', '.join(matched_names)}: są sceny z tym zestawem aktorów, ale brak daty do porównania"
        else:
            detail = f"Brak sceny w tym zakresie dla: {', '.join(matched_names)}"

        if studio_hint:
            studio_display = (
                resolved_studio["name"] if resolved_studio else f"'{studio_hint}' (nieznane w Stash)"
            )
            detail += f" [studio z pliku: {studio_display}]"

        results.append(
            {
                "index": index,
                "path": path,
                "status": "missing",
                "detail": detail,
                "matched_performer_names": matched_names,
                "matched_scene": None,
            }
        )

    # A single Stash scene can legitimately back only one file. If a studio
    # match narrowed several *different* files down to the same scene (e.g.
    # a performer has just one scene at a given studio, but the torrent has
    # several differently-titled files for that studio), only the len==1
    # check above ran per file — it can't see that another file already
    # claimed that scene. Found live on Leo Ahsoka.torrent: both
    # "Backdoor Delight.mp4" and "Let's Skip Dinner.mp4" narrowed to the
    # single "Backdoor Delight" Asshole Fever scene, but only one of them is
    # actually it. Resolve with title: keep the one whose title matches, or
    # if none/more than one does, keep none — downgrade the rest (or all) to
    # missing rather than let duplicate "present" verdicts hide real gaps.
    title_by_index = {e["index"]: e.get("title") for e in parsed_entries}
    by_scene: dict[str, list[int]] = {}
    for pos, r in enumerate(results):
        if r["status"] == "present":
            by_scene.setdefault(r["matched_scene"]["scene_id"], []).append(pos)
    for scene_id, positions in by_scene.items():
        if len(positions) <= 1:
            continue
        scene_title = results[positions[0]]["matched_scene"]["title"]
        title_hits = [
            pos for pos in positions
            if title_similar(title_by_index.get(results[pos]["index"]), scene_title)
        ]
        keep = title_hits[0] if len(title_hits) == 1 else None
        for pos in positions:
            if pos == keep:
                continue
            old = results[pos]
            results[pos] = {
                "index": old["index"],
                "path": old["path"],
                "status": "missing",
                "detail": (
                    f"{', '.join(old['matched_performer_names'])}: kilka różnych plików w torrencie "
                    f"zawęziło się (po studiu) do tej samej sceny '{scene_title}' w Stash, ale tytuł "
                    "tego pliku do niej nie pasuje — prawdopodobnie inna, jeszcze nieposiadana scena"
                ),
                "matched_performer_names": old["matched_performer_names"],
                "matched_scene": None,
            }

    print(
        json.dumps(
            {
                "scope": args.scope,
                "scope_id": str(args.scope_id),
                "scope_name": scope_obj["name"],
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


# --- build-torrent ---------------------------------------------------------


def cmd_build_torrent(args: argparse.Namespace) -> None:
    torrent_path = Path(args.torrent)
    if not torrent_path.is_file():
        fail(f"Nie znaleziono pliku torrent: {torrent_path}")
    missing_path = Path(args.missing)
    if not missing_path.is_file():
        fail(f"Nie znaleziono pliku z listą indeksów: {missing_path}")
    indices = set(json.loads(missing_path.read_text(encoding="utf-8")))
    if not indices:
        fail("Lista brakujących indeksów jest pusta.")

    torrent, info = load_torrent(torrent_path)
    out_path = Path(args.out)

    if not is_bep47_padded(info) and not args.force:
        print(
            json.dumps(
                {
                    "ok": False,
                    "reason": (
                        "Torrent v1 bez BEP 47 padding — subset torrent może nie przejść "
                        "weryfikacji hashy na granicach plików. Użyj --force żeby spróbować "
                        "mimo to, albo poleć qbittorrent-push."
                    ),
                },
                ensure_ascii=False,
            )
        )
        sys.exit(1)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    create_v1_subset_torrent_with_padding(torrent, info, indices, out_path)
    print(
        json.dumps(
            {
                "ok": True,
                "output": str(out_path),
                "warning": None if is_bep47_padded(info) else "torrent bez natywnego BEP 47 padding — zweryfikuj w kliencie",
            },
            ensure_ascii=False,
        )
    )


# --- qbittorrent-push --------------------------------------------------


def cmd_qbittorrent_push(args: argparse.Namespace) -> None:
    torrent_path = Path(args.torrent)
    if not torrent_path.is_file():
        fail(f"Nie znaleziono pliku torrent: {torrent_path}")
    missing_path = Path(args.missing)
    if not missing_path.is_file():
        fail(f"Nie znaleziono pliku z listą indeksów: {missing_path}")
    missing_indices = set(json.loads(missing_path.read_text(encoding="utf-8")))

    torrent, info = load_torrent(torrent_path)
    all_files = iter_torrent_files(info)
    v1_hash, v2_hash = info_hashes(info)
    primary_hash = v1_hash or v2_hash
    if not primary_hash:
        fail("Nie udało się wyliczyć info-hash z torrenta.")
        return

    client = QBittorrentClient(args.qb_url)
    if not client.reachable():
        fail(f"Nie mogę połączyć się z qBittorrent pod {args.qb_url}. Sprawdź, czy Web UI jest włączone.")
        return

    try:
        client.torrent_info(primary_hash)
        authenticated = True
    except QBittorrentError as exc:
        authenticated = "403" not in str(exc)
        if not authenticated:
            pass
        else:
            fail(f"qBittorrent: {exc}")
            return

    if not authenticated:
        qb_user = args.qb_user or os.environ.get("QB_USER") or "admin"
        qb_pass = args.qb_pass or os.environ.get("QB_PASS") or ""
        try:
            client.login(qb_user, qb_pass)
        except QBittorrentError as exc:
            fail(f"Logowanie do qBittorrent nieudane: {exc}")
            return

    try:
        existing = client.torrent_info(primary_hash)
    except QBittorrentError as exc:
        fail(f"qBittorrent torrent info: {exc}")
        return

    if not existing:
        try:
            client.add_torrent_file(
                torrent_path.read_bytes(),
                torrent_path.name,
                paused=True,
                save_path=args.qb_save_path,
                category=args.qb_category,
            )
        except QBittorrentError as exc:
            fail(f"Dodawanie torrenta nieudane: {exc}")
            return
        if not client.wait_for_torrent(primary_hash, timeout_seconds=20):
            if v2_hash and primary_hash != v2_hash and client.wait_for_torrent(v2_hash, timeout_seconds=5):
                primary_hash = v2_hash
            else:
                fail("qBittorrent nie zarejestrował torrenta w 25s. Sprawdź ręcznie w GUI.")
                return

    try:
        qb_files = client.torrent_files(primary_hash)
    except QBittorrentError as exc:
        fail(f"qBittorrent torrent files: {exc}")
        return

    qb_total = len(qb_files)
    our_total = len(all_files)
    if qb_total == our_total:
        keep = [i for i in range(qb_total) if i not in missing_indices]
        download = [i for i in range(qb_total) if i in missing_indices]
    else:
        path_to_index = {"/".join(parts): idx for idx, (parts, _len) in enumerate(all_files)}
        keep, download = [], []
        for qb_idx, qf in enumerate(qb_files):
            qb_path = qf.get("name", "").replace("\\", "/")
            original_idx = path_to_index.get(qb_path)
            if original_idx is None:
                continue
            (download if original_idx in missing_indices else keep).append(qb_idx)

    try:
        client.set_file_priorities(primary_hash, keep, 0)
        client.set_file_priorities(primary_hash, download, 1)
    except QBittorrentError as exc:
        fail(f"Ustawianie priorytetów nieudane: {exc}")
        return

    if args.qb_start:
        client.resume_torrent(primary_hash)

    print(
        json.dumps(
            {
                "ok": True,
                "info_hash": primary_hash,
                "missing_count": len(download),
                "kept_paused": not args.qb_start,
            },
            ensure_ascii=False,
        )
    )


# --- CLI -----------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stash-url", default=os.environ.get("STASH_URL", "http://localhost:9999"))
    parser.add_argument("--api-key", default=os.environ.get("STASH_API_KEY"))
    sub = parser.add_subparsers(dest="command", required=True)

    p_ls = sub.add_parser("list-studios")
    p_ls.add_argument("--query", default="")
    p_ls.add_argument("--limit", type=int, default=25)
    p_ls.set_defaults(func=cmd_list_studios)

    p_lp = sub.add_parser("list-performers")
    p_lp.add_argument("--query", default="")
    p_lp.add_argument("--limit", type=int, default=25)
    p_lp.set_defaults(func=cmd_list_performers)

    p_lf = sub.add_parser("list-files")
    p_lf.add_argument("torrent")
    p_lf.set_defaults(func=cmd_list_files)

    p_match = sub.add_parser("match")
    p_match.add_argument("--scope", choices=["studio", "performer"], required=True)
    p_match.add_argument("--scope-id", required=True)
    p_match.add_argument("--parsed", required=True, help="Path to JSON produced by the fable subagent")
    p_match.set_defaults(func=cmd_match)

    p_build = sub.add_parser("build-torrent")
    p_build.add_argument("torrent")
    p_build.add_argument("--missing", required=True, help="Path to JSON list of missing file indices")
    p_build.add_argument("--out", required=True)
    p_build.add_argument("--force", action="store_true")
    p_build.set_defaults(func=cmd_build_torrent)

    p_qb = sub.add_parser("qbittorrent-push")
    p_qb.add_argument("torrent")
    p_qb.add_argument("--missing", required=True)
    p_qb.add_argument("--qb-url", default=os.environ.get("QB_URL", "http://localhost:8080"))
    p_qb.add_argument("--qb-user", default=os.environ.get("QB_USER"))
    p_qb.add_argument("--qb-pass", default=os.environ.get("QB_PASS"))
    p_qb.add_argument("--qb-save-path", default=None)
    p_qb.add_argument("--qb-category", default=None)
    p_qb.add_argument("--qb-start", action="store_true")
    p_qb.set_defaults(func=cmd_qbittorrent_push)

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())

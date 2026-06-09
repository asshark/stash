#!/usr/bin/env python3
"""
Analyse a torrent against a Stash studio and find missing clips.

For each video file in the torrent, parse performer name(s) from the filename
and check whether the selected studio already has at least one scene with those
performers (matching by name or alias).

Usage:
  python torrent_stash_missing.py path/to/file.torrent
  python torrent_stash_missing.py path/to/file.torrent --studio-id 123
  python torrent_stash_missing.py path/to/file.torrent --studio-name "Wake Up N Fuck"

Environment:
  STASH_URL   GraphQL endpoint (default: http://localhost:9999/graphql)
  STASH_API_KEY  Optional ApiKey header value
"""

from __future__ import annotations

import argparse
import atexit
import getpass
import hashlib
import http.cookiejar
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

# Force UTF-8 on stdout/stderr so we can safely print Polish/Unicode characters
# in interactive prompts and log files (default Windows codepage is cp1250).
for _stream_name in ("stdout", "stderr"):
    _stream = getattr(sys, _stream_name, None)
    if _stream is not None and hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass


DEFAULT_OUTPUT_DIR = r"d:\Downloads\Torrents\Incoming\2download\torrent"
DEFAULT_LOG_DIR = r"d:\Downloads\Torrents\Incoming\2download\logs"
DEFAULT_CACHE_DIR = r"d:\Downloads\Torrents\Incoming\2download\cache"


VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".wmv", ".mov", ".m4v", ".webm", ".mpg", ".mpeg"}

QUALITY_RE = re.compile(
    r"\s*(?:2160p|1080p|720p|480p|4k|uhd|hd|sd)\s*\.?\s*$",
    re.IGNORECASE,
)
PART_SUFFIX_RE = re.compile(r"\s+\d+\s*$")
CODE_PREFIX_RE = re.compile(
    r"^([a-z]{2,10}\s*\d{2,4})[\s._-]+(.+)$",
    re.IGNORECASE,
)
RESOLUTION_IN_NAME_RE = re.compile(r"\s+\d{3,4}p\s*", re.IGNORECASE)
DATE_PREFIX_RE = re.compile(
    r"^("
    r"\d{4}[._-]\d{2}[._-]\d{2}"      # 2024-05-13 / 2024.05.13
    r"|\d{2}[._-]\d{2}[._-]\d{2,4}"   # 14.12.07 / 14-12-2024
    r"|\d{6,8}"                       # 141207 / 20240513
    r")[._\s-]+",
)
MULTI_PERFORMER_SEP_RE = re.compile(
    r"\s+and\s+|\s*&\s*|\s*,\s*|\s+with\s+|\s+feat\.?\s+|\s+ft\.?\s+",
    re.IGNORECASE,
)
COUNTRY_CODE_RE = re.compile(r"[._\s-]*\[([A-Z]{2,3})\]\s*$")
TRAILING_ID_RE = re.compile(
    r"[._\-\s]+(?:[SV]\d+[._\-\s]+)*[SV]?\d{4,}\s*$",
    re.IGNORECASE,
)
AND_SPLIT_RE = re.compile(r"[._\s\-]+and[._\s\-]+", re.IGNORECASE)
SEPARATOR_DASH_RE = re.compile(r"\s+-\s+")


@dataclass
class ParsedFilename:
    raw: str
    basename: str
    title: str | None = None
    date: str | None = None  # YYYY-MM-DD
    country: str | None = None  # ISO 2-3 letter code from .[CC]
    category: str | None = None  # category inferred from parent directory
    performer_candidates: list[list[str]] = field(default_factory=list)

    @property
    def performers(self) -> list[str]:
        return self.performer_candidates[0] if self.performer_candidates else []


@dataclass
class TorrentFile:
    index: int
    path: str
    name: str
    length: int
    parsed: ParsedFilename
    directory: str = ""  # parent directories joined with "/"


@dataclass
class AnalysisResult:
    torrent_file: TorrentFile
    status: str  # missing | present | unmatched | skipped
    detail: str
    matched_performer_ids: list[str] = field(default_factory=list)


@dataclass
class StudioSceneInfo:
    scene_id: str
    title: str
    date: str | None  # YYYY-MM-DD
    performer_ids: frozenset[str]
    file_sizes: list[int]


class StashClient:
    def __init__(self, url: str, api_key: str | None = None) -> None:
        self.url = url.rstrip("/")
        if not self.url.endswith("/graphql"):
            self.url = self.url + "/graphql"
        self.api_key = api_key

    def query(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"query": query}
        if variables:
            body["variables"] = variables
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["ApiKey"] = self.api_key
        req = urllib.request.Request(
            self.url,
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Stash HTTP {exc.code}: {detail}") from exc
        if payload.get("errors"):
            raise RuntimeError(json.dumps(payload["errors"], indent=2))
        return payload["data"]

    def find_studios(self, search: str = "", limit: int = 25) -> list[dict[str, Any]]:
        data = self.query(
            """
            query FindStudios($filter: FindFilterType) {
              findStudios(filter: $filter) {
                count
                studios { id name }
              }
            }
            """,
            {"filter": {"q": search, "per_page": limit, "sort": "name", "direction": "ASC"}},
        )
        return data["findStudios"]["studios"]

    def load_studio_performer_index(self, studio_id: str) -> dict[str, set[str]]:
        """
        Build normalized name/alias -> performer_id map for performers
        that appear in at least one scene of the given studio.
        """
        name_to_ids: dict[str, set[str]] = {}
        page = 1
        per_page = 500
        while True:
            data = self.query(
                """
                query StudioScenes($filter: FindFilterType, $scene_filter: SceneFilterType) {
                  findScenes(filter: $filter, scene_filter: $scene_filter) {
                    count
                    scenes {
                      performers { id name alias_list }
                    }
                  }
                }
                """,
                {
                    "filter": {"page": page, "per_page": per_page, "sort": "id", "direction": "ASC"},
                    "scene_filter": {
                        "studios": {
                            "value": [studio_id],
                            "modifier": "INCLUDES",
                            "depth": 0,
                        }
                    },
                },
            )
            scenes = data["findScenes"]["scenes"]
            if not scenes:
                break
            for scene in scenes:
                for performer in scene.get("performers") or []:
                    pid = str(performer["id"])
                    names = [performer.get("name") or ""]
                    aliases = performer.get("alias_list") or []
                    if isinstance(aliases, str):
                        aliases = [a.strip() for a in aliases.split(",") if a.strip()]
                    for name in names + list(aliases):
                        key = normalize_name(name)
                        if not key:
                            continue
                        name_to_ids.setdefault(key, set()).add(pid)
            if len(scenes) < per_page:
                break
            page += 1
        return name_to_ids

    def find_performer_by_name(self, name: str) -> dict[str, Any] | None:
        data = self.query(
            """
            query FindPerformers($filter: FindFilterType) {
              findPerformers(filter: $filter) {
                performers { id name alias_list }
              }
            }
            """,
            {"filter": {"q": name, "per_page": 25}},
        )
        target = normalize_name(name)
        for performer in data["findPerformers"]["performers"]:
            names = [performer.get("name") or ""]
            aliases = performer.get("alias_list") or []
            if isinstance(aliases, str):
                aliases = [a.strip() for a in aliases.split(",") if a.strip()]
            for candidate in names + list(aliases):
                if normalize_name(candidate) == target:
                    return performer
        return None

    def load_studio_scenes(self, studio_id: str) -> list[StudioSceneInfo]:
        """Load all scenes in the studio with their performer IDs, file sizes and date."""
        result: list[StudioSceneInfo] = []
        page = 1
        per_page = 500
        while True:
            data = self.query(
                """
                query StudioScenes($filter: FindFilterType, $scene_filter: SceneFilterType) {
                  findScenes(filter: $filter, scene_filter: $scene_filter) {
                    scenes {
                      id
                      title
                      date
                      performers { id }
                      files { size }
                    }
                  }
                }
                """,
                {
                    "filter": {"page": page, "per_page": per_page, "sort": "id", "direction": "ASC"},
                    "scene_filter": {
                        "studios": {
                            "value": [studio_id],
                            "modifier": "INCLUDES",
                            "depth": 0,
                        }
                    },
                },
            )
            scenes = data["findScenes"]["scenes"]
            if not scenes:
                break
            for scene in scenes:
                ids = frozenset(str(p["id"]) for p in (scene.get("performers") or []))
                if not ids:
                    continue
                sizes: list[int] = []
                for f in scene.get("files") or []:
                    try:
                        sizes.append(int(f.get("size") or 0))
                    except (TypeError, ValueError):
                        continue
                date_value = scene.get("date") or None
                if date_value and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_value):
                    date_value = None
                result.append(
                    StudioSceneInfo(
                        scene_id=str(scene["id"]),
                        title=scene.get("title") or "",
                        date=date_value,
                        performer_ids=ids,
                        file_sizes=sizes,
                    )
                )
            if len(scenes) < per_page:
                break
            page += 1
        return result


# --- qBittorrent Web API ---


class QBittorrentError(Exception):
    pass


class QBittorrentClient:
    """Minimal qBittorrent Web API client (no external deps).

    qBittorrent v5.1.0 endpoints used:
      POST /api/v2/auth/login
      POST /api/v2/torrents/add
      GET  /api/v2/torrents/files?hash=...
      GET  /api/v2/torrents/info?hashes=...
      POST /api/v2/torrents/filePrio
      POST /api/v2/torrents/resume
    """

    def __init__(self, url: str) -> None:
        self.url = url.rstrip("/")
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )

    def _post(self, path: str, data: bytes, content_type: str, timeout: int = 30) -> bytes:
        req = urllib.request.Request(
            f"{self.url}{path}",
            data=data,
            headers={"Content-Type": content_type, "Referer": self.url},
        )
        try:
            with self.opener.open(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise QBittorrentError(f"HTTP {exc.code}: {body}") from exc

    def _get(self, path: str, timeout: int = 10) -> bytes:
        req = urllib.request.Request(f"{self.url}{path}", headers={"Referer": self.url})
        try:
            with self.opener.open(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise QBittorrentError(f"HTTP {exc.code}: {body}") from exc

    def reachable(self) -> bool:
        try:
            self._get("/api/v2/app/version", timeout=5)
            return True
        except (QBittorrentError, urllib.error.URLError, ConnectionError, TimeoutError):
            return False

    def login(self, username: str, password: str) -> None:
        data = urllib.parse.urlencode({"username": username, "password": password}).encode()
        body = self._post("/api/v2/auth/login", data, "application/x-www-form-urlencoded")
        if body.strip() != b"Ok.":
            raise QBittorrentError(f"Login failed: {body.decode('utf-8', errors='replace').strip()}")

    def add_torrent_file(
        self,
        torrent_data: bytes,
        torrent_filename: str,
        paused: bool = True,
        save_path: str | None = None,
        category: str | None = None,
    ) -> None:
        boundary = "----QBitTorrentBoundary7f9a3d2e5b1c"
        bnd = boundary.encode("ascii")
        chunks: list[bytes] = []

        def add_field(name: str, value: str) -> None:
            chunks.append(b"--" + bnd + b"\r\n")
            chunks.append(
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8")
            )
            chunks.append(value.encode("utf-8"))
            chunks.append(b"\r\n")

        add_field("paused", "true" if paused else "false")
        add_field("stopped", "true" if paused else "false")
        add_field("autoTMM", "false")
        if save_path:
            add_field("savepath", save_path)
        if category:
            add_field("category", category)

        chunks.append(b"--" + bnd + b"\r\n")
        chunks.append(
            f'Content-Disposition: form-data; name="torrents"; filename="{torrent_filename}"\r\n'.encode(
                "utf-8"
            )
        )
        chunks.append(b"Content-Type: application/x-bittorrent\r\n\r\n")
        chunks.append(torrent_data)
        chunks.append(b"\r\n--" + bnd + b"--\r\n")

        body = b"".join(chunks)
        self._post(
            "/api/v2/torrents/add",
            body,
            f"multipart/form-data; boundary={boundary}",
            timeout=60,
        )

    def torrent_info(self, info_hash: str) -> list[dict[str, Any]]:
        body = self._get(f"/api/v2/torrents/info?hashes={info_hash}")
        return json.loads(body)

    def wait_for_torrent(self, info_hash: str, timeout_seconds: int = 15) -> bool:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            info = self.torrent_info(info_hash)
            if info:
                return True
            time.sleep(0.5)
        return False

    def torrent_files(self, info_hash: str) -> list[dict[str, Any]]:
        body = self._get(f"/api/v2/torrents/files?hash={info_hash}")
        return json.loads(body)

    def set_file_priorities(self, info_hash: str, file_ids: list[int], priority: int) -> None:
        if not file_ids:
            return
        data = urllib.parse.urlencode(
            {
                "hash": info_hash,
                "id": "|".join(str(i) for i in file_ids),
                "priority": str(priority),
            }
        ).encode()
        self._post("/api/v2/torrents/filePrio", data, "application/x-www-form-urlencoded")

    def resume_torrent(self, info_hash: str) -> None:
        data = urllib.parse.urlencode({"hashes": info_hash}).encode()
        for path in ("/api/v2/torrents/start", "/api/v2/torrents/resume"):
            try:
                self._post(path, data, "application/x-www-form-urlencoded")
                return
            except QBittorrentError:
                continue


# --- bencode ---


def bencode_encode(value: Any) -> bytes:
    if isinstance(value, bytes):
        return str(len(value)).encode("ascii") + b":" + value
    if isinstance(value, str):
        return bencode_encode(value.encode("utf-8"))
    if isinstance(value, int):
        return b"i" + str(value).encode("ascii") + b"e"
    if isinstance(value, list):
        return b"l" + b"".join(bencode_encode(v) for v in value) + b"e"
    if isinstance(value, dict):
        items = sorted(value.items(), key=lambda kv: kv[0])
        return b"d" + b"".join(bencode_encode(k) + bencode_encode(v) for k, v in items) + b"e"
    raise TypeError(f"Cannot bencode {type(value)!r}")


def bencode_decode(data: bytes, index: int = 0) -> tuple[Any, int]:
    if data[index : index + 1] == b"i":
        end = data.index(b"e", index)
        return int(data[index + 1 : end]), end + 1
    if data[index : index + 1] == b"l":
        result: list[Any] = []
        index += 1
        while data[index : index + 1] != b"e":
            value, index = bencode_decode(data, index)
            result.append(value)
        return result, index + 1
    if data[index : index + 1] == b"d":
        result: dict[Any, Any] = {}
        index += 1
        while data[index : index + 1] != b"e":
            key, index = bencode_decode(data, index)
            value, index = bencode_decode(data, index)
            result[key] = value
        return result, index + 1
    if data[index : index + 1].isdigit():
        colon = data.index(b":", index)
        length = int(data[index:colon])
        start = colon + 1
        return data[start : start + length], start + length
    raise ValueError(f"Invalid bencode at offset {index}")


def b2s(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


# --- torrent ---


def load_torrent(path: Path) -> tuple[dict[Any, Any], dict[Any, Any]]:
    data = path.read_bytes()
    torrent, _ = bencode_decode(data)
    if b"info" not in torrent:
        raise ValueError("Invalid torrent: missing info dict")
    return torrent, torrent[b"info"]


def iter_torrent_files(info: dict[Any, Any]) -> list[tuple[list[str], int]]:
    if b"files" in info:
        files: list[tuple[list[str], int]] = []
        for entry in info[b"files"]:
            path_parts = [b2s(p) for p in entry[b"path"]]
            length = int(entry.get(b"length", 0))
            files.append((path_parts, length))
        return files
    name = b2s(info[b"name"])
    length = int(info.get(b"length", 0))
    return [([name], length)]


def list_video_files(info: dict[Any, Any]) -> list[TorrentFile]:
    result: list[TorrentFile] = []
    for index, (path_parts, length) in enumerate(iter_torrent_files(info)):
        path = "/".join(path_parts)
        name = path_parts[-1]
        directory = "/".join(path_parts[:-1])
        if any(part.startswith(".pad") for part in path_parts):
            continue
        ext = Path(name).suffix.lower()
        if ext not in VIDEO_EXTENSIONS:
            continue
        parsed = parse_filename(name, directory=directory)
        result.append(TorrentFile(
            index=index, path=path, name=name, length=length,
            parsed=parsed, directory=directory,
        ))
    return result


KNOWN_CATEGORY_DIRS = {
    "chat", "chats", "casting", "castings", "casting x", "castingx",
    "cpx", "axt", "xxxx", "wsg", "smm", "wunf", "x69", "area x69",
    "bts", "behind the scenes", "updated", "updates",
    "scenes", "videos", "vids", "filme", "filme casting", "filmy",
    "csh", "interview", "interviews", "raw", "remainder", "remainders",
}


def _strip_dir_prefix(name: str, directory: str) -> str:
    """Strip a redundant directory-name prefix from filename stem.

    e.g. dir='Chat', name='chat-adria-...' → 'adria-...'.
    Only strips if the directory IS a known category (avoid stripping real
    performer-name prefixes like 'Pierre Woodman').
    """
    if not directory:
        return name
    last = directory.split("/")[-1].strip().lower()
    if last not in KNOWN_CATEGORY_DIRS:
        return name
    stem = Path(name).stem
    pattern = re.compile(rf"^{re.escape(last)}[\s._\-]+", re.IGNORECASE)
    stripped = pattern.sub("", stem)
    if stripped == stem:
        return name
    return stripped + Path(name).suffix


def torrent_is_v2(info: dict[Any, Any]) -> bool:
    return b"meta version" in info and int(info[b"meta version"]) >= 2


def torrent_has_v1_data(info: dict[Any, Any]) -> bool:
    return b"pieces" in info and b"piece length" in info


def is_bep47_padded(info: dict[Any, Any]) -> bool:
    """True if torrent contains BEP 47 pad files (real files are piece-aligned)."""
    if b"files" not in info:
        return False
    for entry in info[b"files"]:
        path = entry.get(b"path") or []
        if path and path[0] == b".pad":
            return True
        if entry.get(b"attr") == b"p":
            return True
    return False


def info_hashes(info: dict[Any, Any]) -> tuple[str | None, str | None]:
    encoded = bencode_encode(info)
    v1_hash = hashlib.sha1(encoded).hexdigest() if torrent_has_v1_data(info) else None
    v2_hash = hashlib.sha256(encoded).hexdigest() if torrent_is_v2(info) else None
    return v1_hash, v2_hash


# --- filename parsing ---


def normalize_name(name: str) -> str:
    cleaned = re.sub(r"\s+", " ", name.strip().lower())
    cleaned = cleaned.strip("._-")
    return cleaned


def titlecase_performer(name: str) -> str:
    parts = re.split(r"(\s+)", name.strip())
    return "".join(p[:1].upper() + p[1:].lower() if p.strip() else p for p in parts)


def parse_date_prefix(text: str) -> str | None:
    """Parse a date string (any common format) into 'YYYY-MM-DD' or None."""
    s = text.strip("._-/ ")
    m = re.fullmatch(r"(\d{4})[._\-/](\d{2})[._\-/](\d{2})", s)
    if m:
        y, mo, d = m.group(1), m.group(2), m.group(3)
        if 1 <= int(mo) <= 12 and 1 <= int(d) <= 31:
            return f"{y}-{mo}-{d}"
    m = re.fullmatch(r"(\d{2})[._\-/](\d{2})[._\-/](\d{2,4})", s)
    if m:
        a, b, c = m.group(1), m.group(2), m.group(3)
        if len(c) == 4:
            if 1 <= int(a) <= 31 and 1 <= int(b) <= 12:
                return f"{c}-{b}-{a}"
        elif len(c) == 2:
            yy = int(c)
            year = f"20{c}" if yy <= 30 else f"19{c}"
            if 1 <= int(a) <= 31 and 1 <= int(b) <= 12:
                return f"{year}-{b}-{a}"
    if re.fullmatch(r"\d{8}", s):
        y, mo, d = s[:4], s[4:6], s[6:8]
        if 1 <= int(mo) <= 12 and 1 <= int(d) <= 31 and 1900 <= int(y) <= 2099:
            return f"{y}-{mo}-{d}"
    if re.fullmatch(r"\d{6}", s):
        yy, mo, d = int(s[:2]), int(s[2:4]), int(s[4:6])
        if 1 <= mo <= 12 and 1 <= d <= 31:
            year = 2000 + yy if yy <= 30 else 1900 + yy
            return f"{year:04d}-{mo:02d}-{d:02d}"
    return None


def split_performer_names(text: str) -> list[str]:
    text = text.strip(" ._-")
    if not text:
        return []
    parts = MULTI_PERFORMER_SEP_RE.split(text)
    return [titlecase_performer(p.strip()) for p in parts if p.strip()]


def make_performer_variants(text: str) -> list[list[str]]:
    """Generate possible interpretations of a performer string.

    Returned variants are tried in order; the first one that fully resolves
    against the Stash performer index wins. Hyphenated names like
    'Nikki-Dikki' produce variants: ['Nikki Dikki'], ['Dikki Nikki'],
    ['Nikki', 'Dikki'] so we cover single-name, reversed and two-performer cases.
    """
    text = text.strip(" ._-")
    if not text:
        return []

    cleaned = re.sub(r"[._]+", " ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    if MULTI_PERFORMER_SEP_RE.search(cleaned):
        names = [titlecase_performer(p.strip()) for p in MULTI_PERFORMER_SEP_RE.split(cleaned) if p.strip()]
        if names:
            return [names]

    if "-" in cleaned:
        parts = [p.strip() for p in cleaned.split("-") if p.strip()]
        non_digit_parts = [p for p in parts if not p.isdigit()]
        if len(non_digit_parts) == 2:
            a, b = non_digit_parts
            joined_forward = titlecase_performer(f"{a} {b}")
            joined_reverse = titlecase_performer(f"{b} {a}")
            variants: list[list[str]] = [[joined_forward]]
            if joined_reverse != joined_forward:
                variants.append([joined_reverse])
            variants.append([titlecase_performer(a), titlecase_performer(b)])
            return variants
        if len(non_digit_parts) >= 3:
            joined = titlecase_performer(" ".join(non_digit_parts))
            split = [titlecase_performer(p) for p in non_digit_parts]
            return [[joined], split]
        cleaned = " ".join(non_digit_parts) if non_digit_parts else cleaned

    return [[titlecase_performer(cleaned)]]


def normalize_underscores(text: str) -> str:
    """Convert '_-_' to ' - ' and other underscores to spaces."""
    text = re.sub(r"_+\s*-\s*_+", " - ", text)
    text = re.sub(r"_+", " ", text)
    return text.strip()


def split_words(text: str) -> list[str]:
    """Split on whitespace, hyphens, dots, underscores; drop empty."""
    return [p for p in re.split(r"[._\s\-]+", text) if p.strip()]


def parse_and_split_filename(stem: str) -> tuple[list[str], str | None]:
    """For '<Name1>-And-<Name2>-<title-words>', return ([name1, name2], title) or ([], None)."""
    m = AND_SPLIT_RE.search(stem)
    if not m:
        return [], None
    before = stem[: m.start()]
    after = stem[m.end():]
    before_words = split_words(before)
    after_words = split_words(after)
    if not before_words or not after_words:
        return [], None
    n_before = min(2, len(before_words))
    p1 = " ".join(before_words[:n_before])
    after_non_digit_count = sum(1 for w in after_words if not w.isdigit())
    n_after = 2 if after_non_digit_count >= 2 else 1
    consumed = 0
    p2_parts: list[str] = []
    for w in after_words:
        if consumed >= n_after:
            break
        if not w.isdigit():
            p2_parts.append(w)
            consumed += 1
        else:
            p2_parts.append(w)
    p2 = " ".join(p2_parts)
    title_words = after_words[len(p2_parts):]
    title = " ".join(title_words) if title_words else None
    return [titlecase_performer(p1), titlecase_performer(p2)], title


def parse_filename(filename: str, directory: str = "") -> ParsedFilename:
    # Strip a redundant directory-name prefix (e.g. dir 'Chat' from name 'chat-...')
    effective_filename = _strip_dir_prefix(filename, directory)
    stem = Path(effective_filename).stem
    stem = RESOLUTION_IN_NAME_RE.sub(" ", stem)
    stem = QUALITY_RE.sub("", stem).strip()

    parsed = ParsedFilename(raw=filename, basename=stem)
    if directory:
        last_dir = directory.split("/")[-1].strip()
        if last_dir and last_dir.lower() in KNOWN_CATEGORY_DIRS:
            parsed.category = last_dir

    country_match = COUNTRY_CODE_RE.search(stem)
    if country_match:
        parsed.country = country_match.group(1).upper()
        stem = stem[: country_match.start()].strip()

    code_match = CODE_PREFIX_RE.match(stem)
    if code_match:
        parsed.title = code_match.group(1).strip()
        performer_text = code_match.group(2).strip()
        parsed.performer_candidates = make_performer_variants(performer_text)
        return parsed

    date_match = DATE_PREFIX_RE.match(stem)
    if date_match:
        raw_date = stem[: date_match.end()].rstrip("._- ")
        parsed.date = parse_date_prefix(raw_date)
        rest = stem[date_match.end():].strip()
        rest = TRAILING_ID_RE.sub("", rest).strip()
        rest = normalize_underscores(rest)
        rest = PART_SUFFIX_RE.sub("", rest).strip()
        parsed.performer_candidates = make_performer_variants(rest)
        return parsed

    stem = TRAILING_ID_RE.sub("", stem).strip()
    stem = normalize_underscores(stem)
    stem = PART_SUFFIX_RE.sub("", stem).strip()

    sep_match = SEPARATOR_DASH_RE.search(stem)
    if sep_match:
        performer_text = stem[: sep_match.start()].strip()
        title_text = stem[sep_match.end():].strip()
        if performer_text:
            if title_text:
                parsed.title = title_text
            parsed.performer_candidates = make_performer_variants(performer_text)
            return parsed

    and_names, and_title = parse_and_split_filename(stem)
    if and_names:
        if and_title:
            parsed.title = and_title
        parsed.performer_candidates = [and_names]
        return parsed

    parts = split_words(stem)
    non_digit_parts = [p for p in parts if not p.isdigit()]
    if len(non_digit_parts) >= 4:
        title_text = " ".join(parts[2:]) if len(parts) > 2 else None
        if title_text:
            parsed.title = title_text
        variants: list[list[str]] = [
            [titlecase_performer(" ".join(non_digit_parts[:2]))],
        ]
        if len(non_digit_parts) >= 3:
            variants.append([titlecase_performer(" ".join(non_digit_parts[:3]))])
        parsed.performer_candidates = variants
        return parsed

    if re.search(r"\d", stem) and re.search(r"[a-zA-Z]", stem):
        tokens = stem.split()
        split_at = None
        for i, token in enumerate(tokens):
            if token.isdigit() or re.fullmatch(r"\d+[a-zA-Z]+", token):
                split_at = i
                break
        if split_at is not None and split_at < len(tokens) - 1:
            parsed.title = " ".join(tokens[: split_at + 1])
            rest = " ".join(tokens[split_at + 1:])
            candidates = make_performer_variants(rest)
            if candidates:
                parsed.performer_candidates = candidates
                return parsed

    parsed.performer_candidates = make_performer_variants(stem)
    return parsed


# --- matching ---


def resolve_performer_ids(names: list[str], index: dict[str, set[str]]) -> tuple[list[str], list[str]]:
    matched_ids: list[str] = []
    unmatched: list[str] = []
    for name in names:
        key = normalize_name(name)
        ids = index.get(key)
        if not ids:
            unmatched.append(name)
            continue
        matched_ids.extend(sorted(ids))
    return sorted(set(matched_ids)), unmatched


def fmt_mb(num_bytes: int) -> str:
    return f"{num_bytes / (1024 * 1024):.1f} MB"


def _resolve_single_variant(
    names: list[str],
    performer_index: dict[str, set[str]],
    stash: StashClient,
    global_cache: dict[str, dict[str, Any] | None],
) -> tuple[list[str], list[str]]:
    matched_ids, unmatched = resolve_performer_ids(names, performer_index)
    for name in unmatched:
        key = normalize_name(name)
        if key not in global_cache:
            global_cache[key] = stash.find_performer_by_name(name)
        performer = global_cache[key]
        if performer:
            matched_ids.append(str(performer["id"]))
    matched_ids = sorted(set(matched_ids))
    still_unknown = [
        n for n in names
        if normalize_name(n) not in performer_index
        and not global_cache.get(normalize_name(n))
    ]
    return matched_ids, still_unknown


def resolve_for_file(
    tf: TorrentFile,
    performer_index: dict[str, set[str]],
    stash: StashClient,
    global_cache: dict[str, dict[str, Any] | None],
) -> tuple[list[str], list[str], list[str]]:
    """Try each performer-variant; return (matched_ids, still_unknown, chosen_names).

    The chosen variant is the first one with no unknown names (most complete).
    Otherwise the one with most matched IDs / fewest unknowns is picked.
    """
    candidates = tf.parsed.performer_candidates or [[]]

    best: tuple[list[str], list[str], list[str]] | None = None
    best_score: tuple[int, int] | None = None  # (unknown_count, -matched_count) lower is better

    for variant in candidates:
        if not variant:
            continue
        matched_ids, still_unknown = _resolve_single_variant(
            variant, performer_index, stash, global_cache
        )
        if not still_unknown and matched_ids:
            return matched_ids, still_unknown, variant
        score = (len(still_unknown), -len(matched_ids))
        if best_score is None or score < best_score:
            best_score = score
            best = (matched_ids, still_unknown, variant)

    if best is None:
        primary = candidates[0] if candidates else []
        return [], primary, primary
    return best


def analyse_all(
    torrent_files: list[TorrentFile],
    performer_index: dict[str, set[str]],
    studio_scenes: list[StudioSceneInfo],
    stash: StashClient,
    global_cache: dict[str, dict[str, Any] | None],
    size_check: bool,
    size_tolerance_bytes: int,
) -> list[AnalysisResult]:
    """Resolve performers for every file, then bucket by performer-set and match.

    If size_check is True, each torrent file is paired greedily with a candidate
    scene file by file-size proximity (within size_tolerance_bytes). Once a scene
    file is consumed by one torrent file, it cannot match another — so multiple
    parts (e.g. 'Abby Lee Brazil 1/2.mp4') are correctly deduplicated.
    """
    resolved: dict[int, tuple[frozenset[str], list[str], list[str]]] = {}
    early_results: dict[int, AnalysisResult] = {}
    chosen_variant: dict[int, list[str]] = {}

    for tf in torrent_files:
        if not tf.parsed.performer_candidates:
            early_results[tf.index] = AnalysisResult(
                tf, "skipped", "Nie udało się wyciągnąć nazw aktorów z pliku"
            )
            continue
        matched_ids, still_unknown, variant = resolve_for_file(
            tf, performer_index, stash, global_cache
        )
        chosen_variant[tf.index] = variant
        if still_unknown:
            tried = " / ".join(", ".join(v) for v in tf.parsed.performer_candidates)
            early_results[tf.index] = AnalysisResult(
                tf, "unmatched",
                f"Aktorzy nieznani w bazie Stash: {', '.join(still_unknown)} (próby: {tried})",
            )
            continue
        if not matched_ids:
            tried = " / ".join(", ".join(v) for v in tf.parsed.performer_candidates)
            early_results[tf.index] = AnalysisResult(
                tf, "unmatched",
                f"Nie znaleziono aktorów w Stash (próby: {tried})",
            )
            continue
        resolved[tf.index] = (frozenset(matched_ids), matched_ids, variant)

    groups: dict[frozenset[str], list[TorrentFile]] = {}
    for tf in torrent_files:
        if tf.index in resolved:
            perf_set, _matched, _variant = resolved[tf.index]
            groups.setdefault(perf_set, []).append(tf)

    final: dict[int, AnalysisResult] = {}

    def date_compatible(file_date: str | None, scene_date: str | None) -> bool:
        """Scene is a date-candidate if file has no date, or both match, or scene has no date."""
        if not file_date:
            return True
        if not scene_date:
            return True
        return file_date == scene_date

    for perf_set, files in groups.items():
        all_candidates = [
            s for s in studio_scenes if perf_set.issubset(s.performer_ids)
        ]
        perf_names = chosen_variant.get(files[0].index, list(files[0].parsed.performers))

        # Flat list of available scene files for greedy matching: each entry is mutable.
        # [size, scene_id, scene_title, scene_date, is_exact_performer, used]
        avail: list[list[Any]] = []
        for s in all_candidates:
            is_exact = s.performer_ids == perf_set
            for size in s.file_sizes:
                if size > 0:
                    avail.append([size, s.scene_id, s.title, s.date, is_exact, False])

        if not size_check:
            for tf in files:
                file_date = tf.parsed.date
                compatible = [s for s in all_candidates if date_compatible(file_date, s.date)]
                if compatible:
                    exact_compat = any(s.performer_ids == perf_set for s in compatible)
                    date_hit = next((s for s in compatible if file_date and s.date == file_date), None)
                    date_info = f", data={file_date}" if date_hit else ""
                    if exact_compat:
                        detail = f"Scena ze wszystkimi aktorami: {', '.join(perf_names)}{date_info}"
                    else:
                        detail = f"Scena z co najmniej tymi aktorami: {', '.join(perf_names)}{date_info}"
                    final[tf.index] = AnalysisResult(tf, "present", detail, sorted(perf_set))
                else:
                    if all_candidates and file_date:
                        scene_dates = sorted({s.date for s in all_candidates if s.date})
                        if scene_dates:
                            others = ", ".join(scene_dates[:3])
                            if len(scene_dates) > 3:
                                others += ", ..."
                            detail = (
                                f"Aktor {', '.join(perf_names)} ma sceny, "
                                f"ale brak na datę {file_date} (są: {others})"
                            )
                        else:
                            detail = (
                                f"Aktor {', '.join(perf_names)} ma sceny bez ustalonej daty — "
                                f"oczekiwano {file_date}"
                            )
                    else:
                        detail = f"Brak sceny w tym studio dla: {', '.join(perf_names)}"
                    final[tf.index] = AnalysisResult(tf, "missing", detail, sorted(perf_set))
            continue

        files_sorted = sorted(files, key=lambda f: -f.length)

        for tf in files_sorted:
            file_date = tf.parsed.date
            best_idx = -1
            best_score: tuple[int, int, int] | None = None  # (date_rank, exact_rank, size_diff)
            for i, entry in enumerate(avail):
                size, _sid, _title, sdate, is_exact, used = entry
                if used:
                    continue
                if not date_compatible(file_date, sdate):
                    continue
                diff = abs(size - tf.length)
                if diff > size_tolerance_bytes:
                    continue
                date_rank = 0 if (file_date and sdate == file_date) else 1
                exact_rank = 0 if is_exact else 1
                score = (date_rank, exact_rank, diff)
                if best_score is None or score < best_score:
                    best_score = score
                    best_idx = i

            if best_idx >= 0:
                avail[best_idx][5] = True
                size, sid, title, sdate, is_exact, _ = avail[best_idx]
                label = title or f"scena #{sid}"
                kind = "" if is_exact else " (podzbiór aktorów)"
                date_info = f", data={sdate}" if sdate else ""
                final[tf.index] = AnalysisResult(
                    tf, "present",
                    f"Dopasowano '{label}' [{fmt_mb(size)}, Δ={fmt_mb(best_score[2])}{date_info}]{kind}",
                    sorted(perf_set),
                )
            else:
                if all_candidates:
                    date_part = f", data {file_date}" if file_date else ""
                    detail = (
                        f"Brak sceny o zbliżonym rozmiarze ({fmt_mb(tf.length)}{date_part}) "
                        f"dla {', '.join(perf_names)}"
                    )
                else:
                    detail = f"Brak sceny w tym studio dla: {', '.join(perf_names)}"
                final[tf.index] = AnalysisResult(tf, "missing", detail, sorted(perf_set))

    return [early_results.get(tf.index) or final[tf.index] for tf in torrent_files]


# --- qBittorrent integration ---


def push_to_qbittorrent(
    torrent_path: Path,
    info: dict[Any, Any],
    all_files: list[tuple[list[str], int]],
    missing: list[AnalysisResult],
    qb_url: str,
    qb_user: str | None,
    qb_pass: str | None,
    save_path: str | None,
    category: str | None,
    auto_start: bool,
    non_interactive: bool,
) -> bool:
    v1_hash, v2_hash = info_hashes(info)
    primary_hash = v1_hash or v2_hash
    if not primary_hash:
        print("Nie udało się wyliczyć info-hash z torrenta.", file=sys.stderr)
        return False

    client = QBittorrentClient(qb_url)
    if not client.reachable():
        print(
            f"Nie mogę się połączyć z qBittorrent pod {qb_url}.\n"
            "  • Włącz Web UI: Tools → Preferences → Web UI\n"
            "  • Sprawdź port (domyślnie 8080)",
            file=sys.stderr,
        )
        return False

    try:
        client.torrent_info(primary_hash)
        authenticated = True
    except QBittorrentError as exc:
        msg = str(exc)
        if "403" in msg:
            authenticated = False
        else:
            print(f"qBittorrent: {exc}", file=sys.stderr)
            return False

    if not authenticated:
        if qb_user is None and not non_interactive:
            qb_user = input("qBittorrent user [admin]: ").strip() or "admin"
        if qb_pass is None and not non_interactive:
            qb_pass = getpass.getpass("qBittorrent password: ")
        try:
            client.login(qb_user or "", qb_pass or "")
        except QBittorrentError as exc:
            print(f"Logowanie do qBittorrent nieudane: {exc}", file=sys.stderr)
            return False

    existing = []
    try:
        existing = client.torrent_info(primary_hash)
    except QBittorrentError as exc:
        print(f"qBittorrent torrent info: {exc}", file=sys.stderr)
        return False

    if existing:
        print(
            f"Torrent jest już w qBittorrent (hash={primary_hash[:12]}…). "
            "Pomijam dodawanie, ustawiam priorytety na istniejącym."
        )
    else:
        try:
            torrent_data = torrent_path.read_bytes()
            client.add_torrent_file(
                torrent_data,
                torrent_path.name,
                paused=True,
                save_path=save_path,
                category=category,
            )
        except QBittorrentError as exc:
            print(f"Dodawanie torrenta nieudane: {exc}", file=sys.stderr)
            return False

        if not client.wait_for_torrent(primary_hash, timeout_seconds=20):
            if v2_hash and primary_hash != v2_hash:
                if client.wait_for_torrent(v2_hash, timeout_seconds=5):
                    primary_hash = v2_hash
                else:
                    print(
                        "qBittorrent nie zarejestrował torrenta w 25s. "
                        "Sprawdź ręcznie w GUI.",
                        file=sys.stderr,
                    )
                    return False
            else:
                print(
                    "qBittorrent nie zarejestrował torrenta w 20s. "
                    "Sprawdź ręcznie w GUI.",
                    file=sys.stderr,
                )
                return False

    try:
        qb_files = client.torrent_files(primary_hash)
    except QBittorrentError as exc:
        print(f"qBittorrent torrent files: {exc}", file=sys.stderr)
        return False

    missing_indices = {item.torrent_file.index for item in missing}
    qb_total = len(qb_files)
    our_total = len(all_files)

    if qb_total != our_total:
        print(
            f"Uwaga: qBittorrent widzi {qb_total} plików, my mamy {our_total}. "
            "Próbuję mapować po ścieżce..."
        )
        path_to_index: dict[str, int] = {}
        for idx, (parts, _length) in enumerate(all_files):
            path_to_index["/".join(parts)] = idx
        mapped_missing: list[int] = []
        mapped_keep: list[int] = []
        for qb_idx, qf in enumerate(qb_files):
            qb_path = qf.get("name", "").replace("\\", "/")
            original_idx = path_to_index.get(qb_path)
            if original_idx is None:
                continue
            if original_idx in missing_indices:
                mapped_missing.append(qb_idx)
            else:
                mapped_keep.append(qb_idx)
    else:
        mapped_missing = [i for i in range(qb_total) if i in missing_indices]
        mapped_keep = [i for i in range(qb_total) if i not in missing_indices]

    try:
        client.set_file_priorities(primary_hash, mapped_keep, 0)
        client.set_file_priorities(primary_hash, mapped_missing, 1)
    except QBittorrentError as exc:
        print(f"Ustawianie priorytetów nieudane: {exc}", file=sys.stderr)
        return False

    print()
    print("=== qBittorrent ===")
    print(f"  Hash:           {primary_hash}")
    print(f"  Pliki w kliencie: {qb_total}")
    print(f"  Do pobrania:    {len(mapped_missing)}")
    print(f"  Pomijane:       {len(mapped_keep)}")

    if auto_start:
        client.resume_torrent(primary_hash)
        print("  Status:         Wznowiony (pobieranie startuje)")
    else:
        print("  Status:         Pauza (sprawdź pliki w GUI i wciśnij Start)")
    return True


# --- export ---


def create_v1_subset_torrent_with_padding(
    torrent: dict[Any, Any],
    info: dict[Any, Any],
    selected_indices: set[int],
    output_path: Path,
) -> None:
    """Create a v1 torrent that keeps original piece hashes (pad files fill gaps)."""
    new_files: list[dict[Any, Any]] = []
    for idx, (path_parts, length) in enumerate(iter_torrent_files(info)):
        if idx in selected_indices:
            new_files.append(
                {
                    b"length": length,
                    b"path": [p.encode("utf-8") for p in path_parts],
                }
            )
        else:
            new_files.append(
                {
                    b"length": length,
                    b"path": [b".pad", str(length).encode("ascii")],
                    b"attr": b"p",
                }
            )

    new_info: dict[Any, Any] = {
        b"name": info[b"name"],
        b"piece length": info[b"piece length"],
        b"pieces": info[b"pieces"],
        b"files": new_files,
    }
    new_torrent = {k: v for k, v in torrent.items() if k != b"info"}
    new_torrent[b"info"] = new_info
    output_path.write_bytes(bencode_encode(new_torrent))


def write_category_exports(
    torrent_path: Path,
    torrent: dict[Any, Any],
    info: dict[Any, Any],
    items: list[AnalysisResult],
    category: str,
    label_pl: str,
    output_dir: Path | None = None,
    force_subset_torrent: bool = False,
) -> None:
    """Write .{category}.txt, .{category}.json and (for BEP 47) _{category}.torrent."""
    if not items:
        return

    base_dir = output_dir if output_dir else torrent_path.parent
    base_dir.mkdir(parents=True, exist_ok=True)

    list_path = base_dir / f"{torrent_path.stem}.{category}.txt"
    list_path.write_text(
        "\n".join(item.torrent_file.path for item in items) + "\n",
        encoding="utf-8",
    )
    print(f"  Lista {label_pl}: {list_path}")

    indices = [item.torrent_file.index for item in items]
    meta_path = base_dir / f"{torrent_path.stem}.{category}.json"
    meta_path.write_text(
        json.dumps(
            {
                "source_torrent": str(torrent_path),
                "category": category,
                "file_count": len(items),
                "file_indices": indices,
                "files": [
                    {
                        "index": item.torrent_file.index,
                        "path": item.torrent_file.path,
                        "size": item.torrent_file.length,
                        "performers": list(item.torrent_file.parsed.performers),
                        "date": item.torrent_file.parsed.date,
                        "category": item.torrent_file.parsed.category,
                        "directory": item.torrent_file.directory,
                        "detail": item.detail,
                    }
                    for item in items
                ],
                "v2": torrent_is_v2(info),
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"  Metadane {label_pl}: {meta_path}")

    indices_set = {item.torrent_file.index for item in items}
    output_path = base_dir / f"{torrent_path.stem}_{category}.torrent"
    if is_bep47_padded(info):
        create_v1_subset_torrent_with_padding(torrent, info, indices_set, output_path)
        print(f"  Torrent  {label_pl}: {output_path}")
    elif force_subset_torrent:
        create_v1_subset_torrent_with_padding(torrent, info, indices_set, output_path)
        print(f"  Torrent  {label_pl}: {output_path}")
        print(
            f"           WARN: torrent v1 bez BEP 47 padding. "
            "Boundary-pieces (na granicach plików) mogą NIE przejść weryfikacji w kliencie. "
            "Jeśli nie zadziała, użyj --add-to-qbittorrent."
        )
    else:
        print(
            f"  Torrent  {label_pl}: pominięty (torrent v1 bez BEP 47 padding). "
            "Dodaj --force-subset-torrent żeby spróbować i tak, albo użyj --add-to-qbittorrent."
        )


# --- UI helpers ---


def choose_studio(
    stash: StashClient,
    preset_name: str | None,
    preset_id: str | None,
    non_interactive: bool = False,
) -> dict[str, Any]:
    if preset_id:
        data = stash.query(
            "query ($id: ID!) { findStudio(id: $id) { id name } }",
            {"id": preset_id},
        )
        studio = data.get("findStudio")
        if not studio:
            raise RuntimeError(f"Nie znaleziono studia o id={preset_id}")
        return studio

    if preset_name:
        studios = stash.find_studios(preset_name, limit=10)
        if not studios:
            raise RuntimeError(f"Nie znaleziono studia pasującego do: {preset_name}")
        if non_interactive or len(studios) == 1:
            return studios[0]
        exact = [s for s in studios if s["name"].lower() == preset_name.lower()]
        if len(exact) == 1:
            return exact[0]
        print(f"Wiele studiów pasuje do '{preset_name}':")
        for i, studio in enumerate(studios, start=1):
            print(f"  {i}. [{studio['id']}] {studio['name']}")
        choice = input("Numer studia: ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(studios):
            return studios[int(choice) - 1]
        return studios[0]

    search = ""
    while True:
        if not search:
            search = input("Szukaj studia (Enter = lista): ").strip()
        studios = stash.find_studios(search, limit=25)
        if not studios:
            print("Brak wyników.")
            search = input("Spróbuj inną frazę: ").strip()
            continue
        print("\nStudia:")
        for i, studio in enumerate(studios, start=1):
            print(f"  {i:2}. [{studio['id']}] {studio['name']}")
        choice = input("Numer studia (lub nowe wyszukiwanie): ").strip()
        if not choice:
            search = input("Fraza wyszukiwania: ").strip()
            continue
        if choice.isdigit():
            num = int(choice)
            if 1 <= num <= len(studios):
                return studios[num - 1]
        search = choice


def print_results(results: list[AnalysisResult]) -> None:
    groups = {"missing": [], "present": [], "unmatched": [], "skipped": []}
    for item in results:
        groups[item.status].append(item)

    print(f"\n=== Podsumowanie ===")
    print(f"  Brakujące:     {len(groups['missing'])}")
    print(f"  Posiadane:     {len(groups['present'])}")
    print(f"  Nierozpoznane: {len(groups['unmatched'])}")
    print(f"  Pominięte:     {len(groups['skipped'])}")

    def render_extras(p: ParsedFilename) -> str:
        parts: list[str] = []
        if p.date:
            parts.append(f"data: {p.date}")
        if p.category:
            parts.append(f"kategoria: {p.category}")
        if p.title:
            parts.append(f"tytuł: {p.title}")
        if p.country:
            parts.append(f"kraj: {p.country}")
        return " | " + ", ".join(parts) if parts else ""

    def render_alts(p: ParsedFilename) -> str:
        if len(p.performer_candidates) <= 1:
            return ""
        return "  [warianty: " + " / ".join(
            ", ".join(v) for v in p.performer_candidates[1:]
        ) + "]"

    if groups["missing"]:
        print("\n--- Brakujące pliki ---")
        for item in groups["missing"]:
            p = item.torrent_file.parsed
            perf = ", ".join(p.performers) if p.performers else "?"
            print(f"  {item.torrent_file.name}")
            print(f"    -> {perf}{render_extras(p)}{render_alts(p)}")
            print(f"    {item.detail}")

    if groups["unmatched"]:
        print("\n--- Nierozpoznane (aktorów nie ma w bazie Stash) ---")
        for item in groups["unmatched"]:
            p = item.torrent_file.parsed
            perf = ", ".join(p.performers) if p.performers else "?"
            print(f"  {item.torrent_file.name}")
            print(f"    -> {perf}{render_extras(p)}{render_alts(p)}")
            print(f"    {item.detail}")

    if groups["skipped"]:
        print("\n--- Pominięte (nie udało się sparsować nazw) ---")
        for item in groups["skipped"]:
            print(f"  {item.torrent_file.name}")
            print(f"    {item.detail}")


def interactive_export(
    torrent_path: Path,
    torrent: dict[Any, Any],
    info: dict[Any, Any],
    missing: list[AnalysisResult],
    unmatched: list[AnalysisResult],
    args: argparse.Namespace,
) -> None:
    if not missing and not unmatched:
        print("\nBrak plików do eksportu.")
        return

    auto_yes = args.yes
    print(
        f"\nZnaleziono {len(missing)} brakujących i {len(unmatched)} nierozpoznanych plików."
    )

    save = auto_yes
    if not auto_yes:
        ans = input(
            "Zapisać raporty (.txt / .json / .torrent) dla obu kategorii? [T/n]: "
        ).strip().lower()
        save = ans not in {"n", "no", "nie"}
    if save:
        out_dir = Path(args.output_dir) if args.output_dir else None
        if out_dir:
            print(f"Zapisuję raporty do: {out_dir}")
        else:
            print("Zapisuję raporty obok źródłowego .torrent:")
        write_category_exports(
            torrent_path, torrent, info, missing, "missing", "brakujące",
            output_dir=out_dir,
            force_subset_torrent=args.force_subset_torrent,
        )
        write_category_exports(
            torrent_path, torrent, info, unmatched, "unmatched", "nierozpoznane",
            output_dir=out_dir,
            force_subset_torrent=args.force_subset_torrent,
        )

    add_to_qb = args.add_to_qb
    if add_to_qb is None:
        if args.non_interactive or args.yes:
            add_to_qb = False
        else:
            ans = input(
                f"\nDodać torrent do qBittorrent ({args.qbittorrent_url}) "
                "z gotowymi priorytetami? [t/N]: "
            ).strip().lower()
            add_to_qb = ans in {"t", "y", "tak", "yes"}

    if not add_to_qb:
        return

    include_unmatched = args.qbittorrent_include_unmatched
    if include_unmatched is None and unmatched and not (args.non_interactive or args.yes):
        ans = input(
            f"Dodać też {len(unmatched)} nierozpoznanych do pobrania? [t/N]: "
        ).strip().lower()
        include_unmatched = ans in {"t", "y", "tak", "yes"}

    to_download: list[AnalysisResult] = list(missing)
    if include_unmatched and unmatched:
        to_download.extend(unmatched)
        print(f"qBittorrent: dodaję {len(missing)} brakujących + {len(unmatched)} nierozpoznanych.")
    else:
        print(f"qBittorrent: dodaję {len(missing)} brakujących.")

    if not to_download:
        print("Brak plików do pobrania — pomijam dodawanie do qBittorrent.")
        return

    all_files = iter_torrent_files(info)
    push_to_qbittorrent(
        torrent_path,
        info,
        all_files,
        to_download,
        qb_url=args.qbittorrent_url,
        qb_user=args.qbittorrent_user,
        qb_pass=args.qbittorrent_pass,
        save_path=args.qbittorrent_save_path,
        category=args.qbittorrent_category,
        auto_start=args.qbittorrent_start,
        non_interactive=args.non_interactive,
    )


class _TeeStream:
    """Write to multiple streams simultaneously (used for console + log file)."""

    def __init__(self, *streams: Any) -> None:
        self.streams = streams

    def write(self, data: str) -> int:
        n = 0
        for s in self.streams:
            try:
                n = s.write(data)
            except Exception:
                pass
        return n or 0

    def flush(self) -> None:
        for s in self.streams:
            try:
                s.flush()
            except Exception:
                pass

    def isatty(self) -> bool:
        return any(getattr(s, "isatty", lambda: False)() for s in self.streams)


def _setup_logging(log_dir: str | None, torrent_path: Path) -> Path | None:
    """Tee stdout/stderr into a timestamped log file in log_dir. Returns log path."""
    if not log_dir:
        return None
    log_root = Path(log_dir)
    try:
        log_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"Nie można utworzyć katalogu logów {log_root}: {exc}", file=sys.stderr)
        return None
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_path = log_root / f"{torrent_path.stem}_{ts}.log"
    try:
        fh = open(log_path, "w", encoding="utf-8", buffering=1)
    except OSError as exc:
        print(f"Nie można otworzyć logu {log_path}: {exc}", file=sys.stderr)
        return None
    fh.write(f"# Log uruchomienia: {datetime.now().isoformat()}\n")
    fh.write(f"# Torrent: {torrent_path}\n")
    fh.write(f"# argv:    {' '.join(sys.argv)}\n\n")
    fh.flush()
    sys.stdout = _TeeStream(sys.stdout, fh)
    sys.stderr = _TeeStream(sys.stderr, fh)
    atexit.register(fh.close)
    return log_path


def _apply_ai_parsing(video_files: list[TorrentFile], args: argparse.Namespace) -> bool:
    """Re-parse all video filenames using the LLM module and apply results in place.

    Returns False if the user aborted at the confirmation step.
    """
    try:
        import filename_parser_ai as ai
    except ImportError as exc:
        print(f"Nie mogę zaimportować filename_parser_ai: {exc}", file=sys.stderr)
        return False

    try:
        client = ai.AIClient(
            provider=args.ai_provider,
            base_url=args.ai_base_url,
            api_key=args.ai_api_key,
            model=args.ai_model,
        )
    except RuntimeError as exc:
        print(f"AI: {exc}", file=sys.stderr)
        return False

    cache_dir: Path | None = None
    if not args.ai_no_cache and args.cache_dir:
        cache_dir = Path(args.cache_dir)

    parser_ai = ai.FilenameAIParser(client=client, cache_dir=cache_dir)
    filenames = [tf.name for tf in video_files]
    directories = [tf.directory for tf in video_files]
    batch_size = args.ai_batch_size if args.ai_batch_size > 0 else client.default_batch_size
    dirs_count = sum(1 for d in directories if d)
    dir_note = f" (z czego {dirs_count} w podkatalogach)" if dirs_count else ""
    print(f"\n[AI] Parsuję {len(filenames)} nazw plików{dir_note} przez "
          f"{client.describe()} (batch {batch_size})…")
    try:
        ai_results = parser_ai.parse(
            filenames, directories=directories, batch_size=batch_size, verbose=True
        )
    except RuntimeError as exc:
        print(f"AI parsowanie nieudane: {exc}", file=sys.stderr)
        return False

    if not args.ai_no_confirm and not args.non_interactive and not args.yes:
        if not ai.confirm_groups_interactive(ai_results):
            print("Przerwano przez użytkownika.")
            return False
    else:
        ai.print_groups(ai.group_by_pattern(ai_results))
        ai.print_low_confidence(ai_results)

    for tf, ai_r in zip(video_files, ai_results):
        tf.parsed = ParsedFilename(
            raw=ai_r.filename,
            basename=Path(ai_r.filename).stem,
            title=ai_r.title,
            date=ai_r.date,
            country=ai_r.country,
            category=ai_r.category,
            performer_candidates=_ai_to_variants(ai_r.performers),
        )
    return True


def _ai_to_variants(performers: list[str]) -> list[list[str]]:
    """Build performer_candidates from AI output, with light fallbacks."""
    if not performers:
        return []
    variants: list[list[str]] = [list(performers)]
    if len(performers) == 1:
        name = performers[0]
        tokens = name.split()
        if len(tokens) == 2:
            reversed_name = " ".join(reversed(tokens))
            if reversed_name != name:
                variants.append([reversed_name])
            variants.append(list(tokens))
    return variants


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sprawdź brakujące klipy z torrenta w Stash")
    parser.add_argument("torrent", type=Path, help="Ścieżka do pliku .torrent")
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help=f"Katalog na raporty .txt/.json/.torrent (domyślnie {DEFAULT_OUTPUT_DIR}). "
             "Pusty string '' = obok źródłowego .torrent",
    )
    parser.add_argument(
        "--log-dir",
        default=DEFAULT_LOG_DIR,
        help=f"Katalog na pliki logów (domyślnie {DEFAULT_LOG_DIR}). "
             "Pusty string '' = bez logu na dysk",
    )
    parser.add_argument(
        "--no-log",
        action="store_true",
        help="Wyłącz zapis logów do pliku (tylko konsola)",
    )
    parser.add_argument(
        "--cache-dir",
        default=DEFAULT_CACHE_DIR,
        help=f"Katalog na cache AI parsowania (domyślnie {DEFAULT_CACHE_DIR})",
    )
    parser.add_argument("--studio-id", help="ID studia w Stash (pomija interaktywny wybór)")
    parser.add_argument("--studio-name", help="Wyszukaj studio po nazwie i wybierz pierwsze trafienie")
    parser.add_argument("--stash-url", default=os.environ.get("STASH_URL", "http://localhost:9999"))
    parser.add_argument("--api-key", default=os.environ.get("STASH_API_KEY"))
    parser.add_argument("--dry-run", action="store_true", help="Tylko parsowanie nazw plików, bez Stash")
    parser.add_argument("--yes", "-y", action="store_true", help="Automatycznie zapisz listę brakujących")
    parser.add_argument("--non-interactive", action="store_true", help="Bez pytań (wymaga --studio-id lub --studio-name)")
    parser.add_argument("--limit", type=int, default=0, help="Ogranicz liczbę analizowanych plików (test)")
    size_group = parser.add_mutually_exclusive_group()
    size_group.add_argument(
        "--size-check",
        dest="size_check",
        action="store_true",
        default=None,
        help="Sprawdzaj dopasowanie po rozmiarze pliku (greedy, na grupę aktorów)",
    )
    size_group.add_argument(
        "--no-size-check",
        dest="size_check",
        action="store_false",
        help="Wyłącz sprawdzanie po rozmiarze (sprawdzaj tylko, czy aktor ma scenę w studio)",
    )
    parser.add_argument(
        "--size-tolerance-mb",
        type=float,
        default=2.0,
        help="Maksymalna różnica rozmiaru w MB przy dopasowaniu (domyślnie 2.0)",
    )
    qb_group = parser.add_mutually_exclusive_group()
    qb_group.add_argument(
        "--add-to-qbittorrent",
        dest="add_to_qb",
        action="store_true",
        default=None,
        help="Dodaj torrent do qBittorrent z gotowymi priorytetami plików",
    )
    qb_group.add_argument(
        "--no-add-to-qbittorrent",
        dest="add_to_qb",
        action="store_false",
        help="Nie dodawaj do qBittorrent (tylko pliki .missing.*)",
    )
    parser.add_argument(
        "--qbittorrent-url",
        default=os.environ.get("QB_URL", "http://localhost:8080"),
        help="Web UI qBittorrent (domyślnie http://localhost:8080)",
    )
    parser.add_argument("--qbittorrent-user", default=os.environ.get("QB_USER"))
    parser.add_argument("--qbittorrent-pass", default=os.environ.get("QB_PASS"))
    parser.add_argument("--qbittorrent-save-path", help="Katalog docelowy w qBittorrent")
    parser.add_argument("--qbittorrent-category", help="Kategoria w qBittorrent")
    parser.add_argument(
        "--qbittorrent-start",
        action="store_true",
        help="Po dodaniu od razu wznów (domyślnie pauza, do ręcznego sprawdzenia)",
    )
    unmatched_group = parser.add_mutually_exclusive_group()
    unmatched_group.add_argument(
        "--qbittorrent-include-unmatched",
        dest="qbittorrent_include_unmatched",
        action="store_true",
        default=None,
        help="Dodaj do qBittorrent również pliki nierozpoznane (aktor nieznany w Stash)",
    )
    unmatched_group.add_argument(
        "--qbittorrent-only-missing",
        dest="qbittorrent_include_unmatched",
        action="store_false",
        help="Dodaj do qBittorrent tylko brakujące (domyślne zachowanie)",
    )
    parser.add_argument(
        "--force-subset-torrent",
        action="store_true",
        help="Wygeneruj _missing.torrent / _unmatched.torrent nawet dla v1 bez BEP 47 padding "
             "(boundary-pieces mogą NIE przejść weryfikacji w kliencie - eksperymentalne)",
    )
    parser.add_argument(
        "--use-ai",
        action="store_true",
        help="Użyj LLM do parsowania nazw plików (auto: ollama → groq → openai)",
    )
    parser.add_argument(
        "--ai-provider",
        choices=["auto", "ollama", "groq", "openrouter", "openai"],
        default=None,
        help="Dostawca AI. Domyślnie auto (preferuje DARMOWE: ollama, groq)",
    )
    parser.add_argument("--ai-model", default=None, help="Model (np. qwen2.5:14b, llama-3.3-70b-versatile, gpt-4o-mini)")
    parser.add_argument("--ai-api-key", default=None, help="Klucz API (alt. zmienna środowiskowa)")
    parser.add_argument("--ai-base-url", default=None, help="Endpoint OpenAI-compatible (nadpisuje preset)")
    parser.add_argument(
        "--ai-no-cache", action="store_true", help="Nie używaj lokalnego cache wyników AI"
    )
    parser.add_argument(
        "--ai-no-confirm",
        action="store_true",
        help="Pomiń krok potwierdzenia formatów po parsowaniu",
    )
    parser.add_argument(
        "--ai-batch-size", type=int, default=0,
        help="Ile plików na zapytanie do API (0 = auto, zależnie od dostawcy)",
    )
    return parser.parse_args()


def resolve_size_check(args: argparse.Namespace) -> bool:
    if args.size_check is not None:
        return args.size_check
    if args.non_interactive or args.yes:
        return True
    answer = input(
        "Dopasowywać sceny po rozmiarze pliku (greedy, tolerancja "
        f"{args.size_tolerance_mb:.1f} MB)? [T/n]: "
    ).strip().lower()
    return answer not in {"n", "no", "nie"}


def main() -> int:
    args = parse_args()
    torrent_path = args.torrent
    if not torrent_path.is_file():
        print(f"Nie znaleziono pliku: {torrent_path}", file=sys.stderr)
        return 1

    log_dir = None if args.no_log else (args.log_dir or None)
    log_path = _setup_logging(log_dir, torrent_path)
    if log_path:
        print(f"[log] zapis do {log_path}")

    torrent, info = load_torrent(torrent_path)
    video_files = list_video_files(info)
    if args.limit:
        video_files = video_files[: args.limit]

    print(f"Torrent: {torrent_path.name}")
    print(f"Pliki wideo: {len(video_files)}")
    if torrent_is_v2(info):
        print("Format: BitTorrent v2 (hybrydowy)")
    else:
        print("Format: BitTorrent v1")

    if args.use_ai:
        if not _apply_ai_parsing(video_files, args):
            return 1

    if args.dry_run:
        print("\n--- Parsowanie (dry-run) ---")
        for tf in video_files[:30]:
            p = tf.parsed
            extras: list[str] = []
            if p.date:
                extras.append(f"data: {p.date}")
            if p.category:
                extras.append(f"kategoria: {p.category}")
            if p.title:
                extras.append(f"tytuł: {p.title}")
            if p.country:
                extras.append(f"kraj: {p.country}")
            info = " | " + ", ".join(extras) if extras else ""
            perf = ", ".join(p.performers) if p.performers else "?"
            alt = ""
            if len(p.performer_candidates) > 1:
                alt = "  [warianty: " + " / ".join(
                    ", ".join(v) for v in p.performer_candidates[1:]
                ) + "]"
            dir_prefix = f"{tf.directory}/" if tf.directory else ""
            print(f"  {dir_prefix}{tf.name} -> {perf}{info}{alt}")
        if len(video_files) > 30:
            print(f"  ... i {len(video_files) - 30} więcej")
        return 0

    stash = StashClient(args.stash_url, args.api_key)
    studio = choose_studio(stash, args.studio_name, args.studio_id, args.non_interactive)
    print(f"\nWybrane studio: [{studio['id']}] {studio['name']}")
    print("Ładowanie scen tego studia...")

    performer_index = stash.load_studio_performer_index(studio["id"])
    studio_scenes = stash.load_studio_scenes(studio["id"])
    total_files = sum(len(s.file_sizes) for s in studio_scenes)
    print(
        f"Zindeksowano {len(performer_index)} nazw/aliasów aktorów, "
        f"{len(studio_scenes)} scen i {total_files} plików ze scen."
    )

    size_check = resolve_size_check(args)
    tolerance_bytes = int(args.size_tolerance_mb * 1024 * 1024)
    if size_check:
        print(f"Sprawdzanie rozmiaru: ON (tolerancja {args.size_tolerance_mb:.1f} MB)")
    else:
        print("Sprawdzanie rozmiaru: OFF")

    global_cache: dict[str, dict[str, Any] | None] = {}
    results = analyse_all(
        video_files,
        performer_index,
        studio_scenes,
        stash,
        global_cache,
        size_check,
        tolerance_bytes,
    )

    print_results(results)
    missing = [r for r in results if r.status == "missing"]
    unmatched = [r for r in results if r.status == "unmatched"]
    interactive_export(torrent_path, torrent, info, missing, unmatched, args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

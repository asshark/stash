#!/usr/bin/env python3
"""AI-powered filename parser for porn video torrents.

Sends batches of filenames to an OpenAI-compatible chat-completion endpoint
and asks for structured JSON with: performers, date, title, country.
Caches results on disk so repeated runs are free.

Provider presets (pick with provider= or AI_PARSER_PROVIDER env):

  ollama       (FREE, local)   http://localhost:11434/v1     no key
  groq         (FREE cloud)    https://api.groq.com/openai/v1   GROQ_API_KEY
  openrouter   (FREE models)   https://openrouter.ai/api/v1     OPENROUTER_API_KEY
  openai       (paid)          https://api.openai.com/v1        OPENAI_API_KEY

When no provider is specified, the parser auto-detects in this order:
  1) Ollama if /api/tags responds with at least one installed model
  2) Groq    if GROQ_API_KEY is set
  3) OpenAI  if OPENAI_API_KEY is set
  4) OpenRouter if OPENROUTER_API_KEY is set

Environment overrides (apply regardless of provider):
  AI_PARSER_API_KEY    - explicit API key
  AI_PARSER_BASE_URL   - explicit endpoint
  AI_PARSER_MODEL      - explicit model name
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class AIParsedFilename:
    filename: str
    performers: list[str] = field(default_factory=list)
    date: str | None = None              # YYYY-MM-DD
    title: str | None = None
    country: str | None = None           # ISO 2-3 letter code
    category: str | None = None          # category from parent directory
    pattern_id: str | None = None        # snake_case group identifier
    confidence: float = 0.0              # 0.0-1.0
    notes: str | None = None
    directory: str = ""                  # parent directory passed as context


@dataclass
class FormatGroup:
    pattern_id: str
    items: list[AIParsedFilename]

    @property
    def avg_confidence(self) -> float:
        if not self.items:
            return 0.0
        return sum(it.confidence for it in self.items) / len(self.items)

    @property
    def low_conf_count(self) -> int:
        return sum(1 for it in self.items if it.confidence < 0.7)


# ---------------------------------------------------------------------------
# Knowledge base: canonical examples used as few-shot anchors in the prompt.
# ---------------------------------------------------------------------------

DEFAULT_EXAMPLES: list[dict[str, Any]] = [
    {
        "filename": "Abbie Cat.mp4",
        "performers": ["Abbie Cat"],
        "date": None, "title": None, "country": None,
        "pattern_id": "plain_name",
    },
    {
        "filename": "Abby Lee Brazil 1.mp4",
        "performers": ["Abby Lee Brazil"],
        "date": None, "title": None, "country": None,
        "pattern_id": "plain_name_part_suffix",
    },
    {
        "filename": "Abby Lee Brazil, Joleyn Burst.mp4",
        "performers": ["Abby Lee Brazil", "Joleyn Burst"],
        "date": None, "title": None, "country": None,
        "pattern_id": "two_names_comma",
    },
    {
        "filename": "wunf 307 nanoe vaesen and zaawaadi 2160p.mp4",
        "performers": ["Nanoe Vaesen", "Zaawaadi"],
        "date": None, "title": "wunf 307", "country": None,
        "pattern_id": "studio_code_two_performers",
    },
    {
        "filename": "170702.Nikki-Dikki.mkv",
        "performers": ["Nikki Dikki"],
        "date": "2017-07-02", "title": None, "country": None,
        "pattern_id": "yymmdd_dot_hyphenated_name",
    },
    {
        "filename": "141207.Yekaterin.mkv",
        "performers": ["Yekaterin"],
        "date": "2014-12-07", "title": None, "country": None,
        "pattern_id": "yymmdd_dot_singlename",
    },
    {
        "filename": "Chloe-Amour.[US].mkv",
        "performers": ["Chloe Amour"],
        "date": None, "title": None, "country": "US",
        "pattern_id": "hyphenated_name_country_suffix",
    },
    {
        "filename": "Gina-Gerson-And-Carolina-Abril-Hard-Bed-2-7087.mkv",
        "performers": ["Gina Gerson", "Carolina Abril"],
        "date": None, "title": "Hard Bed 2", "country": None,
        "pattern_id": "two_names_and_title_id",
    },
    {
        "filename": "Aspen-Richardsen-Hard-In-Bed-With-2-Men-8522.mkv",
        "performers": ["Aspen Richardsen"],
        "date": None, "title": "Hard In Bed With 2 Men", "country": None,
        "pattern_id": "name_title_words_id",
    },
    {
        "filename": "Karina-King-Xxxx-Wsg-35-S39002-V30970.mkv",
        "performers": ["Karina King"],
        "date": None, "title": "Xxxx Wsg 35", "country": None,
        "pattern_id": "name_title_sv_codes",
    },
    {
        "filename": "Isabella_Chrystin_-_Hard_-_Chair_1-5189.mkv",
        "performers": ["Isabella Chrystin"],
        "date": None, "title": "Hard - Chair 1", "country": None,
        "pattern_id": "name_underscore_dash_title",
    },
    {
        "filename": "Daniele Orth - I wanted so much a DP.mkv",
        "performers": ["Daniele Orth"],
        "date": None, "title": "I wanted so much a DP", "country": None,
        "pattern_id": "name_dash_title",
    },
    {
        "filename": "[WoodmanCastingX] Aleya Sun - XXXX - An anal for a massage (30.11.2022) rq.mp4",
        "performers": ["Aleya Sun"],
        "date": "2022-11-30",
        "title": "XXXX - An anal for a massage",
        "country": None,
        "pattern_id": "studio_bracket_name_dash_title_date_paren",
    },
    {
        "filename": "WoodmanCastingX - Sandra Blue, Sylvia Buntarka - UPDATED (20.01.2025) rq.mp4",
        "performers": ["Sandra Blue", "Sylvia Buntarka"],
        "date": "2025-01-20",
        "title": "UPDATED",
        "country": None,
        "pattern_id": "studio_name_comma_name_title_date",
    },
]


SYSTEM_PROMPT = """You are an expert filename parser for adult video torrents.

For EACH input (filename + optional directory), extract:

  performers  : list of full performer names in canonical "Firstname Lastname"
                form (Title Case, hyphens between name parts normalized to
                spaces). Order: as they appear in the filename.
  date        : scene release date as "YYYY-MM-DD" if a date can be extracted,
                else null. YY (2-digit) before 31 → 2000+YY, otherwise 1900+YY.
                Accept formats: YYMMDD, YYYYMMDD, YYYY-MM-DD, DD.MM.YYYY.
  title       : scene title (clean of date, code, performer names, trailing
                IDs and resolution markers). null if nothing meaningful left.
  country     : ISO 2-3 letter code if a "[CC]" suffix is present, else null.
  category    : category/section, taken from the parent DIRECTORY name when it
                looks like a section ("Chat", "CSH", "Filme", "BTS", "Updated",
                "WSG", "Casting", "Area X69" etc.). null when directory is
                empty or just a generic container.
  pattern_id  : SHORT snake_case identifier for the filename FORMAT
                (not the specific names). Use the SAME pattern_id for files
                that follow the same overall structure.
  confidence  : 0.0–1.0. Use < 0.7 only when truly ambiguous.
  notes       : short note (≤ 12 words) ONLY if confidence < 0.8 or
                anything is unusual. Else null.

Critical rules:

- The DIRECTORY field is CONTEXT. It is NOT the title and NOT a performer.
  If the filename starts with the directory name as a redundant prefix
  (e.g. dir="Chat", file="chat-adria-..." → effective stem is "adria-..."),
  treat that prefix as already consumed.
- Trailing pure numeric IDs (4+ digits) and `-S\\d+-V\\d+` are NEVER title — drop.
- Resolution markers (1080p, 2160p, 720p, 4K, rq, UHD, ...) are NEVER title.
- A single hyphen between two words (e.g. "Nikki-Dikki") is almost always a
  space inside a single performer's name. A `-And-` (case-insensitive)
  separates TWO performers.
- ` - ` (space-dash-space) and `_-_` separate performer from title.
- "[Studio]" / "Studio - " prefixes are NOT performers and NOT title.
- A bare 6-digit token at the start (e.g. "170702.") is a YYMMDD date.

Output format (STRICT JSON):
  {"results": [<one object per input, in same order>]}

Each object MUST contain exactly the fields listed above. No prose around
the JSON.
"""


# ---------------------------------------------------------------------------
# Provider presets and auto-detection
# ---------------------------------------------------------------------------


PROVIDERS: dict[str, dict[str, Any]] = {
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "default_model": None,  # detected from /api/tags
        "env_key": None,        # no auth needed
        "supports_json_mode": True,
        "free": True,
        "default_batch": 20,
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "default_model": "llama-3.3-70b-versatile",
        "env_key": "GROQ_API_KEY",
        "supports_json_mode": True,
        "free": True,
        "default_batch": 20,   # Groq free tier TPM=12k → ~20 plików mieści się z marginesem
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "default_model": "meta-llama/llama-3.3-70b-instruct:free",
        "env_key": "OPENROUTER_API_KEY",
        "supports_json_mode": True,
        "free": True,  # using a :free model
        "default_batch": 20,
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini",
        "env_key": "OPENAI_API_KEY",
        "supports_json_mode": True,
        "free": False,
        "default_batch": 40,
    },
}


# Best-to-worst preference order when picking an installed Ollama model
OLLAMA_MODEL_PREFERENCES = [
    "qwen2.5:32b", "qwen2.5:14b", "qwen2.5-coder:14b", "qwen2.5:7b",
    "llama3.3:70b", "llama3.1:70b", "llama3.1:8b", "llama3:8b",
    "gemma2:27b", "gemma2:9b",
    "mistral-nemo", "mistral",
    "phi3", "phi3.5",
]


def detect_ollama_models(base_url: str = "http://localhost:11434/v1", timeout: float = 2.0) -> list[str]:
    """Return installed Ollama model names, or [] if Ollama is unreachable."""
    base = base_url.rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    try:
        with urllib.request.urlopen(f"{base}/api/tags", timeout=timeout) as r:
            payload = json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, socket.timeout, ConnectionRefusedError, OSError):
        return []
    except json.JSONDecodeError:
        return []
    return [m.get("name", "") for m in payload.get("models", []) if m.get("name")]


def pick_ollama_model(models: list[str]) -> str | None:
    if not models:
        return None
    for pref in OLLAMA_MODEL_PREFERENCES:
        for m in models:
            if m == pref or m.startswith(pref + ":") or m.startswith(pref):
                return m
    return models[0]


def detect_provider() -> str | None:
    """Try ollama → groq → openai → openrouter, return provider name or None."""
    if detect_ollama_models():
        return "ollama"
    if os.environ.get("GROQ_API_KEY"):
        return "groq"
    if os.environ.get("OPENAI_API_KEY") or os.environ.get("AI_PARSER_API_KEY"):
        return "openai"
    if os.environ.get("OPENROUTER_API_KEY"):
        return "openrouter"
    return None


SETUP_HINTS = {
    "ollama": (
        "Ollama nie odpowiada na localhost:11434.\n"
        "  Pobierz: https://ollama.com/download\n"
        "  Po instalacji uruchom (jednorazowo):\n"
        "    ollama pull qwen2.5:14b   # ~9 GB, świetne do parsowania (zalecane)\n"
        "    ollama pull llama3.1:8b   # ~5 GB, szybsze, mniejsze\n"
        "  Następnie Ollama serwer startuje automatycznie."
    ),
    "groq": (
        "GROQ_API_KEY nie jest ustawiony.\n"
        "  Załóż darmowe konto: https://console.groq.com\n"
        "  Wygeneruj klucz, ustaw zmienną:\n"
        "    PowerShell:  $env:GROQ_API_KEY = 'gsk_...'\n"
        "    cmd:         set GROQ_API_KEY=gsk_...\n"
        "  Free tier jest hojny — kilka tysięcy zapytań/dzień."
    ),
    "openrouter": (
        "OPENROUTER_API_KEY nie jest ustawiony.\n"
        "  Załóż konto: https://openrouter.ai/keys\n"
        "  Modele z sufiksem ':free' są darmowe."
    ),
    "openai": (
        "OPENAI_API_KEY nie jest ustawiony.\n"
        "  OpenAI to opcja PŁATNA. Dla darmowej alternatywy użyj --ai-provider ollama lub groq."
    ),
}


# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------


def _extract_retry_after(message: str) -> int:
    """Parse a sensible sleep time (seconds) from a rate-limit error message."""
    m = re.search(r"try again in (\d+(?:\.\d+)?)\s*([ms])", message, re.IGNORECASE)
    if m:
        value = float(m.group(1))
        if m.group(2).lower() == "m":
            value *= 60
        return max(1, int(value) + 1)
    m = re.search(r"retry[-_ ]after[:=]?\s*(\d+)", message, re.IGNORECASE)
    if m:
        return max(1, int(m.group(1)) + 1)
    m = re.search(r"in (\d+(?:\.\d+)?) seconds?", message, re.IGNORECASE)
    if m:
        return max(1, int(float(m.group(1))) + 1)
    return 30


def _extract_json(text: str) -> dict[str, Any]:
    """Robust JSON extraction (handles markdown fences and trailing prose)."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    start = text.find("{")
    end = text.rfind("}")
    if 0 <= start < end:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass
    raise json.JSONDecodeError("Could not extract JSON object", text, 0)


class AIClient:
    """OpenAI-compatible chat completion client with provider presets.

    Pass provider="ollama" / "groq" / "openrouter" / "openai" to use a preset,
    or override base_url/api_key/model explicitly. Auto-detects if nothing set.
    """

    def __init__(
        self,
        provider: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        # Environment-level overrides take precedence over preset defaults.
        env_base = os.environ.get("AI_PARSER_BASE_URL") or os.environ.get("OPENAI_BASE_URL")
        env_key = os.environ.get("AI_PARSER_API_KEY")
        env_model = os.environ.get("AI_PARSER_MODEL") or os.environ.get("OPENAI_MODEL")
        env_provider = os.environ.get("AI_PARSER_PROVIDER")

        provider = provider or env_provider or detect_provider()

        if provider == "auto":
            provider = detect_provider()

        preset: dict[str, Any] = {}
        if provider and provider in PROVIDERS:
            preset = PROVIDERS[provider]

        self.provider = provider
        self.base_url = (base_url or env_base or preset.get("base_url") or "https://api.openai.com/v1").rstrip("/")

        if not api_key:
            api_key = env_key
            if not api_key and preset.get("env_key"):
                api_key = os.environ.get(preset["env_key"])
        if api_key:
            api_key = api_key.strip().strip('"').strip("'")
        # Some providers (Ollama) don't require auth; send a placeholder so headers work.
        self.api_key = api_key or ("ollama" if provider == "ollama" else None)

        if provider and provider != "ollama" and preset.get("env_key") and not self.api_key:
            hint = SETUP_HINTS.get(provider, "")
            raise RuntimeError(
                f"Brak klucza dla dostawcy '{provider}'.\n{hint}"
            )

        chosen_model = model or env_model or preset.get("default_model")
        if provider == "ollama" and not chosen_model:
            available = detect_ollama_models(self.base_url)
            chosen_model = pick_ollama_model(available)
            if not chosen_model:
                raise RuntimeError(
                    "Ollama działa, ale nie ma żadnych zainstalowanych modeli.\n"
                    "Pobierz model:\n"
                    "  ollama pull qwen2.5:14b  # zalecane do parsowania\n"
                    "  ollama pull llama3.1:8b  # mniejsze i szybsze"
                )

        if not chosen_model:
            chosen_model = "gpt-4o-mini"
        self.model = chosen_model

        if not provider and not self.api_key:
            raise RuntimeError(
                "Nie wykryto żadnego dostawcy AI.\n\n"
                "Wybierz jeden z darmowych:\n"
                "  • Ollama (lokalnie):  https://ollama.com/download\n"
                "    Potem:  ollama pull qwen2.5:14b\n"
                "  • Groq (cloud, free): https://console.groq.com → wygeneruj klucz\n"
                "    Potem:  $env:GROQ_API_KEY = 'gsk_...'\n\n"
                "Następnie uruchom z --use-ai (parser wykryje sam) lub --ai-provider ollama/groq."
            )

        self.supports_json_mode = preset.get("supports_json_mode", True)

    def chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 8000,
        temperature: float = 0.0,
        json_mode: bool = True,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if json_mode and self.supports_json_mode:
            payload["response_format"] = {"type": "json_object"}
        # User-Agent is REQUIRED by some providers behind Cloudflare (e.g. Groq).
        # Without it we get HTTP 403 / error 1010 ("browser signature blocked").
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "torrent-stash-missing/0.1 (urllib)",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
        )
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if exc.code == 403 and "1010" in body:
                raise RuntimeError(
                    f"AI HTTP 403 (Cloudflare error 1010 — Browser signature blocked).\n"
                    f"  Endpoint:  {self.base_url}\n"
                    f"  Provider:  {self.provider}\n"
                    f"  Najpewniej Cloudflare blokuje urllib. Aktualizuj skrypt (User-Agent jest "
                    f"już ustawiony) lub spróbuj innego dostawcy / VPN.\n"
                    f"  Fragment odpowiedzi: {body[:300]}"
                ) from exc
            if exc.code == 429:
                retry_after = exc.headers.get("retry-after") if exc.headers else None
                hint = f" (retry-after: {retry_after}s)" if retry_after else ""
                raise RuntimeError(
                    f"AI HTTP 429 rate_limit{hint}: {body[:400]}"
                ) from exc
            raise RuntimeError(f"AI HTTP {exc.code}: {body[:600]}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"AI nie odpowiada ({self.base_url}): {exc.reason}") from exc
        return data["choices"][0]["message"]["content"]

    @property
    def default_batch_size(self) -> int:
        if self.provider and self.provider in PROVIDERS:
            base = int(PROVIDERS[self.provider].get("default_batch", 40))
        else:
            base = 40
        # Smaller batch for smaller / weaker models — they tend to skip items.
        m = (self.model or "").lower()
        if any(tag in m for tag in (":1b", ":3b", ":4b", "-1b", "-3b", "-4b")):
            return min(base, 5)
        if any(tag in m for tag in (":7b", ":8b", "-7b", "-8b", ".8b")):
            return min(base, 10)
        return base

    def describe(self) -> str:
        provider = self.provider or "custom"
        key_info = ""
        if self.api_key:
            k = self.api_key.strip()
            if len(k) > 12:
                key_info = f" key={k[:4]}…{k[-4:]} (len={len(k)})"
            else:
                key_info = f" key=<{len(k)} chars>"
        return f"{provider}/{self.model} @ {self.base_url}{key_info}"


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def _examples_block(examples: list[dict[str, Any]]) -> str:
    return "\n".join(json.dumps(ex, ensure_ascii=False) for ex in examples)


class FilenameAIParser:
    def __init__(
        self,
        client: AIClient | None = None,
        examples: list[dict[str, Any]] | None = None,
        cache_dir: Path | None = None,
    ) -> None:
        self.client = client or AIClient()
        self.examples = examples if examples is not None else DEFAULT_EXAMPLES
        self.cache_dir = cache_dir
        if cache_dir is not None:
            cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_key(self, items: list[tuple[str, str]]) -> str:
        h = hashlib.sha256()
        h.update(self.client.model.encode("utf-8"))
        h.update(b"\n--examples--\n")
        for ex in self.examples:
            h.update(json.dumps(ex, sort_keys=True).encode("utf-8"))
        h.update(b"\n--files--\n")
        for fn, d in items:
            h.update(fn.encode("utf-8"))
            h.update(b"\t")
            h.update(d.encode("utf-8"))
            h.update(b"\n")
        return h.hexdigest()

    def _cache_get(self, key: str, verbose: bool = False) -> list[AIParsedFilename] | None:
        if self.cache_dir is None:
            return None
        path = self.cache_dir / f"{key}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return [AIParsedFilename(**row) for row in data]
        except Exception as exc:
            if verbose:
                print(f"[AI] Cache niezdatny do odczytu {path.name}: {exc}")
            return None

    def _cache_put(self, key: str, results: list[AIParsedFilename]) -> None:
        if self.cache_dir is None:
            return
        path = self.cache_dir / f"{key}.json"
        path.write_text(
            json.dumps([asdict(r) for r in results], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def parse(
        self,
        filenames: list[str],
        directories: list[str] | None = None,
        batch_size: int = 40,
        verbose: bool = True,
    ) -> list[AIParsedFilename]:
        if not filenames:
            return []

        if directories is None:
            directories = [""] * len(filenames)
        if len(directories) != len(filenames):
            raise ValueError("directories must match filenames length")

        items = list(zip(filenames, directories))
        full_key = self._cache_key(items)
        full_path = self.cache_dir / f"{full_key}.json" if self.cache_dir else None
        total_batches = (len(items) + batch_size - 1) // batch_size

        if verbose and self.cache_dir:
            cached_count = 0
            try:
                cached_count = sum(1 for _ in self.cache_dir.glob("*.json"))
            except OSError:
                pass
            print(f"[AI] Cache:        {self.cache_dir}")
            print(f"[AI] Full-list key: {full_key[:16]}…  ({'HIT' if (full_path and full_path.exists()) else 'MISS'}, w cache: {cached_count} plików)")

        cached = self._cache_get(full_key, verbose=verbose)
        if cached is not None:
            if verbose:
                print(f"[AI] Cache hit dla {len(filenames)} plików — 0 zapytań do API.")
            return cached

        # Pre-pass: count how many batches will hit cache (so user sees the plan).
        if verbose and self.cache_dir:
            preview_hits = 0
            for start in range(0, len(items), batch_size):
                batch_items = items[start:start + batch_size]
                batch_key = self._cache_key(batch_items)
                if (self.cache_dir / f"{batch_key}.json").exists():
                    preview_hits += 1
            print(f"[AI] Plan:         {total_batches} batches → {preview_hits} z cache, "
                  f"{total_batches - preview_hits} do API")

        results: list[AIParsedFilename] = []
        hits = 0
        misses = 0
        last_completed_batch = 0
        try:
            for batch_idx, start in enumerate(range(0, len(items), batch_size), start=1):
                batch_items = items[start:start + batch_size]
                batch_key = self._cache_key(batch_items)
                batch_cached = self._cache_get(batch_key, verbose=verbose)
                if batch_cached is not None:
                    if verbose:
                        print(f"[AI] batch {batch_idx}/{total_batches}: cache hit ({len(batch_items)})")
                    results.extend(batch_cached)
                    hits += 1
                    last_completed_batch = batch_idx
                    continue
                if verbose:
                    print(f"[AI] batch {batch_idx}/{total_batches}: {len(batch_items)} plików → {self.client.model}…")
                batch_results = self._parse_one_batch(batch_items, verbose=verbose)
                self._cache_put(batch_key, batch_results)
                results.extend(batch_results)
                misses += 1
                last_completed_batch = batch_idx
        finally:
            if verbose:
                done = hits + misses
                print(
                    f"[AI] Status:       {done}/{total_batches} batches done "
                    f"(z cache: {hits}, z API: {misses}, ostatni ukończony: #{last_completed_batch})"
                )

        # Save the full-list cache only if EVERY batch is now represented.
        self._cache_put(full_key, results)
        if verbose:
            print(f"[AI] Full-list cache zapisany: {full_path.name if full_path else '(no dir)'}")
        return results

    def _make_placeholder(self, filename: str, directory: str) -> AIParsedFilename:
        """Result for files we couldn't get from the LLM after retries."""
        return AIParsedFilename(
            filename=filename,
            directory=directory,
            performers=[],
            date=None,
            title=None,
            country=None,
            category=None,
            pattern_id="unknown",
            confidence=0.0,
            notes="AI nie zwrócił wyniku po retry — placeholder",
        )

    def _row_to_parsed(
        self, filename: str, directory: str, row: dict[str, Any]
    ) -> AIParsedFilename:
        return AIParsedFilename(
            filename=filename,
            directory=directory,
            performers=list(row.get("performers") or []),
            date=row.get("date") or None,
            title=row.get("title") or None,
            country=(row.get("country") or None),
            category=(row.get("category") or None),
            pattern_id=row.get("pattern_id") or None,
            confidence=float(row.get("confidence") or 0.5),
            notes=row.get("notes") or None,
        )

    def _parse_one_batch(
        self,
        items: list[tuple[str, str]],
        retries: int = 2,
        depth: int = 0,
        verbose: bool = True,
    ) -> list[AIParsedFilename]:
        examples_text = _examples_block(self.examples)
        numbered_lines = []
        for i, (fn, d) in enumerate(items, start=1):
            if d:
                numbered_lines.append(f'{i}. dir="{d}"  file="{fn}"')
            else:
                numbered_lines.append(f'{i}. file="{fn}"')
        numbered = "\n".join(numbered_lines)
        user_msg = (
            f"Reference examples (canonical parses, treat as ground truth):\n"
            f"{examples_text}\n\n"
            f"Now parse these {len(items)} entries. Each line is a separate file; "
            f'"dir" (if present) is the parent directory context — use it for "category" '
            f'and to detect redundant prefix in the filename, but do not mix it into '
            f"title/performers.\n{numbered}\n\n"
            f'Return JSON: {{"results": [<obj>, ...]}} — exactly one object per '
            f"input, in the SAME order."
        )

        # ~150 tokens per filename for a typical compact JSON result (with margin).
        # Lower than before to stay under Groq free tier TPM=12k.
        max_tokens = min(8000, max(800, len(items) * 150))

        response: str | None = None
        last_err: Exception | None = None
        for attempt in range(retries + 1):
            try:
                response = self.client.chat(
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_msg},
                    ],
                    max_tokens=max_tokens,
                )
                break
            except RuntimeError as exc:
                last_err = exc
                msg = str(exc).lower()
                is_rate = (
                    "429" in str(exc)
                    or "rate_limit" in msg
                    or "tokens per minute" in msg
                    or "tpm" in msg
                )
                if is_rate and attempt < retries:
                    sleep_s = _extract_retry_after(str(exc))
                    print(f"[AI] Rate limit, czekam {sleep_s}s przed ponowieniem "
                          f"({attempt + 1}/{retries})…")
                    time.sleep(sleep_s)
                    continue
                raise
        if response is None:
            raise last_err or RuntimeError("AI chat failed without error")

        try:
            data = _extract_json(response)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"AI zwróciło niepoprawny JSON: {exc}\nFragment odpowiedzi:\n{response[:600]}"
            ) from exc

        rows = data.get("results")
        if not isinstance(rows, list):
            raise RuntimeError(f"AI nie zwróciło 'results' jako listy. Odpowiedź:\n{response[:600]}")

        # If the count matches and the input was small, accept by position.
        if len(rows) == len(items):
            out: list[AIParsedFilename] = []
            for (fn, d), row in zip(items, rows):
                row = row if isinstance(row, dict) else {}
                out.append(self._row_to_parsed(fn, d, row))
            return out

        # Count mismatch — typical with smaller models (8B sometimes drops items).
        # Strategy: match returned rows by filename, then retry only the missing
        # items in a smaller batch. Recurse up to depth 4, then give up with
        # placeholder results so the rest of the pipeline keeps going.
        rows_by_fn: dict[str, dict[str, Any]] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            fn = row.get("filename")
            if isinstance(fn, str) and fn:
                rows_by_fn[fn] = row

        matched_indices: set[int] = set()
        out_slots: list[AIParsedFilename | None] = [None] * len(items)
        for idx, (fn, d) in enumerate(items):
            row = rows_by_fn.get(fn)
            if row is not None:
                out_slots[idx] = self._row_to_parsed(fn, d, row)
                matched_indices.add(idx)

        missing_indices = [i for i in range(len(items)) if i not in matched_indices]
        if verbose:
            print(
                f"[AI]   count mismatch: dostałem {len(rows)}/{len(items)}, "
                f"dopasowane po nazwie: {len(matched_indices)}, brakuje: {len(missing_indices)}"
            )

        if not missing_indices:
            return [s for s in out_slots if s is not None]

        if depth >= 4:
            if verbose:
                print(f"[AI]   max retry depth reached, {len(missing_indices)} placeholders.")
            for idx in missing_indices:
                fn, d = items[idx]
                out_slots[idx] = self._make_placeholder(fn, d)
            return [s if s is not None else self._make_placeholder(*items[i])
                    for i, s in enumerate(out_slots)]

        # Retry missing items in halved chunks.
        missing_items = [items[i] for i in missing_indices]
        chunk_size = max(1, len(missing_items) // 2)
        if chunk_size == len(missing_items) and chunk_size > 1:
            chunk_size = max(1, chunk_size // 2)
        if verbose:
            print(f"[AI]   retry: dzielę {len(missing_items)} brakujących na porcje po {chunk_size}…")

        retry_results: list[AIParsedFilename] = []
        for start in range(0, len(missing_items), chunk_size):
            sub = missing_items[start:start + chunk_size]
            retry_results.extend(self._parse_one_batch(sub, retries=retries, depth=depth + 1, verbose=verbose))

        for idx, result in zip(missing_indices, retry_results):
            out_slots[idx] = result

        # Final pass — fill any remaining None with placeholder (defensive).
        return [s if s is not None else self._make_placeholder(*items[i])
                for i, s in enumerate(out_slots)]


# ---------------------------------------------------------------------------
# Grouping + UI
# ---------------------------------------------------------------------------


def group_by_pattern(parsed: list[AIParsedFilename]) -> list[FormatGroup]:
    by_pattern: dict[str, list[AIParsedFilename]] = {}
    for p in parsed:
        pid = p.pattern_id or "unknown"
        by_pattern.setdefault(pid, []).append(p)
    return [
        FormatGroup(pattern_id=pid, items=items)
        for pid, items in sorted(by_pattern.items(), key=lambda kv: -len(kv[1]))
    ]


def _render_extras(item: AIParsedFilename) -> str:
    bits = []
    if item.date:
        bits.append(f"data={item.date}")
    if item.category:
        bits.append(f"kategoria={item.category}")
    if item.title:
        bits.append(f"title={item.title!r}")
    if item.country:
        bits.append(f"kraj={item.country}")
    if item.directory:
        bits.append(f"dir={item.directory!r}")
    return " | " + ", ".join(bits) if bits else ""


def print_groups(groups: list[FormatGroup], samples_per_group: int = 3) -> None:
    print(f"\n=== Wykryte formaty plików ({len(groups)}) ===")
    for i, g in enumerate(groups, start=1):
        print(
            f"  [{i}] {g.pattern_id:42s} "
            f"{len(g.items):>4} plików | conf śr.={g.avg_confidence:.2f} "
            f"| niskich={g.low_conf_count}"
        )
        for item in g.items[:samples_per_group]:
            perfs = ", ".join(item.performers) or "?"
            print(f"        {item.filename}")
            print(f"           → {perfs}{_render_extras(item)}")
        if len(g.items) > samples_per_group:
            print(f"        … i {len(g.items) - samples_per_group} więcej")


def print_low_confidence(
    parsed: list[AIParsedFilename],
    threshold: float = 0.7,
    limit: int = 30,
) -> int:
    low = [p for p in parsed if p.confidence < threshold]
    if not low:
        return 0
    print(f"\n--- {len(low)} wyników o niskiej pewności (conf < {threshold}) ---")
    for p in low[:limit]:
        perfs = ", ".join(p.performers) or "?"
        note = f" — {p.notes}" if p.notes else ""
        print(f"  ({p.confidence:.2f}) [{p.pattern_id}] {p.filename}")
        print(f"        → {perfs}{_render_extras(p)}{note}")
    if len(low) > limit:
        print(f"  … i {len(low) - limit} więcej")
    return len(low)


def confirm_groups_interactive(
    parsed: list[AIParsedFilename],
    low_conf_threshold: float = 0.7,
) -> bool:
    """Show groups and low-confidence items, then ask user to confirm.

    Returns True to continue, False to abort.
    """
    groups = group_by_pattern(parsed)
    print_groups(groups)
    print_low_confidence(parsed, threshold=low_conf_threshold)
    ans = input(
        "\nKontynuować z tym parsowaniem? "
        "[T]ak / [n]ie / [p]okaż wszystkie / [d]ump-do-jsona: "
    ).strip().lower()
    if ans in {"p", "pokaz", "pokaż", "show"}:
        for g in groups:
            print(f"\n>>> {g.pattern_id} ({len(g.items)})")
            for item in g.items:
                perfs = ", ".join(item.performers) or "?"
                print(f"  ({item.confidence:.2f}) {item.filename}")
                print(f"       → {perfs}{_render_extras(item)}")
        ans = input("\nKontynuować? [T/n]: ").strip().lower()
    if ans in {"d", "dump", "json"}:
        out_path = Path("ai_parse_dump.json")
        out_path.write_text(
            json.dumps([asdict(p) for p in parsed], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"Zapisano: {out_path.resolve()}")
        ans = input("Kontynuować? [T/n]: ").strip().lower()
    return ans not in {"n", "no", "nie"}


# ---------------------------------------------------------------------------
# Self-test (no API call)
# ---------------------------------------------------------------------------


def _self_test() -> None:
    print("AIParsedFilename pola:", list(AIParsedFilename.__annotations__))
    print("FormatGroup pola:    ", list(FormatGroup.__annotations__))
    print("System prompt rozmiar:", len(SYSTEM_PROMPT), "znaków")
    print("Liczba przykładów:   ", len(DEFAULT_EXAMPLES))


def _diagnose() -> int:
    """Print which providers are reachable / configured."""
    print("=== Diagnostyka dostawców AI ===\n")

    ollama_models = detect_ollama_models()
    if ollama_models:
        chosen = pick_ollama_model(ollama_models)
        print(f"[OK] Ollama   działa, {len(ollama_models)} modeli, wybiorę: {chosen}")
        print(f"     Dostępne: {', '.join(ollama_models[:8])}"
              + (" …" if len(ollama_models) > 8 else ""))
    else:
        print("[--] Ollama   nie odpowiada (http://localhost:11434)")
        print("     Pobierz: https://ollama.com/download")
        print("     Potem:   ollama pull qwen2.5:14b")
    print()

    for name in ("groq", "openrouter", "openai"):
        preset = PROVIDERS[name]
        env_key = preset["env_key"]
        has_key = bool(env_key and os.environ.get(env_key))
        status = "[OK]" if has_key else "[--]"
        free = " (FREE)" if preset["free"] else " (PAID)"
        line = f"{status} {name:10s} klucz {env_key:20s} = {'ustawiony' if has_key else 'brak'}{free}"
        print(line)
        if not has_key:
            hint = SETUP_HINTS.get(name, "").splitlines()
            for h in hint:
                print(f"     {h}")
        else:
            print(f"     model default: {preset['default_model']}")
        print()

    detected = detect_provider()
    print("Auto-detected provider:", detected or "brak (skonfiguruj coś)")
    return 0 if detected else 1


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        _self_test()
    elif "--diagnose" in sys.argv or "--check" in sys.argv:
        sys.exit(_diagnose())
    else:
        print("Ten moduł nie jest CLI. Importuj go z torrent_stash_missing.py.")
        print("Diagnostyka dostawców:  python filename_parser_ai.py --diagnose")

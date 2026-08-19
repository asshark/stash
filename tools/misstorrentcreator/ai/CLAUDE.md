# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this directory.

## What this is

`tools/misstorrentcreator/ai/` hosts two Claude Code **Skills** — `/misstudio`
and `/misstar` — plus their shared backend `miss_core.py`. Both compare a
`.torrent` file's video contents against the local Stash media library and
help the user (arek-shark) build a torrent (or a qBittorrent selection)
containing only the scenes that are still missing:

- **`/misstudio`** — scope is a single **Studio**. Ask for the studio name
  and a torrent path, find which files in the torrent already exist as
  scenes of that studio in Stash, produce a missing-only torrent/selection.
- **`/misstar`** — same thing, but scope is a single **performer/Actor**
  across the whole Stash library (not limited to one studio).

Skill instructions live at `.claude/skills/misstudio/SKILL.md` and
`.claude/skills/misstar/SKILL.md` — read those for the exact step-by-step
workflow each skill follows. This file covers architecture, the decisions
behind it, and things a future session must not silently change.

## Relationship to `tools/misstorrentcreator/torrent_stash_missing.py`

The parent directory already has a mature 1900-line CLI
(`torrent_stash_missing.py`) that does almost this exact thing, but
**studio-scoped only** (no performer mode), with its own regex/AI filename
parser (`filename_parser_ai.py`, providers: Ollama/Groq/OpenAI/OpenRouter).

**This project is a deliberately separate, independent implementation** —
`miss_core.py` does **not** modify `torrent_stash_missing.py` and does not
call its `StashClient`, filename parser, or CLI. It only imports these
proven **low-level bencode/qBittorrent primitives** (read-only):

```python
from torrent_stash_missing import (
    QBittorrentClient, QBittorrentError,
    bencode_decode, bencode_encode,
    create_v1_subset_torrent_with_padding,
    info_hashes, is_bep47_padded, iter_torrent_files,
    load_torrent, torrent_has_v1_data, torrent_is_v2,
)
```

Everything else — the Stash GraphQL client, performer-name resolution,
studio-vs-performer scope matching, the qBittorrent push orchestration, and
the CLI itself — is new code in `miss_core.py`. If you're tempted to reuse
more of `torrent_stash_missing.py` (e.g. its `StashClient`, `parse_filename`,
`analyse_all`), don't — that was an explicit choice (see "Why a separate
implementation" below), not an oversight.

Filename → performer/date/title extraction, which `torrent_stash_missing.py`
does via regex (`parse_filename`) or an external OpenAI-compatible LLM
(`filename_parser_ai.py`), is instead done by **a Claude subagent using
`model: "fable"`**, invoked directly by the skill (see SKILL.md files). No
external API key, no Groq/Ollama/OpenAI — the parsing happens inside the
Claude Code session itself.

### Why a separate implementation (context for future changes)

This was an explicit user decision, not the default/obvious choice — worth
preserving so nobody "fixes" it back into one shared codebase without
asking:

- The two skills are meant to be self-contained and driven conversationally
  by Claude (ask → parse via Fable → confirm with user → match → build),
  not by CLI flags — a fundamentally different interaction model than
  `torrent_stash_missing.py`'s argparse-driven, mostly-non-interactive CLI.
- Reusing only the **mechanical, correctness-critical, already-debugged**
  parts (bencode encode/decode, BEP 47 padding math, the qBittorrent Web
  API client) avoids re-deriving tricky binary-format code, while keeping
  the Stash-matching logic (which had to change shape anyway — see
  "Performer scope semantics" below) free to diverge without needing to
  keep two call sites of a shared `StashClient`/`analyse_all` in sync.

## `miss_core.py` CLI contract

Full request/response JSON shapes are documented in the module's own
docstring (`tools/misstorrentcreator/ai/miss_core.py`, top of file) — read
that before changing the CLI. Summary of subcommands:

| Subcommand | Purpose |
|---|---|
| `list-studios --query TEXT` | Search Stash studios |
| `list-performers --query TEXT` | Search Stash performers (name + alias_list) |
| `list-files <torrent>` | List video files in a `.torrent` (bencode), plus what got skipped as non-video |
| `match --scope {studio,performer} --scope-id ID --parsed <json>` | Given AI-parsed filenames, decide present/missing/unmatched/skipped against Stash |
| `build-torrent <torrent> --missing <json> --out <path>` | Build a v1 subset torrent (BEP 47 padding) containing only the missing files |
| `qbittorrent-push <torrent> --missing <json>` | Add the full torrent to qBittorrent (paused), set file priority 0 on everything except the missing files |

All output is JSON on stdout; run from `tools/misstorrentcreator/ai/` (it
inserts the parent directory onto `sys.path` itself to find
`torrent_stash_missing.py`, no `PYTHONPATH` setup needed).

## Performer scope semantics (the non-obvious rule)

For `/misstar`, the target performer is **always** added to the
performer-ID set used for matching, regardless of whether their name shows
up in the filename text — because the user (arek-shark) confirmed, after
reviewing the `Stars/` examples, that torrents named after one performer
frequently don't repeat that performer's name in every filename (e.g. an
`[Studio] - date title.mp4` mega-pack, or filenames that only show
co-stars). Fable's job is pure text extraction (it must NOT assume the
target performer is present just because they weren't named); `miss_core.py
match` is what adds `scope_id` to the matched-ID set when `--scope
performer` is used. See `resolve_for_file`-equivalent logic in
`cmd_match()`.

For `/misstudio`, there is no such auto-add — the studio doesn't imply any
specific performer, so the matched-ID set is exactly whatever Fable
extracted from the filename.

## Scope: video files only (v1 limitation, deliberate)

`miss_core.py list-files` only returns files whose extension is in
`VIDEO_EXTENSIONS` (`.mp4 .mkv .avi .wmv .mov .m4v .webm .mpg .mpeg`).
Everything else — image galleries (`.zip`, seen in the `Kyler Quinn`
example, which map to Stash **Galleries** not Scenes) and preview
screenshots (`.jpg` under a `Screens/` folder, seen in the `Sandra Soul`
example) — is reported separately as `skipped_non_video` and is **never**
analyzed or included in "missing" output.

This was confirmed explicitly with the user after finding these file types
in the `Stars/` examples; it's a starting-point simplification, not a bug.
If gallery matching (`.zip` → Stash `findGalleries`) is wanted later, it
needs a new `StashClient.load_studio_galleries`/`load_performer_galleries`
method and a second code path in `cmd_match` — ask before building it, since
it changes the output shape.

## Matching algorithm (also a v1 limitation, deliberate)

`cmd_match()` matches by **(parsed performer-ID set) ⊆ (scene's
performer-ID set)** plus **date compatibility** (a file with no parsed date
matches any scene; a file with a date only matches scenes with no date or
the same date). It does **not** do `torrent_stash_missing.py`'s greedy
file-size-based pairing (`--size-check`), which exists there to
disambiguate multi-part re-encodes of the same scene (e.g. "Abby Lee Brazil
1.mp4" / "2.mp4"). If that turns out to be needed here too, add it as an
opt-in refinement to `cmd_match` — don't silently change the default
behavior other sessions may already rely on.

**Studio and title are soft signals, not hard filters** (added after the
`Leo Ahsoka.torrent` example showed filenames like `ClubSweethearts - Back
To School.mp4`, where the studio name is embedded next to the scene title).
`match --parsed` entries may carry `studio_hint` — text the fable subagent
extracted after cross-referencing a `list-studios` dump (see
`.claude/skills/misstar/SKILL.md` step 4/5) and stripped out of `title`.
`cmd_match()` resolves `studio_hint` to a Stash studio (exact name/alias,
case-insensitive, via `resolve_studio_names()` — mirrors
`resolve_performer_names()`) and, among the performer+date candidates,
**prefers** the one(s) whose `studio_id` matches. If none match, it does
**not** automatically fail the match — Stash scenes aren't always
studio-tagged — but it also does **not** blindly fall back to "the first
candidate" the way the pre-studio code did. It only still trusts the
unfiltered candidate set when something else disambiguates it: exactly one
candidate, an exact date hit, or a `title_similar()` match; in that case it
proceeds as `present` with a `[uwaga: plik wskazuje na studio ... ale
dopasowana scena ma studio: ...]` note in `detail` for the human to check in
SKILL.md step 8. **If none of those hold — multiple same-performer
candidates, no date, no title match, and a resolved studio that matches
none of them — the file is reported `missing`, not a guessed `present`.**

This distinction was found the hard way on the first live run against
`Leo Ahsoka.torrent`, in two stages:

1. First cut: "studio mismatch → fall back to `compatible[0]`" silently
   matched 24 unrelated files (BangBros, DorcelClub, Perfect18, PornBox,
   Vixen, ...) to the *same* single scene ("Dirty Assistant" / Her Limit),
   because with `file_date=None`, `date_compatible()` accepts every scene
   of that performer, and `pool[0]` is deterministic-but-arbitrary.
2. Fixing only the studio-mismatch branch wasn't enough: files whose
   `studio_hint` was simply `null` (never resolved a studio at all —
   `Double Please`, `Futanari`, `Nubiles`, `Rocco's Perverted Secretaries`,
   and the `NRX-Studio` files once the user chose to blank their hint) hit
   the exact same `pool[0]` guess through the *original*, studio-unaware
   code path.

**Studio is now a hard filter, not a soft preference** (changed again in
the same session, per explicit user direction after reviewing the
`BangBros - Jadilica Maid For Anal.mp4` case: Stash had a title-exact match
for it, but tagged under studio "My Dirty Maid", not "BangBros" — the user
said a title match must NOT override a *known* studio mismatch, the file
should still count as missing). `date_compatible()` already worked this
way — known-and-different disqualifies, unknown-on-either-side doesn't —
and studio now mirrors it exactly: when `studio_hint` resolves to a real
Stash studio, `pool` is filtered to only scenes with that `studio_id`; if
that empties the pool, the file falls straight through to `missing`
(`detail` says the studio didn't match; no candidate count/date/title
tie-break rescue like the ambiguous-pool case gets, because studio mismatch
here is *positive* evidence, not merely a lack of a signal). This is
narrower than "soft signal, never a filter that can turn present into
missing" stated in older commentary in this file — that description is
superseded for studio specifically. Only when `studio_hint` doesn't resolve
at all (no signal either way) does the pool stay unfiltered and get the
len==1/date/title disambiguation described below. Don't quietly reintroduce
a title-rescue path for studio mismatches without checking with the user
again — it was explicitly rejected once already.

So the rule in `cmd_match()` is now **general, not studio-specific**:
whichever `pool` you end up with (the full performer+date `compatible`
set, or a studio-narrowed subset of it), only pick a `best` scene when
something disambiguates it — `len(pool) == 1`, an exact date hit, or a
`title_similar()` hit. If none apply, `best` stays `None` and the file
falls through to `missing` (worded as "N scen bez rozstrzygającej
daty/tytułu — za mało sygnału"), never a guessed `present`. A false
`present` is worse here than a false `missing`: the former silently drops
content the user doesn't actually have, the latter just costs a manual
look in step 8. Don't reintroduce a bare `pool[0]` fallback anywhere in
this function without re-solving that failure mode.

**Cross-file scene-collision dedup** (added right after the above, same
`Leo Ahsoka.torrent` session): trusting `len(pool) == 1` is a per-file
decision — it can't see that *another* file in the same run already
"claimed" the same single scene via the same studio narrowing. Live
example: Leo Ahsoka has exactly one "Asshole Fever" scene in Stash
("Backdoor Delight"), so both `AssholeFever - Backdoor Delight.mp4` *and*
`AssholeFever - Let's Skip Dinner.mp4` independently narrowed to it and
both got called `present` — but only the former's title actually matches.
`cmd_match()` now runs a dedup pass after the main loop: group all
`present` results by `matched_scene["scene_id"]`; for any group with more
than one file, keep `present` only on the member whose file `title`
`title_similar()`-matches the scene's title (if exactly one does),
otherwise **downgrade every member of the group to `missing`** — a shared
scene with no title winner is exactly the "coin flip" situation the
`len(pool)==1` check was supposed to prevent, so don't let it slip back in
through a cross-file gap. This still doesn't replace real file-size-based
dedup (see the "Matching algorithm" limitation above) for the case where a
performer genuinely has *multiple* scenes at a studio and several torrent
files title-match none of them well — that residual ambiguity still needs
a human look in SKILL.md step 8, but it's no longer silently mislabeled
`present`.

`title` is used only as a tie-breaker (`title_similar()`, normalized
substring match) for choosing among multiple candidates that already
passed the (hard) studio and date filters. It cannot rescue a *known*
studio or date mismatch — see below, that path was explicitly removed.

## Example torrents (`Studios/`, `Stars/`)

Real, previously-owned `.torrent` files the user dropped in as test/analysis
fixtures — **not synthetic examples**, and not something to delete/move.
Used to design the Fable prompt in each SKILL.md (see the pattern tables
there). Notable ones, if you need to re-derive filename patterns:

- `Studios/AngeloGodshackXXX...` — `(CODE) Studio-style-title FirstName
  LastName and FirstName2 LastName2 ...mp4`, multi-performer, no date.
- `Studios/WakeUpNFuck...` — `wunf <episode> <performer> <resolution>.mp4`,
  single performer, studio-code prefix, no date.
- `Studios/WoodmanCastingX...` — `FirstName LastName.[CC].mkv`, single
  performer, ISO country-code suffix instead of date.
- `Stars/Ariana Marie MegaPack...` — `[Studio] - YYYY.MM.DD Title
  Resolution.ext`, multi-studio, **performer name absent from every
  filename** (see "Performer scope semantics" above).
- `Stars/Chris_Diamond_huge_pack...` — `CODE_FirstName_LastName_Quality.mp4`,
  underscore-separated, filename shows **co-stars, not the target
  performer**.
- `Stars/Kyler Quinn...` — per-studio subfolders, `.zip` galleries with
  `(Performer & Performer2)` in the name — skipped as non-video (see scope
  section above).
- `Stars/Sandra Soul...` — mixed torrent: real scenes under `Videos/`
  (`Studio - Title.mp4`, no performer, no date) alongside preview
  screenshots under `Screens/` (`Studio - Title.mp4.jpg`) — the `.jpg`
  files are correctly filtered out by `list-files`.

## Environment

Same conventions as `torrent_stash_missing.py` for consistency:

- `STASH_URL` (default `http://localhost:9999`), `STASH_API_KEY` — Stash
  GraphQL endpoint/auth.
- `QB_URL` (default `http://localhost:8080`), `QB_USER`, `QB_PASS` —
  qBittorrent Web UI.

## Testing status

`miss_core.py list-files` has been smoke-tested against all seven example
torrents in `Studios/`/`Stars/` (video/non-video split confirmed correct).
`list-studios`, `list-performers`, `match`, `build-torrent`, and
`qbittorrent-push` have **not** been exercised against a live Stash/
qBittorrent instance yet — the GraphQL query shapes mirror
`torrent_stash_missing.py`'s already-working queries, but the first real run
of each skill should be treated as the first real test of that code path.

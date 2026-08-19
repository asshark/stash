# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`docs/sswiki` is a **generated, agent-searchable knowledge base** in Open Knowledge Format (OKF v0.2), built from a native JSON export of a local [Stash](https://github.com/stashapp/stash) instance (adult media library manager). It contains one Markdown file per entity — performer, scene, tag, studio, group, gallery — with YAML front matter and Markdown links to related entities.

This directory is **not application source code**. There is no build, lint, or test suite here; the only code is the single generator script.

## Regenerating the knowledge base

```
python scripts/stash_export_to_okf.py --export-dir <path-to-stash-metadata-export> --out .
```

- `--export-dir` is Stash's native "metadata" export path (Settings > Tasks > Export; see `config.yml -> metadata`), containing one subfolder of JSON files per entity type: `performers/`, `scenes/`, `tags/`, `studios/`, `movies/` (exported as `groups/` here), `galleries/`, `images/`.
- `--out` is the OKF bundle root (defaults to the current directory, i.e. `docs/sswiki` itself).
- The script is **idempotent and destructive per-subdirectory**: each concept folder (`performers/`, `scenes/`, `tags/`, `studios/`, `groups/`, `galleries/`) is fully deleted and rewritten on every run via `reset_dir()`. `index.md` is also fully regenerated with fresh counts.
- `log.md` is the one file that accumulates across runs: `write_log()` reads the existing file and **prepends** a dated entry (grouping same-day reruns under one `## <date>` heading, newest date first) rather than overwriting it, so regeneration history is preserved.
- **Never hand-edit files under `performers/`, `scenes/`, `tags/`, `studios/`, `groups/`, or `galleries/`** — any manual change is silently discarded the next time the script runs. `index.md` states this explicitly.

## Architecture of the generator (`scripts/stash_export_to_okf.py`)

The script runs in three phases:

1. **Slug assignment** (`assign_performers`, `assign_tags`, `assign_studios`, `assign_groups`, `assign_galleries`, `assign_scenes`): each entity gets a filesystem-safe slug (via `slugify` + `unique_slug`, disambiguating collisions by appending `-2`, `-3`, ...). Each `assign_*` function also builds a `NameIndex`, which maps an entity's display name back to its slug(s) — this is how later phases resolve cross-references (Stash JSON stores relations by name, not ID).
2. **Reverse index construction** (`build_reverse_indices`): scans scene/performer/studio/group/gallery records to build reverse lookups not present directly in the source data — e.g. which scenes a performer appears in (`performer_scenes`), which scenes belong to a group in order (`group_scenes`), and usage counts for tags/studios across all entity types (`tag_usage`, `studio_usage`).
3. **Writers** (`write_performers`, `write_tags`, `write_studios`, `write_groups`, `write_galleries`, `write_scenes`, `write_root`): one function per entity type, each producing YAML front matter (`type`, `title`, denormalized fields like `tags`/`scene_count` for fast filtering without opening the file) plus a Markdown body with attribute tables and `## <Heading>` link sections (aliases, tags, related scenes, etc.).

Cross-referencing is entirely name-based, matching Stash's own export/import convention. If a linked name has no matching slug in the corresponding `NameIndex`, `NameIndex.links()` renders it as plain text with `_(brak dopasowania w eksporcie)_` ("no match in export") instead of a broken link.

All body/section text and log entries are written in **Polish** — this convention is baked into the generator (`table_section`, `links_section` headings, `log.md` entries) and should be preserved if the script is modified.

## Directory layout

```
index.md         bundle root (OKF `type: Bundle`), lists section counts
log.md           regeneration history, one entry appended per run of the script
performers/      one .md per performer, slug = name(-disambiguation)
scenes/          one .md per scene, slug = title (falls back to filename stem)
tags/            one .md per tag, includes parent/child tag links and usage counts
studios/         one .md per studio, includes parent/child studio links and usage counts
groups/          one .md per group/movie, with ordered scene lists
galleries/       one .md per gallery
scripts/         generator: stash_export_to_okf.py (+ __pycache__)
```

## Searching the knowledge base

Per `index.md`'s own guidance: use filename/glob search (e.g. `performers/*.md`, `scenes/*.md`) to find an entity by name/title, and content search (grep) within a subdirectory to filter by attribute — e.g. grep `scenes/*.md` for a tag or studio link path (`/tags/<slug>.md`, `/studios/<slug>.md`) since tag and studio pages only show usage *counts*, not full reverse-linked lists of scenes (this was a deliberate scale tradeoff — the full corpus has ~39k scenes).

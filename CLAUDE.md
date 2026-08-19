# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repository is

This is **`arek-shark`'s personal fork of [Stash](https://github.com/stashapp/stash)** — a self-hosted Go/React web app that organizes and serves a local media collection (metadata scraping, tagging, performers/studios/tags, etc.), backed by SQLite. `origin` still points at `stashapp/stash` and the fork tracks `develop`, but this checkout carries local-only additions on top of upstream:

- `tools/` — personal Windows/Python/Go utilities (torrent-vs-library diffing, scene organizing by studio, a `git.cmd` menu for fetch/rebase/build/backup workflows). Not part of upstream Stash.
- `docs/sswiki/` — a generated, agent-searchable knowledge base (Open Knowledge Format) exported from a local Stash library. It has its own `docs/sswiki/CLAUDE.md` — **read that before touching anything under `docs/sswiki/`**; files under its `performers/scenes/tags/studios/groups/galleries/` subfolders are regenerated/destroyed by `scripts/stash_export_to_okf.py` on every run and must never be hand-edited.
- `.debug/`, `migrate_database.py`, `verify_migration.py`, `README_MIGRATION*.md`, `IMPORTANT_DATABASE_STRUCTURE.md` — ad hoc database recovery/migration scripts and notes for this user's own library, not upstream code.
- Root-level Polish naming (`polecenia/`, `pomocnicze/`, `repozytorium/`) and Polish commit messages are normal for this fork's own history — match that tone only in files that are already in Polish (e.g. `tools/misstorrentcreator/README.md`, the sswiki generator output); write everything else (Go/TS/upstream-style docs) in English as upstream does.

**Upstream's `docs/AI_POLICY.md` and `docs/CONTRIBUTING.md`** forbid AI-authored issues/PRs and require AI-assisted upstream contributions to be disclosed and fully understood by the human submitter. Those rules govern *contributions back to `stashapp/stash`*; they don't block AI assistance on this local fork, but if you ever prepare a PR/issue destined for upstream, follow them (human-written description, disclosed AI usage, tests, manual verification steps).

Full architecture deep-dive already exists at **`docs/ARCHITECTURE.md`** (layering, GraphQL request lifecycle, plugin/scraper/job systems, DB migrations, key data flows) and **`docs/DEVELOPMENT.md`** (full build/setup instructions per OS). Read those for anything not covered below rather than re-deriving it from source.

## Build & test commands

Backend is Go, frontend (`ui/v2.5/`) is React/TypeScript built with Vite and pnpm. The Go binary embeds the built frontend, so a full build always needs the UI built first.

```bash
make pre-ui          # one-time (or after UI dep changes): installs UI deps via pnpm
make generate         # regenerates Go + UI GraphQL code (gqlgen) — run after schema.graphql changes
make ui               # builds the frontend production bundle
make build             # builds stash + phasher binaries (alias for `make stash phasher`)
make stash             # builds only the stash binary (dynamically-linked debug build)
make build-release     # release build (stripped, PIE) — alias for `make flags-release flags-pie build`
make release            # full pipeline: pre-ui -> generate -> ui -> build-release
```

On **Windows** the `make` command is `mingw32-make` (MinGW64 toolchain required; CGO_ENABLED=1 for the sqlite driver). `mingw32-make release` is the "Release (full pipeline)" VS Code task and what `tools/git.cmd` option `7` runs.

Local dev loop (two terminals, hot-reload UI):

```bash
make server-start      # runs backend in ./.local (config, db, generated content live there)
make ui-start           # Vite dev server on :3000, proxies to the backend — no auth in this mode
make server-clean       # wipes ./.local to start fresh
```

Tests & linting:

```bash
make test               # go test ./... (unit tests only)
make it                 # go test -tags integration ./...  (unit + integration tests)
make lint                # golangci-lint run (backend)
make validate             # everything required before a PR: lint + it + UI validate
make fmt / make fmt-ui     # gofmt / biome+stylelint format
```

```bash
go test ./pkg/scene/...                 # run tests for one Go package
go test -run TestName ./pkg/scene/...   # run a single Go test
go test -tags integration ./pkg/sqlite/...   # integration tests need the `integration` build tag (real sqlite)
```

Frontend, from `ui/v2.5/`:

```bash
pnpm run validate       # lint (biome + stylelint) + tsc --noEmit + format-check — same as CI
pnpm run check           # tsc --noEmit only
pnpm run lint:js:fix       # biome autofix
pnpm run gqlgen           # regenerate src/core/generated-graphql.ts from graphql/*.graphql queries
```
There is no frontend unit test runner configured in this repo (no vitest/jest); `pnpm run check`/CI type-checking is the safety net for the UI.

## Architecture (see `docs/ARCHITECTURE.md` for full detail)

- **Layering**: GraphQL resolver (`internal/api/resolver_*.go`) → service layer for complex entities (`pkg/scene`, `pkg/gallery`, `pkg/image`, `pkg/group`) or validation for simple entities (`pkg/performer`, `pkg/studio`, `pkg/tag`) → repository interface (`pkg/models/repository_*.go`) → SQLite implementation (`pkg/sqlite/*.go`). Resolvers wrap operations in `withReadTxn()`/`withTxn()`.
- **GraphQL schema** lives in `graphql/schema/`; `gqlgen.yml` maps schema types to Go structs. After editing the schema, run `make generate` (backend: `make generate-backend`, UI: from `ui/v2.5`, `pnpm run gqlgen`) — don't hand-edit `internal/api/generated_*.go`.
- **DB migrations**: `pkg/sqlite/migrations/{version}_description.up.sql`, optional `{version}_premigrate.go`/`{version}_postmigrate.go` for Go-side data transforms, and bump `appSchemaVersion` in `pkg/sqlite/database.go`. Migrations are embedded via `go:embed` and run through `golang-migrate/migrate`.
- **Plugin system** (`pkg/plugin/`): YAML-configured, supports JS UI plugins and external script/binary plugins via raw or RPC interface, with hooks like `Scene.Create.Post`.
- **Scraper system** (`pkg/scraper/`): YAML-configured scrapers (XPath/JSON/GraphQL/script), plus stash-box integration for crowd-sourced metadata.
- **Job system** (`pkg/job/`, tasks in `internal/manager/task_*.go`): background jobs (Scan, Generate, Clean, Auto-tag, Identify, Export/Import) with progress reported over GraphQL subscriptions.
- **Frontend** (`ui/v2.5/src/`): Apollo Client against `/graphql`; `src/core/StashService.ts` plus per-domain query files; generated types in `src/core/generated-graphql.ts`; components grouped by entity under `src/components/`.

## Working in this fork

- Local database/config for dev runs live under `.local/` (via `make server-start`) or under the personal install at `%USERPROFILE%\.stash` (see `tools/git.cmd`, which also has commit/rebase/backup/build helpers callable as `tools\git.cmd <0-9|name>`).
- Before regenerating `docs/sswiki/`, read `docs/sswiki/CLAUDE.md` — it documents the exporter script (`docs/sswiki/scripts/stash_export_to_okf.py`), its idempotent-but-destructive-per-subdirectory behavior, and that all body text/log entries in that tree are written in Polish by convention.
- `tools/misstorrentcreator/` (torrent-vs-library gap analysis, optional LLM filename parsing via Groq/Ollama/OpenAI/OpenRouter, optional qBittorrent integration) and `tools/scenesorganizer/` are standalone Python/utility tools, documented in their own READMEs — they don't participate in the Go build.

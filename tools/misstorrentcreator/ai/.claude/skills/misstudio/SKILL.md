---
name: misstudio
description: Compares a Studio's .torrent against the local Stash library and produces (or qBittorrent-selects) only the scenes missing for that studio.
---

# /misstudio — brakujące sceny wybranego Studia

## Cel

Dla wskazanego **Studia** i pliku `.torrent`: ustal, które pliki wideo w
torrencie odpowiadają scenom, których NIE MA jeszcze w lokalnej bazie Stash
w obrębie tego studia — a następnie zbuduj torrent zawierający tylko te
brakujące pliki, albo dodaj cały torrent do qBittorrent zaznaczając do
pobrania tylko brakujące.

Backend: `miss_core.py` w tym samym katalogu (`tools/misstorrentcreator/ai/`) —
zobacz jego docstring dla pełnego kontraktu CLI/JSON. To nowy, niezależny
moduł; **nie modyfikuje** `tools/misstorrentcreator/torrent_stash_missing.py`
(importuje z niego wyłącznie sprawdzone niskopoziomowe funkcje bencode/
qBittorrent — patrz CLAUDE.md w tym katalogu).

Wszystkie polecenia poniżej uruchamiaj z katalogu
`tools/misstorrentcreator/ai/` (`python miss_core.py ...`).

## Krok po kroku

### 1. Zapytaj o nazwę Studia

```
python miss_core.py list-studios --query "<fraza od użytkownika>"
```

- Dokładnie jedno trafienie (lub nazwa identyczna ignorując wielkość liter)
  → użyj go bez pytania.
- Wiele trafień → pokaż listę (`id — name`) i poproś o numer.
- Zero trafień → poproś o inną frazę.

Zapamiętaj `studio_id` i `studio_name`.

### 2. Zapytaj o ścieżkę do pliku `.torrent`

Zweryfikuj, że plik istnieje i ma rozszerzenie `.torrent`. Jeśli nie —
poinformuj i poproś ponownie.

### 3. Wylistuj pliki wideo z torrenta

```
python miss_core.py list-files "<ścieżka do torrenta>"
```

Zwraca `files` (tylko wideo: `.mp4 .mkv .avi .wmv .mov .m4v .webm .mpg .mpeg`)
oraz `skipped_non_video` (np. `.zip`, `.jpg`). Poinformuj użytkownika ile
plików pominięto i dlaczego — **nie analizuj ich dalej**, nie trafiają do
wyniku.

### 4. Analiza nazw plików — deleguj do Fable

Wywołaj narzędzie `Agent` z `model: "fable"` (świeży, ogólny subagent — nie
`fork`, bo to zadanie jest samodzielne i niezależne od reszty konwersacji).
Przekaż **wszystkie** `name` + `directory` z kroku 3 na raz, w jednym
wywołaniu. Zadanie subagenta jest wyłącznie ekstrakcją strukturalną z tekstu
nazwy pliku — ma nie zgadywać, kto naprawdę jest w bazie Stash, tylko
odczytać, co widać w nazwie.

Dla każdego pliku subagent ma zwrócić:

```json
{"index": <index z listy>, "performers": ["Imię Nazwisko", ...],
 "date": "YYYY-MM-DD"|null, "title": "..."|null,
 "confidence": 0.0, "notes": "..."|null}
```

Wzorce spotykane w torrentach studiów (pokaż je subagentowi jako
przykłady w promcie — nie ma jednego standardu, formaty mieszają się nawet
w obrębie jednego torrenta):

| Nazwa pliku | performers | date | uwagi |
|---|---|---|---|
| `(2DAP) Angels of Hardcore 6on2 Yessica Bunny and Helen Star DP DVP DAP Triple penetration.mp4` | `["Yessica Bunny", "Helen Star"]` | null | kod na początku w nawiasie to typ sceny, nie tytuł ani data |
| `wunf 415 lilith liber 2160p.mp4` | `["Lilith Liber"]` | null | `wunf 415` to kod odcinka studia, nie aktor; `2160p` to rozdzielczość — zignoruj |
| `Shona River.[HU].mkv` | `["Shona River"]` | null | `[HU]` to kod kraju, nie data |
| `170702.Nikki-Dikki.mkv` | `["Nikki Dikki"]` | `2017-07-02` | prefiks `YYMMDD` z kropkami to data |

Separator wieloosobowy bywa: `and`, `&`, `,`, `with`, `feat.`, `ft.`. Jeśli
nie da się wydobyć żadnego aktora — `performers: []`, niska `confidence`,
`notes` wyjaśniające dlaczego.

Poproś o JSON-only output (lista obiektów, zero dodatkowego tekstu).
Dopisz do każdego wpisu `path` z kroku 3 (żeby wynik `match` mógł go
zwrócić czytelnie) i zapisz do pliku tymczasowego obok torrenta, np.
`<torrent>.parsed.json`.

### 5. Pokaż wynik parsowania i poczekaj na potwierdzenie

Wypisz zwięźle: nazwa pliku → wykryci aktorzy / data (pogrupuj po wzorcu,
jeśli to poprawia czytelność przy dużych torrentach). Zapytaj, czy się
zgadza. Jeśli użytkownik poprawia pozycję (błędnie rozpoznany aktor,
brakująca data itd.) — zaktualizuj odpowiedni wpis w JSON i pokaż jeszcze
raz zmienioną pozycję do potwierdzenia. **Nie przechodź dalej bez wyraźnej
zgody użytkownika.**

### 6. Dopasuj do Stash w obrębie studia

```
python miss_core.py match --scope studio --scope-id <studio_id> --parsed "<torrent>.parsed.json"
```

`results[]` zawiera status `present` / `missing` / `unmatched` / `skipped`
per plik + `detail` z uzasadnieniem (jaka scena dopasowana, albo dlaczego
nie).

### 7. Pokaż podsumowanie

Ile `present` / `missing` / `unmatched` / `skipped`, z listą plików
`missing` i `unmatched`. `unmatched` to sygnał: albo Fable się pomylił z
nazwiskiem, albo aktor faktycznie nie ma jeszcze karty w Stash — daj
użytkownikowi szansę poprawić dane z kroku 5 i wrócić do kroku 6, zanim
przejdziesz dalej.

### 8. Zbuduj wynik z plików `missing`

Zapisz listę indeksów `missing` do JSON (np. `<torrent>.missing_indices.json`),
potem:

```
python miss_core.py build-torrent "<torrent>" --missing "<torrent>.missing_indices.json" --out "<torrent_bez_ext>_missing.torrent"
```

- `ok: true` → gotowe, podaj ścieżkę wynikowego pliku.
- `ok: false` (torrent v1 bez natywnego BEP 47 padding) → poinformuj
  użytkownika i zaproponuj alternatywę — dodanie całego torrenta do
  qBittorrent z zaznaczeniem do pobrania tylko brakujących:

  ```
  python miss_core.py qbittorrent-push "<torrent>" --missing "<torrent>.missing_indices.json" [--qb-url ...] [--qb-user ...] [--qb-pass ...]
  ```

  Zapytaj o URL/dane logowania qBittorrent, jeśli nie są ustawione w
  zmiennych środowiskowych, zanim to wywołasz.

## Środowisko

- `STASH_URL` (domyślnie `http://localhost:9999`), `STASH_API_KEY` — jeśli
  ustawione, `miss_core.py` użyje ich automatycznie; inaczej dopytaj/użyj
  domyślnych.
- qBittorrent: `QB_URL` (domyślnie `http://localhost:8080`), `QB_USER`,
  `QB_PASS`.

## Ograniczenia (świadome — patrz `CLAUDE.md` w tym katalogu)

- Dopasowanie po (zestaw ID aktorów ⊆ aktorów sceny) + zgodność daty —
  **bez** dopasowania po rozmiarze pliku (brak odpowiednika `--size-check`
  z `torrent_stash_missing.py`).
- Analizowane są wyłącznie pliki wideo; `.zip`/`.jpg`/inne rozszerzenia są
  pomijane i nigdy nie trafiają do wyniku „missing”.

# SPEC: Raporty brakujących scen — widok kafelkowy

*Zastępuje poprzednią wersję SPEC.md (widok tabelaryczny z grupowaniem).*

---

## 1. Cel

Przebudować raporty `ActorMissingScenes` i `StudioMissingScenes` tak, żeby wyglądały jak istniejące listy scen w widoku aktora/studia:
- kafelki z miniaturką pobraną ze Stash-Box,
- lewa kolumna z polem tekstowego szukania,
- nagłówek z licznikiem i opcjami sortowania,
- licznik brakujących scen na zakładce „Missing".

Usuwa: grupowanie po roku / studio / aktorach (z poprzedniej spec), widok tabelaryczny.

Użytkownicy: właściciel lokalnej instalacji Stash, jeden użytkownik.

---

## 2. Stan bieżący (co już jest)

| Plik | Stan |
|---|---|
| `Performer.tsx` | zakładka `missing` już dodana (bez licznika) |
| `Studio.tsx` | zakładka `missing` już dodana (bez licznika) |
| `PerformerMissingPanel.tsx` | wraps `ActorMissingScenes`, gotowy |
| `StudioMissingPanel.tsx` | wraps `StudioMissingScenes`, gotowy |
| `ActorMissingScenes.tsx` | tabela + grupowanie → **do przebudowy** |
| `StudioMissingScenes.tsx` | tabela + grupowanie → **do przebudowy** |
| `graphql/schema/types/stash-box.graphql` | brak pola `image_url` → **do rozszerzenia** |
| `internal/api/resolver_query_stash_box_scenes.go` | nie zwraca obrazka → **do rozszerzenia** |
| `pkg/stashbox/scene.go` | GraphQL query bez `images` → **do rozszerzenia** |

---

## 3. Zakres zmian

### 3A. Backend — dodanie miniaturki

#### 3A-1. GraphQL schema (`graphql/schema/types/stash-box.graphql`)
Dodać pole `image_url` do obu typów:

```graphql
type StashBoxPerformerScene {
  id: ID!
  title: String
  date: String
  urls: [String!]!
  performers: [String!]!
  studio: String
  parent_studio: String
  image_url: String   # URL pierwszego obrazka ze Stash-Box (może być null)
}

type StashBoxStudioScene {
  id: ID!
  title: String
  date: String
  urls: [String!]!
  performers: [String!]!
  image_url: String   # URL pierwszego obrazka ze Stash-Box (może być null)
}
```

#### 3A-2. GraphQL query w `pkg/stashbox/scene.go`
Dodać `images { url }` do obu stałych query:

```graphql
# stashBoxQueryScenesByStudioID  i  stashBoxQueryScenesByPerformerID
scenes {
  id
  title
  date
  urls { url }
  performers { performer { id name gender } as }
  studio { name parent { name } }   # (performer query już to ma)
  images { url }                     # NOWE
}
```

#### 3A-3. Resolver (`internal/api/resolver_query_stash_box_scenes.go`)
W obu funkcjach (`StashBoxPerformerScenes`, `StashBoxStudioScenes`) dodać:

```go
var imageURL *string
if len(scene.Images) > 0 {
    url := scene.Images[0].URL
    imageURL = &url
}
// ... przy budowaniu wyniku:
result.Scenes = append(result.Scenes, &StashBoxPerformerScene{
    ...,
    ImageURL: imageURL,
})
```

---

### 3B. Frontend — widok kafelkowy

#### 3B-1. Nowy komponent: `RemoteSceneCard`

Plik: `ui/v2.5/src/components/Shared/RemoteSceneCard.tsx`

Dane wejściowe (props):
```ts
interface IRemoteSceneCardProps {
  scene: RemoteScene;          // { id, title, date, urls, performers, studio, parent_studio, image_url }
  stashboxBase?: string;       // np. "https://stashdb.org/"
  actorName?: string;          // jeśli raport dotyczy konkretnego aktora (do linka Google)
}
```

Renderowanie:
- Kontener: `<div className="scene-card card">` — te same klasy CSS co istniejące `SceneCard`
- **Thumbnail**: `<img src={scene.image_url} />` wewnątrz `<div className="scene-card-preview">`;  
  jeśli `image_url` jest null — szary placeholder z ikoną filmowej klatki
- **Overlay na thumbnail** (bottom-right): ikona zewnętrznego linku → otwiera stronę sceny na Stash-Box  
  (`${stashboxBase}scenes/${scene.id}`)
- **Treść karty** (`scene-card__details`):
  - Tytuł: link Google (`https://www.google.com/search?q={actorName}+{title}`)  
    target `_blank`, rel `noopener noreferrer`
  - Studio: `scene.parent_studio ? "${parent_studio} / ${studio}" : studio`
  - Data: `scene.date`
  - Aktorzy: `scene.performers.join(", ")`

Brak interakcji lokalnych (play, zaznaczanie, rating, O-counter) — to karta zewnętrzna, tylko-do-przeglądania.

#### 3B-2. Nowy komponent: `RemoteSceneCardGrid`

Plik: `ui/v2.5/src/components/Shared/RemoteSceneCardGrid.tsx`

```tsx
interface IProps {
  scenes: RemoteScene[];
  stashboxBase?: string;
  actorName?: string;
}
// Renderuje: <div className="card-grid"> <RemoteSceneCard .../> </div>
```

---

#### 3B-3. Przebudowa `ActorMissingScenes.tsx`

**Co usunąć:**
- `groupMode`, `groupedMissingScenes`, `ToggleButtonGroup` z grupowaniem
- Tabela HTML (`<Table>`)

**Co dodać / zmienić:**
- Typ `RemoteScene` uzupełnić o `image_url?: string | null`
- Query `STASHBOX_PERFORMER_SCENES` uzupełnić o pole `image_url`
- Nowy `searchFilter: string` (stan lokalny)
- `filteredMissingScenes` = useMemo filtrujące po `searchFilter` (tytuł, aktorzy, studio)
- Nowy `sortMode: "date" | "title" | "studio"` (stan lokalny, domyślnie `"date"`)
- `sortedFilteredScenes` = useMemo sortujące po `sortMode`
- Props `onMissingCountChange?: (count: number) => void` — wywoływany po wyliczeniu listy brakujących scen

**Nowy layout (zamiast Card+Table):**

```
┌─────────────────────────────────────────────────────────┐
│  [Stash-ID select]  [Regenerate button (tools only)]    │  ← pasek konfiguracji (ukryty gdy preselected)
├──────────────┬──────────────────────────────────────────┤
│ Szukaj...    │  Znaleziono: N  Sort: Data | Tytuł |...  │
│ (input text) ├──────────────────────────────────────────┤
│              │  [Karta] [Karta] [Karta] ...              │
│              │  [Karta] [Karta] [Karta] ...              │
└──────────────┴──────────────────────────────────────────┘
```

Konkretna implementacja HTML/JSX:
```tsx
<div className="ActorMissingScenes">
  {/* Konfiguracja - ukryta gdy preselectedPerformerId */}
  {!preselectedPerformerId && <ConfigCard ... />}

  {isLoading && <LoadingIndicator />}
  {combinedError && <ErrorMessage error={combinedError} />}

  {hasReport && (
    <div className="row">
      {/* Lewa kolumna - szukaj */}
      <div className="col-md-2">
        <Form.Control
          type="search"
          placeholder={intl.formatMessage({ id: "missing_scenes.search_placeholder" })}
          value={searchFilter}
          onChange={(e) => setSearchFilter(e.target.value)}
        />
      </div>
      {/* Główna kolumna */}
      <div className="col-md-10">
        {/* Nagłówek */}
        <div className="d-flex align-items-center mb-2 gap-2">
          <span>{sortedFilteredScenes.length} / {missingScenes.length}</span>
          <ButtonGroup>
            <Button size="sm" variant={sortMode === "date" ? "primary" : "secondary"} onClick={() => setSortMode("date")}>Data</Button>
            <Button size="sm" variant={sortMode === "title" ? "primary" : "secondary"} onClick={() => setSortMode("title")}>Tytuł</Button>
            <Button size="sm" variant={sortMode === "studio" ? "primary" : "secondary"} onClick={() => setSortMode("studio")}>Studio</Button>
          </ButtonGroup>
        </div>
        {/* Kafelki */}
        <RemoteSceneCardGrid
          scenes={sortedFilteredScenes}
          stashboxBase={stashboxBase}
          actorName={selectedPerformer?.name}
        />
      </div>
    </div>
  )}
</div>
```

**Callback `onMissingCountChange`:**
```ts
useEffect(() => {
  if (missingScenes.length >= 0 && !isLoading) {
    onMissingCountChange?.(missingScenes.length);
  }
}, [missingScenes.length, isLoading]);
```

---

#### 3B-4. Przebudowa `StudioMissingScenes.tsx`

Analogicznie do `ActorMissingScenes`:
- Usunąć `groupMode`, tabele, `ToggleButtonGroup`
- Dodać `image_url` do query i typu `RemoteScene`
- Dodać `searchFilter`, `sortMode`, `filteredMissingScenes`, `sortedFilteredScenes`
- Dodać props `onMissingCountChange?: (count: number) => void`
- Ten sam layout lewa-kolumna + kafelki

Różnica: brak `actorName` (raport studia) — link Google = `{title} + {performers.join(" ")} + {studio}`

---

#### 3B-5. Aktualizacja `PerformerMissingPanel.tsx`

```tsx
interface IProps {
  performer: GQL.PerformerDataFragment;
  onMissingCountChange?: (count: number) => void;
}

export const PerformerMissingPanel: React.FC<IProps> = ({ performer, onMissingCountChange }) => (
  <ActorMissingScenes
    preselectedPerformerId={performer.id}
    onMissingCountChange={onMissingCountChange}
  />
);
```

---

#### 3B-6. Aktualizacja `StudioMissingPanel.tsx`

```tsx
interface IProps {
  studio: GQL.StudioDataFragment;
  onMissingCountChange?: (count: number) => void;
}

export const StudioMissingPanel: React.FC<IProps> = ({ studio, onMissingCountChange }) => (
  <StudioMissingScenes
    preselectedStudioId={studio.id}
    onMissingCountChange={onMissingCountChange}
  />
);
```

---

#### 3B-7. Aktualizacja `Performer.tsx` — licznik na zakładce

W `PerformerTabs`:
```tsx
const [missingCount, setMissingCount] = useState<number | undefined>(undefined);

// W zakładce "missing":
<Tab
  eventKey="missing"
  title={
    missingCount !== undefined
      ? <TabTitleCounter messageID="missing_scenes.tab_label" count={missingCount} abbreviateCounter={abbreviateCounter} />
      : <FormattedMessage id="missing_scenes.tab_label" />
  }
>
  <PerformerMissingPanel
    performer={performer}
    onMissingCountChange={setMissingCount}
  />
</Tab>
```

---

#### 3B-8. Aktualizacja `Studio.tsx` — licznik na zakładce

Analogicznie do `Performer.tsx`:
```tsx
const [missingCount, setMissingCount] = useState<number | undefined>(undefined);

<Tab
  eventKey="missing"
  title={
    missingCount !== undefined
      ? <TabTitleCounter messageID="missing_scenes.tab_label" count={missingCount} abbreviateCounter={abbreviateCounter} />
      : <FormattedMessage id="missing_scenes.tab_label" />
  }
>
  <StudioMissingPanel studio={studio} onMissingCountChange={setMissingCount} />
</Tab>
```

---

#### 3B-9. Raporty w panelu narzędzi (`SettingsToolsPanel`)

Raporty dostępne przez Settings → Tools używają tych samych komponentów (`ActorMissingScenes`, `StudioMissingScenes`) bez `preselectedPerformerId` / `preselectedStudioId`. Po przebudowie 3B-3 i 3B-4 automatycznie uzyskają nowy widok kafelkowy — **bez dodatkowych zmian w `SettingsToolsPanel`**.

Różnica: wyświetlają selector aktora/studia i przycisk „Generuj raport". Po kliknięciu — ten sam widok kafelkowy.

---

## 4. Klucze i18n (nowe / zmienione)

```json
"missing_scenes.tab_label":        "Missing",
"missing_scenes.search_placeholder": "Szukaj po tytule, aktorach lub studiu…",
"missing_scenes.sort_by_date":     "Data",
"missing_scenes.sort_by_title":    "Tytuł",
"missing_scenes.sort_by_studio":   "Studio",
"missing_scenes.result_count":     "{filtered} / {total} brakujących"
```

Usunąć (nie są już używane):
- `missing_scenes.group_by`
- `missing_scenes.group_by_year`
- `missing_scenes.group_by_studio`
- `missing_scenes.group_by_actor`
- `missing_scenes.unknown_studio`
- `missing_scenes.unknown_actor`
- `missing_scenes.search_filter`
- `missing_scenes.search_link`

---

## 5. Pliki do modyfikacji / tworzenia

| Plik | Akcja |
|---|---|
| `graphql/schema/types/stash-box.graphql` | Dodać `image_url` do obu typów scen |
| `pkg/stashbox/scene.go` | Dodać `images { url }` do obu query |
| `internal/api/resolver_query_stash_box_scenes.go` | Przekazywać `ImageURL` w obu resolverach |
| `ui/v2.5/src/core/generated-graphql.ts` | Regenerować po zmianach schematu |
| `ui/v2.5/src/components/Shared/RemoteSceneCard.tsx` | **Nowy** — karta pojedynczej sceny zewnętrznej |
| `ui/v2.5/src/components/Shared/RemoteSceneCardGrid.tsx` | **Nowy** — siatka kart |
| `ui/v2.5/src/components/ActorMissingScenes/ActorMissingScenes.tsx` | Przebudowa — widok kafelkowy |
| `ui/v2.5/src/components/StudioMissingScenes/StudioMissingScenes.tsx` | Przebudowa — widok kafelkowy |
| `ui/v2.5/src/components/Performers/PerformerDetails/PerformerMissingPanel.tsx` | Dodać `onMissingCountChange` |
| `ui/v2.5/src/components/Studios/StudioDetails/StudioMissingPanel.tsx` | Dodać `onMissingCountChange` |
| `ui/v2.5/src/components/Performers/PerformerDetails/Performer.tsx` | Licznik na zakładce Missing |
| `ui/v2.5/src/components/Studios/StudioDetails/Studio.tsx` | Licznik na zakładce Missing |
| `ui/v2.5/src/locales/en-GB.json` | Nowe klucze i18n, usunąć stare |

---

## 6. Styl kodu

- TypeScript + React funkcyjny (hooks), bez klas.
- React-Bootstrap dla layoutu (`Row`, `Col`, `Form.Control`, `ButtonGroup`, `Button`).
- `useMemo` do filtrowania i sortowania (po stronie klienta).
- Nowe props opcjonalne — brak `preselectedPerformerId` / `onMissingCountChange` zachowuje stare zachowanie.
- Klucze i18n przez `intl.formatMessage({ id: "..." })` lub `<FormattedMessage id="..." />`.
- CSS classes (`scene-card`, `card-grid`) reużywane z istniejących komponentów.
- Brak nowych komentarzy poza nieoczywistymi przypadkami.

---

## 7. Testowanie ręczne

1. Zakładka „Missing" w widoku aktora/studia — pojawia się bez licznika, po załadowaniu raportu  
   licznik pojawia się (np. `Missing 42`).
2. Kliknięcie zakładki „Missing" → autostart raportu → widok kafelkowy z miniaturkami.
3. Wpisanie tekstu w polu szukaj → filtrowanie w czasie rzeczywistym.
4. Sortowanie (Data / Tytuł / Studio) → zmiana kolejności kafelków.
5. Kliknięcie miniaturki / tytułu → Google search otwiera się w nowej karcie.
6. Ikonka zewnętrznego linku na karte → strona sceny na Stash-Box.
7. Scena bez miniaturki → szary placeholder (nie crash).
8. Raporty z Settings → Tools → actor/studio selector + przycisk → ten sam widok kafelkowy.
9. Widok aktora/studia bez stash-id → informacja o braku stash-id (stare zachowanie).
10. Przejście do innej zakładki i powrót → raport nie generuje się ponownie (`unmountOnExit` kasuje stan, ponowne wejście auto-generuje).

---

## 8. Granice

| Zawsze | Zapytać przed | Nigdy |
|---|---|---|
| Rozszerzać istniejące komponenty | Dodać paginację dla wyników (czy naprawdę potrzebna?) | Usuwać route `/actorMissingScenes`, `/studioMissingScenes` |
| Zachować wsteczną kompatybilność (props opcjonalne) | Reużywać pełny komponent `Sidebar` z `SceneList` | Zapisywać dane raportu do bazy |
| Używać istniejącego systemu i18n | Dodać obsługę wielu stash-box równocześnie | Automatycznie uruchamiać raport bez akcji użytkownika (poza pre-selekcją) |
| CSS klasy z istniejących scene cards | | |

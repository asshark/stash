---
name: misstar
description: Compares an Actor/performer's .torrent against the local Stash library and produces (or qBittorrent-selects) only the scenes missing for that performer.
---

# /misstar — brakujące sceny wybranego Aktora

## Cel

Dokładnie jak `/misstudio`, ale zakres to **jeden Aktor** (performer) w
całej bazie Stash, niezależnie od studia, zamiast jednego studia. Dla
wskazanego Aktora i pliku `.torrent`: ustal, które pliki wideo w torrencie
odpowiadają scenom tego aktora, których NIE MA jeszcze w Stash — zbuduj
torrent z brakującymi plikami albo dodaj cały torrent do qBittorrent
zaznaczając do pobrania tylko brakujące.

Backend: `miss_core.py` w tym samym katalogu (`tools/misstorrentcreator/ai/`).
Ten skill i `/misstudio` używają tego samego backendu — różni się tylko
`--scope performer` zamiast `--scope studio`, i sposób budowania zestawu
wykonawców do dopasowania (patrz krok 6).

Wszystkie polecenia poniżej uruchamiaj z katalogu
`tools/misstorrentcreator/ai/` (`python miss_core.py ...`).

## Ważna różnica względem /misstudio: torrenty aktorów są dużo mniej jednolite

Przykłady w `Stars/` (przeanalizowane przed napisaniem tego skilla) pokazują,
że paczki jednego aktora bywają dużo bardziej niejednorodne niż torrenty
jednego studia:

- **Nazwisko wybranego Aktora często w ogóle nie występuje w nazwie pliku** —
  cała paczka już jest "o nim/o niej" (np. `[3rdDegree] - 2014.02.20 Too
  Small To Take It All 7 1080p.mp4` w paczce "Ariana Marie MegaPack" — w
  nazwie jest tylko `[Studio] - data tytuł`, żadnego imienia).
- Czasem w nazwie są **partnerzy/partnerki sceny, a nie sam wybrany Aktor**
  (np. `SZ1871_Alexis_Crystal_4K.mp4` w paczce "Chris_Diamond_huge_pack" —
  widać Alexis Crystal, nie Chrisa Diamonda).
- Bywają podkatalogi per-studio z pełniejszymi nazwami
  (`AdultTime/2022-01-30 - AdultTime - Anal Envy... (Kyler Quinn & Savannah
  Bond) (37) 1012x1920.zip` — ale to `.zip`/galeria, więc i tak pomijana,
  patrz krok 3).
- Bywają torrenty mieszane: folder `Videos/` z prawdziwymi scenami obok
  folderu `Screens/` z samymi zrzutami ekranu `.jpg` nazwanymi jak tytuły
  scen (`Sandra Soul 2.torrent`) — `list-files` filtruje `Screens/*.jpg`
  automatycznie (nie jest rozszerzeniem wideo), zostają tylko pliki z
  `Videos/`.

## Krok po kroku

### 1. Zapytaj o nazwę Aktora

```
python miss_core.py list-performers --query "<fraza od użytkownika>"
```

- Dokładnie jedno trafienie (lub nazwa/alias identyczny ignorując wielkość
  liter) → użyj go bez pytania.
- Wiele trafień → pokaż listę (`id — name`, uwzględnij `alias_list` jeśli
  pomaga odróżnić) i poproś o numer.
- Zero trafień → poinformuj, że aktora nie ma jeszcze w Stash (ta osoba
  nie ma jeszcze karty performera — `/misstar` wymaga istniejącego
  performera jako punktu odniesienia) i poproś o inną frazę lub przerwij.

Zapamiętaj `performer_id` i `performer_name`.

### 2. Zapytaj o ścieżkę do pliku `.torrent`

Zweryfikuj, że plik istnieje i ma rozszerzenie `.torrent`.

### 3. Wylistuj pliki wideo z torrenta

```
python miss_core.py list-files "<ścieżka do torrenta>"
```

Zwraca `files` (tylko wideo) oraz `skipped_non_video` (`.zip` galerie,
`.jpg` zrzuty ekranu itp. — patrz sekcja wyżej). Poinformuj użytkownika ile
i jakich plików pominięto. **Nie analizuj pominiętych dalej.**

### 4. Pobierz listę studiów ze Stash

```
python miss_core.py list-studios --limit 5000
```

(bez `--query`, żeby dostać cały katalog studiów). Ta lista jest potrzebna
w kroku 5 — **nazwa studia jest bardzo często zaszyta w nazwie pliku obok
tytułu sceny** (patrz sekcja niżej), i tylko znając realne nazwy studiów ze
Stash da się ją poprawnie oddzielić od tytułu, zamiast zgadywać.

#### Nazwa studia w nazwie pliku (nowość — dawniej ignorowane)

Bardzo częsty wzorzec w paczkach aktorów: `<Studio> - <Tytuł sceny>.mp4`,
np. w `Leo Ahsoka.torrent`:

- `ClubSweethearts - Back To School.mp4` → studio `ClubSweethearts`, tytuł
  `Back To School`.
- `DorcelClub - Girls at Work - Team Building - Jadalica's Game.mp4` →
  studio `DorcelClub`, reszta (mimo dodatkowych myślników) to tytuł.
- `PornBox - MSS 1744412 - We Discussed What We Would Eat for Dinner...mp4`
  → studio `PornBox`, `MSS 1744412` to wewnętrzny kod PornBoksa (część
  tytułu/serii, nie osobne pole).
- `Private Specials 390 - Horny Neighbours.mp4` → to **pułapka**: bez listy
  studiów można by pomyśleć, że studio to "Private Specials", ale w Stash
  studio nazywa się `Private` (a "Specials 390" to seria/numer w ramach
  tytułu) — stąd potrzeba realnej listy studiów, a nie samego
  rozpoznawania wzorca "tekst przed pierwszym myślnikiem".
- `Rocco's Perverted Secretaries 8.mp4` → brak dopasowania do żadnego
  studia z listy → `studio_hint: null`, cały tekst to tytuł.

Format bywa też inny (prefiks w nawiasach `[3rdDegree] - ...`, katalog
`AdultTime/...`, kod studia `wunf ...` — patrz istniejące przykłady w
sekcji "Ważna różnica..." wyżej) — Fable ma rozpoznawać studio niezależnie
od tego, gdzie w nazwie się pojawia, na podstawie listy z tego kroku, nie
tylko wzorca "przed pierwszym myślnikiem".

### 5. Analiza nazw plików — deleguj do Fable

Wywołaj `Agent` z `model: "fable"` (świeży subagent, nie `fork`). Przekaż
**wszystkie** `name` + `directory` z kroku 3, **oraz pełną listę nazw
studiów** z kroku 4, na raz. Zadanie subagenta to wyłącznie ekstrakcja
tekstowa — **nie** zakładaj z góry, że wybrany Aktor pojawi się w nazwie
pliku (patrz przykłady wyżej — często się nie pojawia). Subagent ma
wypisać dokładnie to, co widać w tekście, nic więcej — poza jednym
wyjątkiem: dopasowaniem nazwy studia do dostarczonej listy (patrz niżej).

Dla każdego pliku subagent ma zwrócić:

```json
{"index": <index z listy>, "performers": ["Imię Nazwisko", ...],
 "date": "YYYY-MM-DD"|null, "title": "..."|null, "studio_hint": "..."|null,
 "confidence": 0.0, "notes": "..."|null}
```

`performers` to tylko osoby faktycznie nazwane w tekście (może być pusta
lista — to normalne dla torrentów w stylu "Ariana Marie MegaPack", gdzie
tylko studio+data+tytuł są w nazwie).

`studio_hint`: sprawdź, czy w nazwie pliku (dowolne miejsce — prefiks przed
myślnikiem, nawias, nazwa podkatalogu, prefiks kodu) da się rozpoznać jedno
z **dokładnych** studiów z listy przekazanej w tym kroku (dopuszczalne
drobne różnice wielkości liter/spacji, ale nie zgadywanie po znaczeniu).
Jeśli tak — wstaw dokładną nazwę studia tak, jak występuje na liście, i
**usuń ten fragment z `title`** (razem z otaczającym separatorem, np.
` - `), żeby `title` zawierał tylko właściwy tytuł sceny. Jeśli nic z listy
nie pasuje pewnie — `studio_hint: null` i zostaw `title` w całości (bez
obcinania zgadywanego prefiksu). `miss_core.py match` i tak dorobi
dopasowanie tekst→Stash na końcu (dokładne/alias, jak przy performerach),
więc drobne niedopasowanie pisowni tutaj nie jest krytyczne — ważniejsze
jest niezgadywanie studia, którego nie ma na liście.

Poproś o JSON-only output. Dopisz `path` z kroku 3 do każdego wpisu i
zapisz do pliku tymczasowego obok torrenta, np. `<torrent>.parsed.json`.

### 6. Pokaż wynik parsowania i poczekaj na potwierdzenie

Jak w `/misstudio` — wypisz zwięźle nazwa → wykryci aktorzy/data/tytuł/
studio_hint, zapytaj czy się zgadza, pozwól poprawić pojedyncze wpisy,
**nie przechodź dalej bez potwierdzenia**. Jeśli dla wielu plików
`studio_hint` wyszło `null` mimo że nazwy wyglądają na `Studio - Tytuł`,
to sygnał, że lista studiów z kroku 4 mogła nie dotrzeć do Fable albo dane
studio faktycznie nie istnieje jeszcze w Stash — zwróć na to uwagę
użytkownikowi.

### 7. Dopasuj do Stash w kontekście Aktora

```
python miss_core.py match --scope performer --scope-id <performer_id> --parsed "<torrent>.parsed.json"
```

Kluczowa różnica względem trybu studia: `miss_core.py` **automatycznie
dodaje wybranego Aktora** do zestawu wykonawców użytego do dopasowania
sceny, niezależnie od tego, czy jego nazwisko pojawiło się w nazwie pliku.
Czyli dla `SZ1871_Alexis_Crystal_4K.mp4` w paczce Chrisa Diamonda, zestaw
do dopasowania to `{Chris Diamond, Alexis Crystal}` — szuka sceny w Stash,
która zawiera OBOJE. Dla plików bez żadnego wykrytego performera (np.
Ariana Marie MegaPack) zestaw to po prostu `{Ariana Marie}`.

Jeśli plik ma `studio_hint`, `match` rozwiązuje go do studia w Stash
(dokładna nazwa/alias, bez rozróżniania wielkości liter) i **filtruje
kandydatki tylko do scen z tym samym studiem** — dokładnie tak samo, jak
już traktuje datę: znane i różne wyklucza, nieznane po którejkolwiek
stronie nie wyklucza. **To twardy filtr, nie preferencja** — jeśli żadna
scena pasująca po aktorach+dacie nie ma tego studia, plik dostaje
`missing`, nawet gdy jego tytuł dokładnie zgadza się z tytułem jakiejś
sceny w Stash pod innym studiem (potwierdzone przez użytkownika na
przykładzie `BangBros - Jadilica Maid For Anal.mp4`, który w Stash figuruje
pod studiem „My Dirty Maid" — mimo identycznego tytułu to `missing`, nie
`present`).

Wśród kandydatek, które przeszły filtr studia+daty, `match` wskaże
konkretną scenę jako `present` tylko wtedy, gdy coś ją jednoznacznie
rozstrzyga — dokładnie jedna kandydatka, trafienie po dacie, albo
podobieństwo `title` do tytułu sceny w Stash. **Jeśli nic tego nie
rozstrzyga — kilka kandydatek, brak daty, brak trafienia po tytule — plik
dostaje `missing`, a nie zgadnięty `present`.** To ważne: pierwsza wersja
tej logiki w takiej sytuacji brała "pierwszą z brzegu" scenę tego aktora i
zwracała `present` — na `Leo Ahsoka.torrent` to fałszywie dopasowało
kilkadziesiąt różnych plików do jednej i tej samej sceny. Fałszywy
`present` jest tu gorszy niż fałszywy `missing` (cichy brak treści vs.
jedno spojrzenie w kroku 8), stąd `missing` jako domyślny wynik przy braku
sygnału rozstrzygającego.

**Dodatkowo**: `match` wykrywa też sytuację, gdy studio zawęża kilka
*różnych* plików do tej samej jednej sceny w Stash (np. 4 różne
`ClubSweethearts - ...mp4`, a dany aktor ma w Stash tylko jedną scenę tego
studia) — zostawia `present` tylko na tym pliku, którego `title` faktycznie
pasuje do tytułu tej sceny, resztę cofa do `missing`. Jeśli żaden tytuł w
takiej grupie nie pasuje, **wszystkie** pliki z grupy dostają `missing`
(nie zgaduje, który — jeśli w ogóle który — to ta scena). To nie zastępuje
pełnego dopasowania po rozmiarze pliku (patrz "Ograniczenia" niżej) —
przypadek, gdy aktor ma *kilka* scen tego studia i żaden tytuł pliku nie
pasuje wystarczająco dobrze do żadnej z nich, nadal wymaga ręcznego
spojrzenia w kroku 8.

`results[]` zawiera status `present` / `missing` / `unmatched` / `skipped`
per plik + `detail`.

### 8. Pokaż podsumowanie

Jak w `/misstudio`. `unmatched` tutaj zwykle znaczy: partner/partnerka z
nazwy pliku nie istnieje jeszcze w Stash (a nie sam wybrany Aktor — ten
zawsze się rozwiązuje, bo użytkownik wybrał go z istniejącej listy w kroku
1). Zwróć uwagę użytkownika na wpisy `present`, których `detail` zawiera
ostrzeżenie `[uwaga: plik wskazuje na studio ...]` — to sceny dopasowane
mimo niezgodności studia, warto je zweryfikować ręcznie.

### 9. Zbuduj wynik z plików `missing`

Identycznie jak w `/misstudio`, krok 8 — `build-torrent`, z fallbackiem na
`qbittorrent-push` gdy torrent nie ma natywnego BEP 47 padding.

## Środowisko

Jak w `/misstudio`: `STASH_URL`, `STASH_API_KEY`, `QB_URL`, `QB_USER`,
`QB_PASS`.

## Ograniczenia (świadome — patrz `CLAUDE.md` w tym katalogu)

- Dopasowanie po (zestaw ID aktorów ⊆ aktorów sceny, zawsze zawiera
  wybranego Aktora) + zgodność daty + zgodność studia, gdy któreś z nich
  jest znane po stronie pliku (znane-i-różne wyklucza, nieznane nie
  wyklucza) — `title` tylko jako miękki tie-break między kandydatkami,
  które już przeszły te twarde filtry. Bez dopasowania po rozmiarze pliku.
- Analizowane są wyłącznie pliki wideo; galerie `.zip` i zrzuty ekranu
  `.jpg` są pomijane, nawet jeśli reprezentują treść, której w Stash
  faktycznie brakuje (to świadome ograniczenie wersji 1 — patrz CLAUDE.md).
- Gdy w nazwie pliku nie ma żadnego wykrytego performera i sceny wybranego
  Aktora w Stash nie mają daty, `match` nie ma jak rozstrzygnąć która
  konkretna scena to ta z pliku — wynik `missing`/`present` może być mniej
  precyzyjny niż przy pełnych danych (title z kroku 4 jest wtedy jedyną
  dodatkową wskazówką dla człowieka przy ręcznej weryfikacji w kroku 5/7).

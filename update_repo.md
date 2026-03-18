# Aktualizacja repozytorium bez utraty lokalnych zmian

Poniższe kroki pozwalają pobrać nowe zmiany z repozytorium zdalnego i **zachować Twoje niezatwierdzone modyfikacje** w lokalnym repo (tzw. “working tree changes”).

> Zakładam, że pracujesz na gałęzi `develop` (u Ciebie lokalna gałąź śledzi `origin/develop`). Jeśli jesteś na innej gałęzi, zamień nazwę gałęzi w poleceniach.

## Krok 1: Wejdź do katalogu repo

```powershell
cd "S:\MyProjects\stash\stash"
```

## Krok 2: Sprawdź bieżący stan (zanim zrobisz stash)

```powershell
git status -sb
git branch --show-current

# Sprawdź, czy masz zmiany "staged" (w indeksie) i/lub "unstaged" (w working tree)
git diff --cached --quiet
$stagedHasChanges = ($LASTEXITCODE -ne 0)

git diff --quiet
$unstagedHasChanges = ($LASTEXITCODE -ne 0)

Write-Host "STAGED changes:   $stagedHasChanges"
Write-Host "UNSTAGED changes: $unstagedHasChanges"
```

## Wariant alternatywny: Najpierw lokalny commit, potem pobierz zmiany

Ten wariant jest dobry, jeśli wolisz utworzyć **lokalne commity** ze swoich zmian, a dopiero potem pobrać nowe zdalne i je “przełożyć” przez Twoją historię (`git pull --rebase`).

### Krok A1: Dodaj zmiany do indeksu

Jeśli chcesz dodać wszystko (łącznie z ewentualnymi `??`):

```powershell
git add -A
```

Jeśli NIE chcesz, żeby do commita trafiła Twoja notatka `update_repo.md` (opcjonalnie):

```powershell
git restore --staged update_repo.md 2>$null
```

### Krok A2: Zrób lokalny commit

```powershell
git commit -m "WIP: lokalne zmiany"
```

### Krok A3: Pobierz nowe zmiany i zrób rebase

```powershell
git pull --rebase
```

Jeśli pojawią się konflikty w trakcie rebase:

1. Rozwiąż konflikty w plikach.
2. Dodaj rozwiązane pliki:
   ```powershell
   git add -A
   ```
3. Kontynuuj:
   ```powershell
   git rebase --continue
   ```
4. Powtarzaj aż rebase zakończy się powodzeniem.

### Krok A4: Sprawdź końcowy stan

```powershell
git status -sb
```

## Krok 3: Schowaj lokalne niezatwierdzone zmiany (stash)

`git stash` schowa tylko niezatwierdzone zmiany w working tree / indeksie. Twoje lokalne commity (jeśli `git status -sb` pokazuje `ahead ...`) pozostaną.
W praktyce: jeśli masz `ahead`, to `git pull --rebase` przebazuję także Twoje lokalne commity na świeższy stan z `origin`.

Następnie wybierz wariant:

### Wariant A: Masz zmiany `staged` (a working tree jest bez zmian)

Używaj gdy: `$stagedHasChanges = True` i `$unstagedHasChanges = False`.

To schowa zmiany w indeksie (staged) oraz ewentualne nowe/nieśledzone pliki (`-u`).

```powershell
git stash push -u --staged -m "WIP przed aktualizacją z origin"
```

### Wariant B: Brak `staged` (tylko zmiany `unstaged` i/lub nieśledzone pliki)

Używaj gdy: `$stagedHasChanges = False` (niezależnie od tego, czy `$unstagedHasChanges` jest True/False).

To schowa zarówno zmiany śledzonych plików, jak i ewentualne nowe/nieśledzone pliki (`-u`).

```powershell
git stash push -u -m "WIP przed aktualizacją z origin"
```

### Wariant C: Masz jednocześnie `staged` i `unstaged`

Używaj gdy: `$stagedHasChanges = True` i `$unstagedHasChanges = True`.

To schowa zarówno zmiany w indeksie (`staged`), jak i zmiany w working tree (`unstaged`) oraz ewentualne nowe/nieśledzone pliki (`-u`).

```powershell
git stash push -u -m "WIP przed aktualizacją z origin"
```

## Krok 4: Pobierz nowe zmiany i zaktualizuj lokalną gałąź

Najbezpieczniej zwykle użyć `--rebase`, żeby zachować historię w miarę liniową:

```powershell
git pull --rebase
```

Jeśli pojawią się konflikty w trakcie rebase:

1. Rozwiąż konflikty w plikach.
2. Dodaj rozwiązane pliki:
   ```powershell
   git add -A
   ```
3. Kontynuuj rebase:
   ```powershell
   git rebase --continue
   ```
4. Powtarzaj aż rebase zakończy się powodzeniem.

## Krok 5: Przywróć swoje schowane zmiany (stash pop)

```powershell
git stash pop
```

## Krok 6: Jeśli `stash pop` spowoduje konflikty

1. Rozwiąż konflikty w plikach.
2. Sprawdź status:
   ```powershell
   git status
   ```
3. Po ręcznym rozwiązaniu konfliktów i dodaniu plików do indeksu:
   ```powershell
   git add -A
   ```
4. Jeśli stash nie został automatycznie usunięty (często pozostaje przy konfliktach), sprawdź listę:
   ```powershell
   git stash list
   ```
5. Usuń już niepotrzebny wpis stash (dopiero po potwierdzeniu, że wszystko jest poprawnie w working tree):
   ```powershell
   git stash drop stash@{0}
   ```

## Krok 7: Na koniec potwierdź, że wszystko gra

```powershell
git status
```

Jeśli chcesz, możesz też uruchomić test/build procesu po Twojej stronie.


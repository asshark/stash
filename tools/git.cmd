@echo off
chcp 65001 > nul
setlocal EnableDelayedExpansion

REM git.cmd - pomocnicze polecenia git/build/deploy dla repozytorium stash
REM Uzycie: git.cmd [1-9|check-remote|show-remote|status-local|commit-local|pull-rebase|verify|build-release|install-stash|backup-stash|help]

set "STASH_HOME=C:\Users\areks\.stash"
set "STASH_BIN=%STASH_HOME%\bin"
set "STASH_BACKUP=%STASH_HOME%\backup"

cd /d "%~dp0.."
if errorlevel 1 (
    echo [git.cmd] Nie mozna przejsc do katalogu repo.
    exit /b 1
)

if not exist ".git" (
    echo [git.cmd] Brak katalogu .git.
    exit /b 1
)

for /f "delims=" %%I in ('git branch --show-current 2^>nul') do set "GIT_BRANCH=%%I"
if not defined GIT_BRANCH set "GIT_BRANCH=develop"

if "%~1"=="" goto menu
if /i "%~1"=="1" goto check_remote
if /i "%~1"=="2" goto show_remote
if /i "%~1"=="3" goto status_local
if /i "%~1"=="4" goto commit_local
if /i "%~1"=="5" goto pull_rebase
if /i "%~1"=="6" goto verify_rebase
if /i "%~1"=="7" goto build_release
if /i "%~1"=="8" goto install_stash
if /i "%~1"=="9" goto backup_stash
if /i "%~1"=="check-remote" goto check_remote
if /i "%~1"=="show-remote" goto show_remote
if /i "%~1"=="status-local" goto status_local
if /i "%~1"=="commit-local" goto commit_local
if /i "%~1"=="pull-rebase" goto pull_rebase
if /i "%~1"=="verify" goto verify_rebase
if /i "%~1"=="build-release" goto build_release
if /i "%~1"=="install-stash" goto install_stash
if /i "%~1"=="backup-stash" goto backup_stash
if /i "%~1"=="help" goto help
if /i "%~1"=="/?" goto help
if /i "%~1"=="--help" goto help

echo [git.cmd] Nieznana opcja: %~1
goto help

:menu
echo.
echo === git.cmd - repo: %CD% ===
echo Galaz: !GIT_BRANCH!
echo.
echo  1. Sprawdz czy na remote sa nowe zmiany
echo  2. Wyswietl nowe zmiany z remote
echo  3. Sprawdz lokalne niezatwierdzone zmiany
echo  4. Zatwierdz lokalne zmiany (commit)
echo  5. Pobierz remote i naloz lokalne commity (pull --rebase)
echo  6. Sprawdz czy wszystko pobrane i brak konfliktow po rebase
echo  7. Zbuduj release (mingw32-make release)
echo  8. Skopiuj stash.exe do !STASH_BIN!
echo  9. Backup stash.exe, bazy i config do !STASH_BACKUP!
echo.
echo  help - pomoc
echo  q    - wyjscie
echo.
set /p "CHOICE=Wybierz opcje: "
if /i "!CHOICE!"=="1" goto check_remote
if /i "!CHOICE!"=="2" goto show_remote
if /i "!CHOICE!"=="3" goto status_local
if /i "!CHOICE!"=="4" goto commit_local
if /i "!CHOICE!"=="5" goto pull_rebase
if /i "!CHOICE!"=="6" goto verify_rebase
if /i "!CHOICE!"=="7" goto build_release
if /i "!CHOICE!"=="8" goto install_stash
if /i "!CHOICE!"=="9" goto backup_stash
if /i "!CHOICE!"=="help" goto help
if /i "!CHOICE!"=="q" exit /b 0
if "!CHOICE!"=="" exit /b 0
echo Nieznana opcja: !CHOICE!
exit /b 1

:check_remote
echo.
echo === 1. Sprawdzanie remote (origin/!GIT_BRANCH!) ===
echo Pobieram metadane z origin...
git fetch origin
if errorlevel 1 (
    echo [git.cmd] git fetch nie powiodl sie.
    exit /b 1
)
echo.
git status -sb
echo.
for /f "tokens=1,2" %%A in ('git rev-list --left-right --count origin/!GIT_BRANCH!...HEAD 2^>nul') do (
    set "BEHIND=%%A"
    set "AHEAD=%%B"
)
if not defined BEHIND (
    echo [git.cmd] Nie mozna porownac z origin/!GIT_BRANCH!.
    exit /b 1
)
echo Podsumowanie wzgledem origin/!GIT_BRANCH!:
echo   behind (nowe na remote): !BEHIND!
echo   ahead  (Twoje commity):  !AHEAD!
echo.
if "!BEHIND!"=="0" (
    echo Brak nowych commitow na remote.
) else (
    echo Sa nowe commity na remote. Uzyj opcji 2, zeby je zobaczyc.
)
exit /b 0

:show_remote
echo.
echo === 2. Nowe commity na origin/!GIT_BRANCH! ===
git fetch origin
if errorlevel 1 (
    echo [git.cmd] git fetch nie powiodl sie.
    exit /b 1
)
echo.
for /f "tokens=1" %%A in ('git rev-list --left-right --count origin/!GIT_BRANCH!...HEAD 2^>nul') do set "BEHIND=%%A"
if not defined BEHIND (
    echo [git.cmd] Nie mozna porownac z origin/!GIT_BRANCH!.
    exit /b 1
)
if "!BEHIND!"=="0" (
    echo Brak nowych commitow na remote wzgledem Twojej galezi.
    exit /b 0
)
echo Commity na remote, ktorych nie masz lokalnie ^(!BEHIND!^):
echo.
git --no-pager log HEAD..origin/!GIT_BRANCH! --oneline --decorate --graph
echo.
echo Zmiany w plikach (ostatnie 10 commitow):
git --no-pager log HEAD..origin/!GIT_BRANCH! --stat --oneline -n 10
exit /b 0

:status_local
echo.
echo === 3. Lokalne niezatwierdzone zmiany ===
echo Galaz: !GIT_BRANCH!
echo.
git status -sb
echo.
git diff --stat
git diff --cached --stat
echo.
git diff --quiet
if errorlevel 1 (
    echo [unstaged] Sa zmiany w working tree.
) else (
    echo [unstaged] Brak zmian w working tree.
)
git diff --cached --quiet
if errorlevel 1 (
    echo [staged] Sa zmiany w indeksie.
) else (
    echo [staged] Brak zmian w indeksie.
)
git status --porcelain | findstr /r "^??" >nul
if not errorlevel 1 (
    echo [untracked] Sa nieledzone pliki.
) else (
    echo [untracked] Brak nieledzonych plikow.
)
exit /b 0

:commit_local
echo.
echo === 4. Lokalny commit zmian ===
git status -sb
echo.
git diff --quiet
set "UNSTAGED_OK=!ERRORLEVEL!"
git diff --cached --quiet
set "STAGED_OK=!ERRORLEVEL!"
git status --porcelain | findstr /r "^??" >nul
set "UNTRACKED_OK=!ERRORLEVEL!"

if "!UNSTAGED_OK!"=="0" if "!STAGED_OK!"=="0" if not "!UNTRACKED_OK!"=="0" (
    echo Brak zmian do zatwierdzenia.
    exit /b 0
)

echo Dodaje wszystkie zmiany do indeksu (git add -A)...
git add -A
if errorlevel 1 (
    echo [git.cmd] git add nie powiodl sie.
    exit /b 1
)

set "MSG=%~2"
if "!MSG!"=="" (
    set /p "MSG=Wiadomosc commita [WIP: lokalne zmiany]: "
    if "!MSG!"=="" set "MSG=WIP: lokalne zmiany"
)

echo Tworze commit: !MSG!
git commit -m "!MSG!"
if errorlevel 1 (
    echo [git.cmd] git commit nie powiodl sie.
    exit /b 1
)
echo.
git status -sb
exit /b 0

:pull_rebase
echo.
echo === 5. Pobierz remote i naloz lokalne commity ===
echo Galaz: !GIT_BRANCH!
echo.
git fetch origin
if errorlevel 1 (
    echo [git.cmd] git fetch nie powiodl sie.
    exit /b 1
)
echo Uruchamiam: git pull --rebase origin !GIT_BRANCH!
git pull --rebase origin !GIT_BRANCH!
if errorlevel 1 (
    echo.
    echo [git.cmd] Rebase przerwany - prawdopodobnie konflikt.
    echo Rozwiaz konflikty, potem:
    echo   git add -A
    echo   git rebase --continue
    echo Aby przerwac:
    echo   git rebase --abort
    exit /b 1
)
echo.
git status -sb
exit /b 0

:verify_rebase
echo.
echo === 6. Weryfikacja stanu po rebase ===
set "VERIFY_OK=1"

git fetch origin
if errorlevel 1 (
    echo [FAIL] git fetch nie powiodl sie.
    set "VERIFY_OK=0"
)

echo.
git status -sb
echo.

if exist ".git\rebase-merge" (
    echo [FAIL] Trwa rebase ^(.git\rebase-merge^).
    set "VERIFY_OK=0"
)
if exist ".git\rebase-apply" (
    echo [FAIL] Trwa rebase ^(.git\rebase-apply^).
    set "VERIFY_OK=0"
)
if exist ".git\MERGE_HEAD" (
    echo [FAIL] Trwa merge ^(.git\MERGE_HEAD^).
    set "VERIFY_OK=0"
)

set "HAS_CONFLICTS=0"
for /f "delims=" %%F in ('git diff --name-only --diff-filter=U 2^>nul') do (
    if "!HAS_CONFLICTS!"=="0" (
        echo [FAIL] Sa pliki w konflikcie:
        set "HAS_CONFLICTS=1"
        set "VERIFY_OK=0"
    )
    echo   %%F
)
if "!HAS_CONFLICTS!"=="0" (
    echo [OK] Brak plikow w konflikcie.
)

git diff --quiet
if errorlevel 1 (set "UNSTAGED=1") else (set "UNSTAGED=0")
git diff --cached --quiet
if errorlevel 1 (set "STAGED=1") else (set "STAGED=0")
if "!UNSTAGED!"=="0" if "!STAGED!"=="0" (
    echo [OK] Working tree czysty.
) else (
    echo [WARN] Sa niezatwierdzone lokalne zmiany.
)

for /f "tokens=1,2" %%A in ('git rev-list --left-right --count origin/!GIT_BRANCH!...HEAD 2^>nul') do (
    set "BEHIND=%%A"
    set "AHEAD=%%B"
)
if not defined BEHIND (
    echo [FAIL] Nie mozna porownac z origin/!GIT_BRANCH!.
    set "VERIFY_OK=0"
) else (
    echo.
    echo Podsumowanie wzgledem origin/!GIT_BRANCH!:
    echo   behind: !BEHIND!
    echo   ahead:  !AHEAD!
    if "!BEHIND!"=="0" (
        echo [OK] Wszystkie commity z remote sa pobrane.
    ) else (
        echo [FAIL] Brakuje !BEHIND! commitow z remote. Uruchom opcje 5.
        set "VERIFY_OK=0"
    )
)

echo.
if "!VERIFY_OK!"=="1" (
    echo === Weryfikacja: OK ===
    exit /b 0
)
echo === Weryfikacja: PROBLEMY ===
exit /b 1

:build_release
echo.
echo === 7. Build release (full pipeline) ===
echo Uruchamiam: mingw32-make release
echo To odpowiada taskowi VS Code "Release (full pipeline)".
echo.
mingw32-make release
if errorlevel 1 (
    echo [git.cmd] Build release nie powiodl sie.
    exit /b 1
)
if not exist "stash.exe" (
    echo [git.cmd] Build zakonczony, ale brak pliku stash.exe w katalogu repo.
    exit /b 1
)
echo.
echo [OK] Build zakonczony: %CD%\stash.exe
exit /b 0

:install_stash
echo.
echo === 8. Kopiowanie stash.exe do !STASH_BIN! ===
if not exist "stash.exe" (
    echo [git.cmd] Brak pliku stash.exe w katalogu repo.
    echo Uruchom najpierw opcje 7 (build release).
    exit /b 1
)
if not exist "!STASH_BIN!" (
    echo Tworze katalog: !STASH_BIN!
    mkdir "!STASH_BIN!"
)
copy /Y "stash.exe" "!STASH_BIN!\stash.exe"
if errorlevel 1 (
    echo [git.cmd] Kopiowanie nie powiodlo sie.
    exit /b 1
)
echo [OK] Skopiowano do !STASH_BIN!\stash.exe
exit /b 0

:backup_stash
echo.
echo === 9. Backup stash.exe, bazy i config ===
set "BACKUP_OK=1"
set "BACKUP_DIR="

for /f "delims=" %%T in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd_HHmmss"') do set "BACKUP_TS=%%T"
set "BACKUP_DIR=!STASH_BACKUP!\!BACKUP_TS!"

if not exist "!STASH_BACKUP!" mkdir "!STASH_BACKUP!"
mkdir "!BACKUP_DIR!"
if errorlevel 1 (
    echo [git.cmd] Nie mozna utworzyc katalogu backup: !BACKUP_DIR!
    exit /b 1
)

echo Katalog backup: !BACKUP_DIR!
echo.

if exist "stash.exe" (
    copy /Y "stash.exe" "!BACKUP_DIR!\stash.exe" >nul
    if errorlevel 1 (
        echo [FAIL] Nie udalo sie skopiowac stash.exe z repo.
        set "BACKUP_OK=0"
    ) else (
        echo [OK] stash.exe ^(z repo^)
    )
) else (
    echo [WARN] Brak stash.exe w repo - pomijam.
)

if exist "!STASH_HOME!\config.yml" (
    copy /Y "!STASH_HOME!\config.yml" "!BACKUP_DIR!\config.yml" >nul
    if errorlevel 1 (
        echo [FAIL] Nie udalo sie skopiowac config.yml.
        set "BACKUP_OK=0"
    ) else (
        echo [OK] config.yml
    )
) else (
    echo [WARN] Brak !STASH_HOME!\config.yml
)

set "DB_COPIED=0"
call :copy_db_file "!STASH_HOME!\stash-go.sqlite"
call :copy_db_file "!STASH_HOME!\database\stash-go.sqlite"

if "!DB_COPIED!"=="0" (
    echo [WARN] Nie znaleziono bazy stash-go.sqlite w !STASH_HOME!
)

echo.
if "!BACKUP_OK!"=="1" (
    echo [OK] Backup zapisany w: !BACKUP_DIR!
    exit /b 0
)
echo [FAIL] Backup zakonczony z bledami.
exit /b 1

:copy_db_file
if not exist "%~1" exit /b 0
for %%F in ("%~1") do set "DB_BASE=%%~nxF"
copy /Y "%~1" "!BACKUP_DIR!\!DB_BASE!" >nul
if not errorlevel 1 (
    echo [OK] !DB_BASE!
    set "DB_COPIED=1"
)
if exist "%~1-wal" (
    copy /Y "%~1-wal" "!BACKUP_DIR!\!DB_BASE!-wal" >nul
    if not errorlevel 1 echo [OK] !DB_BASE!-wal
)
if exist "%~1-shm" (
    copy /Y "%~1-shm" "!BACKUP_DIR!\!DB_BASE!-shm" >nul
    if not errorlevel 1 echo [OK] !DB_BASE!-shm
)
exit /b 0

:help
echo.
echo Uzycie:
echo   git.cmd
echo   git.cmd 1 .. 9
echo   git.cmd check-remote ^| show-remote ^| status-local ^| commit-local
echo   git.cmd pull-rebase ^| verify ^| build-release ^| install-stash ^| backup-stash
echo   git.cmd commit-local "Wiadomosc commita"
echo.
echo Opcje:
echo   1  Sprawdz czy na remote sa nowe commity
echo   2  Wyswietl commity i statystyke plikow z remote
echo   3  Sprawdz lokalne niezatwierdzone zmiany
echo   4  Dodaj i zatwierdz lokalne zmiany
echo   5  Pobierz remote i przebazuj lokalne commity
echo   6  Sprawdz czy wszystko pobrane i brak konfliktow po rebase
echo   7  Zbuduj release (mingw32-make release)
echo   8  Skopiuj stash.exe do %STASH_BIN%
echo   9  Backup stash.exe, bazy i config do %STASH_BACKUP%
echo.
echo Sciezki (edytuj na poczatku git.cmd):
echo   STASH_HOME=%STASH_HOME%
echo   STASH_BIN=%STASH_BIN%
echo   STASH_BACKUP=%STASH_BACKUP%
exit /b 0

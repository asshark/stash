@echo off
chcp 65001 > nul
setlocal EnableDelayedExpansion

REM git.cmd - pomocnicze polecenia git dla repozytorium stash
REM Uzycie: git.cmd [1-5|check-remote|show-remote|status-local|commit-local|pull-rebase|help]

cd /d "%~dp0.."
if errorlevel 1 (
    echo [git.cmd] Nie mozna przejsc do katalogu repo.
    exit /b 1
)

if not exist ".git" (
    echo [git.cmd] Brak katalogu .git.
    exit /b 1
)

for /f "delims=" %%B in ('git branch --show-current 2^>nul') do set "BRANCH=%%B"
if "%BRANCH%"=="" set "BRANCH=develop"

if "%~1"=="" goto menu
if /i "%~1"=="1" goto check_remote
if /i "%~1"=="2" goto show_remote
if /i "%~1"=="3" goto status_local
if /i "%~1"=="4" goto commit_local
if /i "%~1"=="5" goto pull_rebase
if /i "%~1"=="check-remote" goto check_remote
if /i "%~1"=="show-remote" goto show_remote
if /i "%~1"=="status-local" goto status_local
if /i "%~1"=="commit-local" goto commit_local
if /i "%~1"=="pull-rebase" goto pull_rebase
if /i "%~1"=="help" goto help
if /i "%~1"=="/?" goto help
if /i "%~1"=="--help" goto help

echo [git.cmd] Nieznana opcja: %~1
goto help

:menu
echo.
echo === git.cmd - repo: %CD% ===
echo Galaz: %BRANCH%
echo.
echo  1. Sprawdz czy na remote sa nowe zmiany
echo  2. Wyswietl nowe zmiany z remote
echo  3. Sprawdz lokalne niezatwierdzone zmiany
echo  4. Zatwierdz lokalne zmiany (commit)
echo  5. Pobierz remote i naloz lokalne commity (pull --rebase)
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
if /i "!CHOICE!"=="help" goto help
if /i "!CHOICE!"=="q" exit /b 0
if "!CHOICE!"=="" exit /b 0
echo Nieznana opcja: !CHOICE!
exit /b 1

:check_remote
echo.
echo === 1. Sprawdzanie remote (origin/%BRANCH%) ===
echo Pobieram metadane z origin...
git fetch origin
if errorlevel 1 (
    echo [git.cmd] git fetch nie powiodl sie.
    exit /b 1
)
echo.
git status -sb
echo.
for /f "tokens=1,2" %%A in ('git rev-list --left-right --count origin/%BRANCH%...HEAD 2^>nul') do (
    set "BEHIND=%%A"
    set "AHEAD=%%B"
)
if not defined BEHIND (
    echo [git.cmd] Nie mozna porownac z origin/%BRANCH%.
    exit /b 1
)
echo Podsumowanie wzgledem origin/%BRANCH%:
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
echo === 2. Nowe commity na origin/%BRANCH% ===
git fetch origin
if errorlevel 1 (
    echo [git.cmd] git fetch nie powiodl sie.
    exit /b 1
)
echo.
for /f "tokens=1" %%A in ('git rev-list --left-right --count origin/%BRANCH%...HEAD 2^>nul') do set "BEHIND=%%A"
if not defined BEHIND (
    echo [git.cmd] Nie mozna porownac z origin/%BRANCH%.
    exit /b 1
)
if "!BEHIND!"=="0" (
    echo Brak nowych commitow na remote wzgledem Twojej galezi.
    exit /b 0
)
echo Commity na remote, ktorych nie masz lokalnie ^(!BEHIND!^):
echo.
git log HEAD..origin/%BRANCH% --oneline --decorate --graph
echo.
echo Zmiany w plikach (ostatnie 10 commitow):
git log HEAD..origin/%BRANCH% --stat --oneline -n 10
exit /b 0

:status_local
echo.
echo === 3. Lokalne niezatwierdzone zmiany ===
echo Galaz: %BRANCH%
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
echo Galaz: %BRANCH%
echo.
git fetch origin
if errorlevel 1 (
    echo [git.cmd] git fetch nie powiodl sie.
    exit /b 1
)
echo Uruchamiam: git pull --rebase origin %BRANCH%
git pull --rebase origin %BRANCH%
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

:help
echo.
echo Uzycie:
echo   git.cmd
echo   git.cmd 1
echo   git.cmd 2
echo   git.cmd 3
echo   git.cmd 4
echo   git.cmd 5
echo   git.cmd check-remote
echo   git.cmd show-remote
echo   git.cmd status-local
echo   git.cmd commit-local "Wiadomosc commita"
echo   git.cmd pull-rebase
echo.
echo Opcje:
echo   1  Sprawdz czy na remote sa nowe commity
echo   2  Wyswietl commity i statystyke plikow z remote
echo   3  Sprawdz lokalne niezatwierdzone zmiany
echo   4  Dodaj i zatwierdz lokalne zmiany
echo   5  Pobierz remote i przebazuj lokalne commity
exit /b 0

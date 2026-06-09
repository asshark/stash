@echo off
chcp 65001 > nul
set PYTHONIOENCODING=utf-8
REM ============================================================================
REM  misstorrentcreator - Windows wrapper for torrent_stash_missing
REM
REM  Usage:
REM    run.bat "C:\path\to\source.torrent" [extra arguments]
REM
REM  Examples:
REM    run.bat "d:\torrents\WUNF.torrent" --studio-id 113
REM    run.bat "d:\torrents\Pierre.torrent" --studio-id 24 --use-ai
REM    run.bat "d:\torrents\Pierre.torrent" --studio-id 24 --use-ai --add-to-qbittorrent
REM
REM  Configure API keys:
REM    1. Open this file in a text editor
REM    2. Paste your key into GROQ_API_KEY (or OPENAI_API_KEY)
REM    3. Save and run with arguments
REM
REM  Groq API key (FREE):  https://console.groq.com/keys
REM  OpenAI key (paid):    https://platform.openai.com/api-keys
REM
REM  Alternative: set keys globally in PowerShell:
REM    [Environment]::SetEnvironmentVariable("GROQ_API_KEY", "gsk_...", "User")
REM ============================================================================

setlocal

REM === AI key: Groq (FREE, recommended) ===
REM Paste your key into the line below. When non-empty, it ALWAYS overrides
REM any value already in the env (so what you see here is what gets used).
set "_GROQ_KEY="
if not "%_GROQ_KEY%"=="" set "GROQ_API_KEY=%_GROQ_KEY%"
set "_GROQ_KEY="

REM === Alternative: OpenAI (PAID) ===
set "_OPENAI_KEY="
if not "%_OPENAI_KEY%"=="" set "OPENAI_API_KEY=%_OPENAI_KEY%"
set "_OPENAI_KEY="

REM === Alternative: OpenRouter (FREE models with :free suffix) ===
set "_OPENROUTER_KEY="
if not "%_OPENROUTER_KEY%"=="" set "OPENROUTER_API_KEY=%_OPENROUTER_KEY%"
set "_OPENROUTER_KEY="

REM === qBittorrent Web UI credentials (optional, used by --add-to-qbittorrent) ===
REM Leave empty if 'Bypass authentication for clients on localhost' is enabled
REM in qBittorrent Preferences -> Web UI.
set "QB_URL=http://localhost:8080"
set "QB_USER=admin"
set "QB_PASS=admin"

REM === Defaults (used when run.bat is called without arguments) ===
set "DEFAULT_TORRENT=d:\Downloads\Torrents\Completed\.torrents\Bums Bus 576p SiteRip - Current as of 13th Feb 2025.torrent"
set "DEFAULT_STUDIO_ID="

REM ----------------------------------------------------------------------------
REM  AI MODEL CHOICE - Edit DEFAULT_EXTRA below to switch.
REM
REM  IMPORTANT: the model MUST be pulled first. Check what you have:
REM    ollama list
REM  Pull anything new with:
REM    ollama pull <model>
REM
REM  Default qwen2.5:3b: ~2 GB VRAM, fits 100%% on most GPUs, fast, best
REM  3B model for structured JSON output (filename parsing).
REM
REM  Other options (pull first!):
REM
REM    llama3.2:3b                ~2 GB VRAM, alternative 3B model
REM    qwen2.5:7b                 ~5 GB VRAM, best 7B-class quality
REM    qwen2.5:14b                ~9 GB VRAM, recommended on 12 GB+ cards
REM    qwen2.5:32b                ~20 GB VRAM, near top-tier
REM    llama3.1:8b                ~5 GB VRAM (the original default)
REM    llama3.1:8b-instruct-q4_0  ~4.7 GB VRAM (tighter fit than default 8B)
REM
REM  Examples:
REM    set "DEFAULT_EXTRA=--use-ai --ai-model qwen2.5:14b"
REM    set "DEFAULT_EXTRA=--use-ai --ai-model llama3.1:8b --ai-batch-size 5"
REM
REM  Quickly check what is loaded and where (CPU vs GPU):
REM    ollama ps
REM
REM  To skip AI completely (only rule-based parsing), drop --use-ai:
REM    set "DEFAULT_EXTRA="
REM ----------------------------------------------------------------------------
set "DEFAULT_EXTRA=--use-ai --ai-model qwen2.5:3b --add-to-qbittorrent"

REM === Show help on /? or --help ===
if /i "%~1"=="/?" goto :showhelp
if /i "%~1"=="--help" goto :showhelp
if /i "%~1"=="-h" goto :showhelp

REM === Run the script ===
REM  Build --studio-id flag only when DEFAULT_STUDIO_ID is non-empty.
REM  Empty studio-id triggers the interactive studio-picker inside the script.
set "STUDIO_ARG="
if not "%DEFAULT_STUDIO_ID%"=="" set "STUDIO_ARG=--studio-id %DEFAULT_STUDIO_ID%"

if "%~1"=="" (
    echo [run.bat] No arguments given, using defaults:
    echo            torrent:   %DEFAULT_TORRENT%
    if "%DEFAULT_STUDIO_ID%"=="" (
        echo            studio-id: ^(none - will prompt interactively^)
    ) else (
        echo            studio-id: %DEFAULT_STUDIO_ID%
    )
    echo            extras:    %DEFAULT_EXTRA%
    echo.
    python "%~dp0torrent_stash_missing.py" "%DEFAULT_TORRENT%" %STUDIO_ARG% %DEFAULT_EXTRA%
    set "EXIT=%ERRORLEVEL%"
) else (
    python "%~dp0torrent_stash_missing.py" %*
    set "EXIT=%ERRORLEVEL%"
)
goto :endbat

:showhelp
echo.
echo Usage:
echo   run.bat                                            -- run with defaults
echo   run.bat "C:\path\to\file.torrent" [extra args]     -- override
echo   run.bat --help                                      -- this help + full options
echo.
echo Defaults:
echo   torrent:   %DEFAULT_TORRENT%
if "%DEFAULT_STUDIO_ID%"=="" (
    echo   studio-id: ^(none - script will prompt interactively^)
) else (
    echo   studio-id: %DEFAULT_STUDIO_ID%
)
echo   extras:    %DEFAULT_EXTRA%
echo.
echo Full Python script options:
python "%~dp0torrent_stash_missing.py" --help
set "EXIT=0"

:endbat

endlocal & exit /b %EXIT%

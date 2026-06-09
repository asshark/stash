# misstorrentcreator

Narzędzie do analizy plików `.torrent` przeciwko bazie Stash — wykrywa,
których klipów brakuje w wybranym studio, których aktorów nie ma jeszcze
w bazie, i opcjonalnie tworzy nowe pliki `.torrent` lub dodaje torrent
do qBittorrent z gotowymi priorytetami plików.

## Pliki

| Plik | Opis |
|---|---|
| `torrent_stash_missing.py` | Główny skrypt |
| `filename_parser_ai.py` | Moduł parsera nazw plików oparty o LLM |
| `run.bat` | Wrapper Windows, ustawia klucze API i uruchamia skrypt |

## Konfiguracja kluczy API (jednorazowo)

### Opcja A — edytuj `run.bat`

Otwórz `run.bat` w edytorze, wklej swój klucz do linii `set "GROQ_API_KEY="`:

```batch
if not defined GROQ_API_KEY set "GROQ_API_KEY=gsk_..."
```

### Opcja B — globalna zmienna środowiskowa (PowerShell, jednorazowo)

```powershell
[Environment]::SetEnvironmentVariable("GROQ_API_KEY", "gsk_...", "User")
```

Po tym możesz uruchamiać `run.bat` z dowolnego okna konsoli bez edycji.

### Skąd wziąć klucz

| Provider | Koszt | URL |
|---|---|---|
| **Groq** (zalecane) | 🆓 FREE tier | https://console.groq.com/keys |
| OpenRouter | 🆓 modele `:free` | https://openrouter.ai/keys |
| OpenAI | 💲 płatne | https://platform.openai.com/api-keys |

Skrypt wybiera dostawcę automatycznie w kolejności: Ollama (jeśli działa
lokalnie) → Groq → OpenAI → OpenRouter.

## Użycie

```batch
REM Najprostsze (z auto-wyborem studia, bez AI)
run.bat "d:\path\source.torrent"

REM Ze wskazanym studio (jeśli znasz ID)
run.bat "d:\path\source.torrent" --studio-id 113

REM Z AI parsowaniem nazw plików
run.bat "d:\path\source.torrent" --studio-id 113 --use-ai

REM Dodaj do qBittorrent z gotowymi priorytetami
run.bat "d:\path\source.torrent" --studio-id 113 --use-ai --add-to-qbittorrent
```

## Domyślne katalogi

| Co | Gdzie |
|---|---|
| Raporty `.txt` / `.json` / `_missing.torrent` | `d:\Downloads\Torrents\Incoming\2download\torrent` |
| Pliki logów | `d:\Downloads\Torrents\Incoming\2download\logs` |
| Cache AI | `d:\Downloads\Torrents\Incoming\2download\cache` |

Można nadpisać przez `--output-dir`, `--log-dir`, `--cache-dir`. Zobacz pełną
listę opcji:

```batch
run.bat
```

(bez argumentów wyświetla pomoc i listę wszystkich flag)

## Diagnostyka AI

Sprawdź, którzy dostawcy są skonfigurowani:

```batch
python filename_parser_ai.py --diagnose
```

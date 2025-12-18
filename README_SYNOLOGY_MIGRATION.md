# Migracja Stash na Synology NAS - Przewodnik

Kompletny zestaw narzędzi i dokumentacji do migracji Stash z Windows na Synology NAS w Docker.

---

## 🎯 Którą metodę wybrać?

### Oficjalny obraz Docker (Zalecane dla większości użytkowników)

**Wybierz jeśli:**
- ✅ Chcesz używać stabilnej, oficjalnej wersji Stash
- ✅ Nie masz zmian w kodzie źródłowym
- ✅ Chcesz łatwe aktualizacje (`docker pull`)
- ✅ Potrzebujesz wsparcia społeczności
- ✅ Preferujesz szybkie wdrożenie (bez budowania)

**📖 Użyj:** `README_MIGRATION.md`

**⏱️ Czas:** ~1-2 godziny

---

### Własny obraz Docker z customizacją

**Wybierz jeśli:**
- ✅ Masz zmodyfikowany kod źródłowy Stash
- ✅ Chcesz testować development branches
- ✅ Potrzebujesz funkcji sprzed oficjalnego release
- ✅ Chcesz pełną kontrolę nad buildem
- ✅ Jesteś developer lub power user

**📖 Użyj:** `README_MIGRATION_CUSTOM_BUILD.md`

**⏱️ Czas:** ~2-3 godziny (+ 15-30 min na build)

---

## 📁 Pliki w tym repozytorium

### Dla obu metod (wspólne):

| Plik | Opis |
|------|------|
| `migrate_database.py` | Skrypt do migracji bazy danych (zamiana ścieżek) |
| `verify_migration.py` | Weryfikacja poprawności migracji |
| `path_mapping.txt` | Template mapowania ścieżek Windows → Linux |

### Dla oficjalnego obrazu:

| Plik | Opis |
|------|------|
| `README_MIGRATION.md` | 📘 **Szczegółowa instrukcja** - START TUTAJ |
| `docker-compose.yml` | Konfiguracja Docker Compose (oficjalny obraz) |

### Dla custom build:

| Plik | Opis |
|------|------|
| `README_MIGRATION_CUSTOM_BUILD.md` | 📗 **Szczegółowa instrukcja custom build** - START TUTAJ |
| `QUICK_START_CUSTOM_BUILD.md` | 🚀 Szybki start dla doświadczonych |
| `docker-compose-custom-build.yml` | Konfiguracja Docker Compose (custom obraz) |
| `build_and_deploy.sh` | Skrypt budowania (Bash/Linux) |
| `build_and_deploy.ps1` | Skrypt budowania (PowerShell/Windows) |

---

## 🚀 Szybki start

### Metoda 1: Oficjalny obraz (Najprostsze)

```bash
# 1. Backup na Windows
cd C:\Users\areks\.stash
mkdir C:\Stash-Backup
copy stash-go.sqlite C:\Stash-Backup\

# 2. Transfer na Synology
scp C:\Stash-Backup\* admin@SYNOLOGY-IP:/volume2/video.xxx.clips/stash/

# 3. Migracja bazy
ssh admin@SYNOLOGY-IP
cd /volume2/video.xxx.clips/stash/database
python3 migrate_database.py stash-go.sqlite path_mapping.txt

# 4. Start Stash
cd /volume1/docker/stash
docker compose up -d
```

**Szczegóły:** Czytaj `README_MIGRATION.md`

---

### Metoda 2: Custom build

```bash
# 1. Build obrazu na Windows
cd S:\MyProjects\stash\stash
.\build_and_deploy.ps1 -Mode windows

# 2. Transfer obrazu
scp stash-custom.tar.gz admin@SYNOLOGY:/volume1/docker/stash/

# 3. Załaduj obraz na Synology
ssh admin@SYNOLOGY
docker load -i /volume1/docker/stash/stash-custom.tar.gz

# 4. Migracja bazy (jak w metodzie 1)
python3 migrate_database.py stash-go.sqlite path_mapping.txt

# 5. Start Stash z custom obrazem
docker compose -f docker-compose-custom-build.yml up -d
```

**Szczegóły:** Czytaj `README_MIGRATION_CUSTOM_BUILD.md`

**Szybka ścieżka:** Czytaj `QUICK_START_CUSTOM_BUILD.md`

---

## 📋 Proces migracji (ogólny)

Niezależnie od wybranej metody, proces wygląda podobnie:

```
┌─────────────────────────────────────────┐
│ 1. PRZYGOTOWANIE                        │
│    - Stop Stash na Windows              │
│    - Backup bazy i config               │
│    - Dokumentacja ścieżek               │
└─────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────┐
│ 2. PRZYGOTOWANIE OBRAZU DOCKER          │
│    Oficjalny: docker pull               │
│    Custom: build + transfer             │
└─────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────┐
│ 3. TRANSFER NA SYNOLOGY                 │
│    - Config files                       │
│    - Database                           │
│    - Plugins                            │
└─────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────┐
│ 4. MIGRACJA BAZY DANYCH                 │
│    - Edycja path_mapping.txt            │
│    - Uruchomienie migrate_database.py   │
│    - Weryfikacja verify_migration.py    │
└─────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────┐
│ 5. KONFIGURACJA DOCKER                  │
│    - Edycja docker-compose.yml          │
│    - Mapowanie volumów                  │
│    - Ustawienie uprawnień               │
└─────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────┐
│ 6. URUCHOMIENIE                         │
│    - docker compose up -d               │
│    - Weryfikacja logów                  │
│    - Test w przeglądarce                │
└─────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────┐
│ 7. WERYFIKACJA                          │
│    - Sprawdzenie bibliotek              │
│    - Test playback                      │
│    - Weryfikacja wtyczek                │
└─────────────────────────────────────────┘
```

---

## 🗺️ Struktura katalogów na Synology

Po migracji będziesz mieć:

```
/volume2/video.xxx.clips/
├── Clips/                          # Twoje media
├── Videos/                         # Twoje media
└── stash/                          # Dane Stash
    ├── config/                     # Konfiguracja
    │   ├── config.yml
    │   ├── plugins/                # Wtyczki Python - edytowalne!
    │   │   └── myplugin/
    │   │       ├── myplugin.yml
    │   │       └── myplugin.py
    │   └── scrapers/               # Scrapers
    ├── database/                   # Baza SQLite
    │   └── stash-go.sqlite
    ├── blobs/                      # Obrazy, okładki (istniejące)
    ├── generated/                  # Generowane preview, thumbnails
    ├── cache/                      # Cache
    └── metadata/                   # Metadane

/volume1/docker/stash/              # Docker config
├── docker-compose.yml              # Dla oficjalnego obrazu
├── docker-compose-custom-build.yml # Dla custom obrazu
└── stash-custom.tar               # Custom obraz (jeśli używasz)
```

---

## ⚙️ Mapowanie ścieżek

Kluczowa koncepcja dla migracji:

| Lokalizacja | Ścieżka | Przykład |
|------------|---------|----------|
| **Windows** | Dysk sieciowy | `L:\Clips` |
| **Synology Filesystem** | Rzeczywista ścieżka | `/volume2/video.xxx.clips/Clips` |
| **Docker Container** | Wewnątrz kontenera | `/data/Clips` |
| **Database** | Zapisana w bazie | `/data/Clips` |

**Jak to działa:**

1. **Windows → Synology Migration:**
   - `path_mapping.txt`: `L:\Clips|/data/Clips`
   - `migrate_database.py` zamienia ścieżki w bazie

2. **Synology → Docker Mapping:**
   - `docker-compose.yml`: 
     ```yaml
     volumes:
       - /volume2/video.xxx.clips/Clips:/data/Clips
     ```

3. **Rezultat:**
   - Stash w kontenerze widzi `/data/Clips`
   - To jest zamapowane do `/volume2/video.xxx.clips/Clips` na Synology
   - Baza zawiera `/data/Clips`
   - Wszystko działa! ✅

---

## 🔧 Zarządzanie wtyczkami Python

Jedna z najważniejszych funkcji: **edycja wtyczek zewnętrznie!**

### Lokalizacja wtyczek:
```
/volume2/video.xxx.clips/stash/config/plugins/
```

### Metody edycji:

**1. Via SMB/CIFS (Windows):**
```
\\YOUR-NAS-IP\volume2\video.xxx.clips\stash\config\plugins\
```
Edytuj w VS Code, Notepad++, itp.

**2. Via File Station (przeglądarka):**
- Otwórz File Station na Synology
- Nawiguj do plugins/
- Edytuj lub upload

**3. Via SSH:**
```bash
ssh admin@YOUR-NAS
nano /volume2/video.xxx.clips/stash/config/plugins/myplugin/myplugin.py
```

**Po każdej edycji:**
```bash
docker compose restart
# lub
docker compose -f docker-compose-custom-build.yml restart
```

---

## 🆘 Pomoc i wsparcie

### Dokumentacja w tym repozytorium:

1. **README_MIGRATION.md** - Oficjalny obraz (szczegółowa instrukcja)
2. **README_MIGRATION_CUSTOM_BUILD.md** - Custom build (szczegółowa instrukcja)
3. **QUICK_START_CUSTOM_BUILD.md** - Custom build (szybki start)
4. Ten plik - Przegląd i wybór metody

### Troubleshooting:

Obie instrukcje zawierają rozbudowane sekcje rozwiązywania problemów:
- Build issues
- Deployment issues
- Database migration issues
- Performance issues
- Plugin issues

### Społeczność Stash:

- **Discord:** https://discord.gg/2TsNFKt
- **Forum:** https://discourse.stashapp.cc
- **GitHub:** https://github.com/stashapp/stash
- **Docs:** https://docs.stashapp.cc

---

## 📊 Porównanie metod

| Aspekt | Oficjalny obraz | Custom build |
|--------|----------------|--------------|
| **Instalacja** | Bardzo prosta | Średnio skomplikowana |
| **Czas wdrożenia** | 1-2h | 2-3h + build |
| **Aktualizacje** | `docker pull` (1 min) | Rebuild (15-30 min) |
| **Stabilność** | Wysoka (testowane) | Zależy od zmian |
| **Custom features** | ❌ Nie | ✅ Tak |
| **Dev branches** | ❌ Nie | ✅ Tak |
| **Wsparcie** | ✅ Pełne community | ⚠️ Self-support |
| **Łatwość utrzymania** | ✅ Bardzo łatwa | ⚠️ Wymaga uwagi |
| **Rozmiar obrazu** | ~450MB (optym.) | ~450-600MB |
| **Python support** | ✅ Wbudowane | ⚠️ Wymaga config |
| **Dla kogo** | Wszyscy użytkownicy | Developers, power users |

### Rekomendacje:

- 🟢 **Nowy użytkownik?** → Oficjalny obraz
- 🟢 **Produkcja?** → Oficjalny obraz
- 🟡 **Testujesz features?** → Custom build
- 🟡 **Masz modyfikacje?** → Custom build
- 🟡 **Developer?** → Custom build

---

## ✅ Checklist przed rozpoczęciem

### Przygotowanie:

- [ ] Docker Desktop zainstalowany na Windows (jeśli custom build)
- [ ] Docker zainstalowany na Synology
- [ ] SSH włączony na Synology
- [ ] Python 3 dostępny na Synology
- [ ] Min. 2GB wolnego RAM na Synology
- [ ] Min. 10GB wolnego miejsca na dysku

### Dokumentacja:

- [ ] Lista wszystkich bibliotek w Windows Stash
- [ ] Ścieżki Windows (np. `L:\Clips`)
- [ ] Ścieżki Synology (np. `/volume2/video.xxx.clips/Clips`)
- [ ] Lista wtyczek do przeniesienia
- [ ] Backup Windows Stash

### Wybór metody:

- [ ] Zdecydowałem: Oficjalny obraz / Custom build
- [ ] Przeczytałem odpowiedni README
- [ ] Rozumiem proces migracji
- [ ] Mam ~2-3 godziny czasu

---

## 🎯 Następne kroki

### Dla oficjalnego obrazu:

1. **Otwórz:** `README_MIGRATION.md`
2. **Przeczytaj sekcję:** Prerequisites
3. **Przygotuj:** Backup Windows installation
4. **Postępuj według:** Step-by-step instructions

### Dla custom build:

1. **Otwórz:** `README_MIGRATION_CUSTOM_BUILD.md`
2. **Lub dla szybkiego start:** `QUICK_START_CUSTOM_BUILD.md`
3. **Przeczytaj sekcję:** Prerequisites
4. **Zdecyduj:** Build on Windows or Synology?
5. **Postępuj według:** Step-by-step instructions

---

## 📞 Kontakt i wsparcie

**Masz pytania?**

1. Sprawdź sekcję Troubleshooting w odpowiednim README
2. Przeszukaj Stash Discord
3. Zadaj pytanie na forum Stash
4. Otwórz issue na GitHub (dla bugów)

**Znalazłeś błąd w dokumentacji?**

- Zgłoś issue
- Lub prześlij pull request

---

## 📄 Licencja

Stash jest open-source (AGPL-3.0).
Ta dokumentacja jest dostarczona "as-is" bez gwarancji.

---

## 🎉 Powodzenia!

Migracja Stash na Synology to świetny krok do lepszej organizacji i dostępności.

**Powodzenia z migracją!** 🚀

---

*Ostatnia aktualizacja: 2025-10-23*

















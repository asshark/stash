# Quick Start: Custom Build Deployment

Skrócona instrukcja dla doświadczonych użytkowników, którzy chcą szybko wdrożyć własny build Stash na Synology.

---

## TL;DR

```bash
# Na Windows:
cd /s/MyProjects/stash/stash
./build_and_deploy.sh windows
scp stash-custom.tar.gz admin@SYNOLOGY:/volume1/docker/stash/

# Na Synology:
cd /volume1/docker/stash
gunzip stash-custom.tar.gz
docker load -i stash-custom.tar
docker compose -f docker-compose-custom-build.yml up -d
```

---

## Szybka ścieżka (30 minut)

### 1. Przygotowanie (5 minut)

```bash
# Windows - sprawdź środowisko
docker info
git status
ls Makefile tools.go

# Backup Windows Stash
cd C:\Users\areks\.stash
mkdir C:\Stash-Backup
copy stash-go.sqlite C:\Stash-Backup\
xcopy /E /I config.yml plugins scrapers C:\Stash-Backup\config\
```

### 2. Build obrazu (15 minut)

**Bash (Git Bash/WSL):**
```bash
cd /s/MyProjects/stash/stash
./build_and_deploy.sh windows
```

**PowerShell:**
```powershell
cd S:\MyProjects\stash\stash
.\build_and_deploy.ps1 -Mode windows
```

### 3. Transfer na Synology (5 minut)

```bash
# Przenieś obraz
scp stash-custom.tar.gz admin@YOUR-NAS-IP:/volume1/docker/stash/

# Przenieś pliki konfiguracyjne
scp -r C:\Stash-Backup\config/* admin@YOUR-NAS-IP:/volume2/video.xxx.clips/stash/config/
scp C:\Stash-Backup\stash-go.sqlite admin@YOUR-NAS-IP:/volume2/video.xxx.clips/stash/database/
```

### 4. Migracja bazy danych (5 minut)

**Edytuj path_mapping.txt:**
```
L:\Clips|/data/Clips
M:\Videos|/data/Videos
```

**Uruchom migrację:**
```bash
# SSH do Synology
ssh admin@YOUR-NAS-IP
cd /volume2/video.xxx.clips/stash/database

# Uruchom skrypt
python3 migrate_database.py stash-go.sqlite path_mapping.txt
# Odpowiedz: yes

# Weryfikuj
python3 verify_migration.py stash-go.sqlite
```

### 5. Wdrożenie (2 minuty)

```bash
# Załaduj obraz
cd /volume1/docker/stash
gunzip stash-custom.tar.gz
docker load -i stash-custom.tar

# Edytuj docker-compose
nano docker-compose-custom-build.yml
# Zmień ścieżki volumów!

# Uruchom
docker compose -f docker-compose-custom-build.yml up -d

# Sprawdź logi
docker compose -f docker-compose-custom-build.yml logs -f
```

### 6. Weryfikacja (3 minuty)

```
http://YOUR-NAS-IP:9999

- Zaloguj się
- Sprawdź biblioteki
- Odtwórz testowy film
- Sprawdź wtyczki
```

---

## Aktualizacja (10 minut)

```bash
# Windows - rebuild
cd /s/MyProjects/stash/stash
git pull  # lub wprowadź zmiany
./build_and_deploy.sh windows
scp stash-custom.tar.gz admin@SYNOLOGY:/volume1/docker/stash/

# Synology - reload
ssh admin@SYNOLOGY
cd /volume1/docker/stash
docker compose -f docker-compose-custom-build.yml down
gunzip -f stash-custom.tar.gz
docker load -i stash-custom.tar
docker compose -f docker-compose-custom-build.yml up -d
```

---

## Mapowanie ścieżek

| Windows | Synology (filesystem) | Docker (container) | Database |
|---------|----------------------|-------------------|----------|
| `L:\Clips` | `/volume2/video.xxx.clips/Clips` | `/data/Clips` | `/data/Clips` |
| `M:\Videos` | `/volume2/video.xxx.clips/Videos` | `/data/Videos` | `/data/Videos` |

**Ważne:**
- W `path_mapping.txt` używaj ścieżek kontenera (np. `/data/Clips`)
- W `docker-compose.yml` mapuj filesystem → container:
  ```yaml
  - /volume2/video.xxx.clips/Clips:/data/Clips
  ```

---

## Struktura katalogów

```
/volume2/video.xxx.clips/stash/
├── config/
│   ├── config.yml
│   ├── plugins/
│   │   └── myplugin/
│   │       ├── myplugin.yml
│   │       └── myplugin.py
│   └── scrapers/
├── database/
│   └── stash-go.sqlite
├── blobs/          (existing)
├── generated/
├── cache/
└── metadata/

/volume1/docker/stash/
├── docker-compose-custom-build.yml
├── stash-custom.tar.gz
└── update-stash.sh
```

---

## Edycja wtyczek

**Via SMB:**
```
\\YOUR-NAS\volume2\video.xxx.clips\stash\config\plugins\
```

**Via SSH:**
```bash
ssh admin@YOUR-NAS
nano /volume2/video.xxx.clips/stash/config/plugins/myplugin/myplugin.py
docker compose -f /volume1/docker/stash/docker-compose-custom-build.yml restart
```

---

## Przydatne komendy

```bash
# Status kontenera
docker compose -f docker-compose-custom-build.yml ps

# Logi (ostatnie 50 linii)
docker compose -f docker-compose-custom-build.yml logs --tail=50

# Logi na żywo
docker compose -f docker-compose-custom-build.yml logs -f

# Restart
docker compose -f docker-compose-custom-build.yml restart

# Stop
docker compose -f docker-compose-custom-build.yml down

# Start
docker compose -f docker-compose-custom-build.yml up -d

# Shell w kontenerze
docker exec -it stash-custom /bin/sh

# Sprawdź wersję
docker exec stash-custom stash --version

# Lista obrazów
docker images | grep stash

# Wyczyść stare obrazy
docker image prune -a
```

---

## Rozwiązywanie problemów

**Build failuje:**
```bash
docker system prune -a  # Wyczyść cache
docker info             # Sprawdź Docker
```

**Kontener się nie uruchamia:**
```bash
docker compose -f docker-compose-custom-build.yml logs  # Sprawdź błędy
docker images | grep stash/custom                        # Czy obraz istnieje?
```

**Pliki nie są widoczne:**
```bash
docker exec -it stash-custom ls /data/Clips  # Sprawdź w kontenerze
```

**Baza danych - ścieżki Windows:**
```bash
cd /volume2/video.xxx.clips/stash/database
python3 verify_migration.py stash-go.sqlite  # Sprawdź status
# Jeśli błędne ścieżki - uruchom migrate_database.py ponownie
```

---

## Backup

```bash
# Baza danych
cp /volume2/video.xxx.clips/stash/database/stash-go.sqlite \
   /volume2/video.xxx.clips/stash/database/stash-go.sqlite.backup.$(date +%Y%m%d)

# Cała konfiguracja
tar -czf /volume2/backups/stash-config-$(date +%Y%m%d).tar.gz \
   /volume2/video.xxx.clips/stash/config/
```

---

## Różnice: Official vs Custom

| Cecha | Official | Custom |
|-------|----------|--------|
| Update | `docker pull` | Rebuild |
| Build time | 0s | 15-30 min |
| Custom features | ❌ | ✅ |
| Dev branches | ❌ | ✅ |
| Support | Community | Self |

---

## Następne kroki

1. **Backup na Windows:**
   ```powershell
   # Zachowaj backup przez 2 tygodnie
   # Potem możesz usunąć Stash z Windows
   ```

2. **Automatyzacja aktualizacji:**
   ```bash
   # Utwórz skrypt update-stash.sh na Synology
   # Zobacz README_MIGRATION_CUSTOM_BUILD.md
   ```

3. **Monitoring:**
   ```bash
   # Dodaj do crontab sprawdzanie zdrowia
   # Automatyczne backupy
   ```

4. **Dokumentacja:**
   ```
   # Zapisz:
   # - Ścieżki mapowania
   # - Customowe zmiany w kodzie
   # - Procedura aktualizacji
   ```

---

## Przydatne linki

- **Szczegółowa instrukcja:** `README_MIGRATION_CUSTOM_BUILD.md`
- **Standardowa migracja:** `README_MIGRATION.md`
- **Build skrypt:** `build_and_deploy.sh` lub `build_and_deploy.ps1`
- **Stash Docs:** https://docs.stashapp.cc
- **Stash GitHub:** https://github.com/stashapp/stash
- **Discord:** https://discord.gg/2TsNFKt

---

## Checklist

- [ ] Docker działa na Windows
- [ ] Source code gotowy
- [ ] Build wykonany (15-30 min)
- [ ] Obraz przeniesiony na Synology
- [ ] Baza danych zmigrowana
- [ ] docker-compose.yml skonfigurowany
- [ ] Kontener uruchomiony
- [ ] Stash dostępny w przeglądarce
- [ ] Biblioteki widoczne
- [ ] Wtyczki działają
- [ ] Backup utworzony

---

**Pytania?** Zobacz pełną dokumentację lub zapytaj na Discord!

















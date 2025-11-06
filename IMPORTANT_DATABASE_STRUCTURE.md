# Ważne: Struktura bazy danych Stash

## Przechowywanie ścieżek w bazie danych

⚠️ **WAŻNE ODKRYCIE:** Stash przechowuje ścieżki w niestandardowy sposób!

### Struktura tabel:

#### Tabela `folders`:
```sql
CREATE TABLE `folders` (
  `id` integer PRIMARY KEY,
  `path` varchar(255) NOT NULL,              -- PEŁNA ŚCIEŻKA DO FOLDERU
  `parent_folder_id` integer,
  `mod_time` datetime,
  `created_at` datetime,
  `updated_at` datetime
);
```

**Przykład:**
- `path`: `/data/Clips/Scene1/`

#### Tabela `files`:
```sql
CREATE TABLE `files` (
  `id` integer PRIMARY KEY,
  `basename` varchar(255) NOT NULL,          -- TYLKO NAZWA PLIKU (bez ścieżki!)
  `parent_folder_id` integer NOT NULL,       -- Odniesienie do folders
  `zip_file_id` integer,
  `size` integer,
  `mod_time` datetime,
  `created_at` datetime,
  `updated_at` datetime
);
```

**Przykład:**
- `basename`: `video.mp4`
- `parent_folder_id`: `123` (odniesienie do folderu w tabeli `folders`)

### Pełna ścieżka do pliku:

Pełna ścieżka jest **konstruowana dynamicznie**:
```
folders.path + files.basename = pełna ścieżka
/data/Clips/Scene1/ + video.mp4 = /data/Clips/Scene1/video.mp4
```

## Konsekwencje dla migracji:

### ✅ CO TRZEBA MIGROWAĆ:
- **Tylko tabela `folders`** - kolumna `path`
- Zawiera pełne ścieżki do folderów

### ❌ CZEGO NIE TRZEBA MIGROWAĆ:
- **Tabela `files`** - kolumna `basename`
- Zawiera tylko nazwy plików (bez ścieżek)
- Nie wymaga konwersji Windows → Linux

## Przykład migracji:

### Przed migracją:
**folders:**
| id  | path                    |
|-----|-------------------------|
| 1   | `L:\Clips\Scene1\`      |
| 2   | `L:\Clips\Scene2\`      |
| 3   | `M:\Videos\Movies\`     |

**files:**
| id  | basename      | parent_folder_id |
|-----|---------------|------------------|
| 10  | `video1.mp4`  | 1                |
| 11  | `video2.mp4`  | 1                |
| 12  | `movie1.mkv`  | 3                |

### Po migracji:
**folders:**
| id  | path                    |
|-----|-------------------------|
| 1   | `/data/Clips/Scene1/`   |
| 2   | `/data/Clips/Scene2/`   |
| 3   | `/data/Videos/Movies/`  |

**files:** (BEZ ZMIAN!)
| id  | basename      | parent_folder_id |
|-----|---------------|------------------|
| 10  | `video1.mp4`  | 1                |
| 11  | `video2.mp4`  | 1                |
| 12  | `movie1.mkv`  | 3                |

## Jak to działa w Stash:

Gdy Stash potrzebuje pełnej ścieżki do pliku:

```go
// W kodzie Stash:
fullPath := folder.Path + "/" + file.Basename
// Np: /data/Clips/Scene1/ + video1.mp4 = /data/Clips/Scene1/video1.mp4
```

## Co to oznacza dla użytkownika:

1. **Migracja jest prostsza:** Tylko foldery, nie pliki!
2. **Mniej danych do aktualizacji:** Znacznie mniej wierszy w `folders` niż w `files`
3. **Szybsza migracja:** Nie trzeba przetwarzać milionów plików
4. **Mniej miejsca na błąd:** Tylko jedna tabela do zmiany

## Zmodyfikowane skrypty:

### `migrate_database.py`:
- ✅ Migruje **tylko** tabelę `folders`
- ⏭️ Pomija tabelę `files` (tylko zlicza dla statystyk)
- 📊 Poprawne raportowanie

### `verify_migration.py`:
- ✅ Weryfikuje **tylko** tabelę `folders`
- ⏭️ Zlicza pliki ale nie szuka w nich ścieżek Windows
- 📊 Poprawny komunikat o sukcesie

## Podsumowanie:

| Aspekt | Szczegóły |
|--------|-----------|
| **Tabela do migracji** | `folders` (kolumna `path`) |
| **Tabela do pominięcia** | `files` (kolumna `basename`) |
| **Typy ścieżek** | Pełne ścieżki tylko w `folders` |
| **Konstrukcja pełnej ścieżki** | `folders.path + files.basename` |
| **Czas migracji** | Krótsz y - mniej wierszy do aktualizacji |

---

**Data odkrycia:** 2025-10-23
**Wersja Stash:** v0.27+ (od migracji 32 - files system)




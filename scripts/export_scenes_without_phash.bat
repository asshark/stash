@echo off
sqlite3 stash-go.sqlite -header -csv "SELECT s.id, s.title, f.path FROM scenes s JOIN scenes_files sf ON s.id = sf.scene_id JOIN files f ON sf.file_id = f.id LEFT JOIN files_fingerprints ff ON f.id = ff.file_id AND ff.type = 'phash' WHERE ff.fingerprint IS NULL;" > scenes_without_phash.csv
echo Exported to scenes_without_phash.csv
pause














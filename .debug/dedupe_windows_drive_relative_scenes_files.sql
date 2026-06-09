-- Remove duplicate scene file links where the same video exists twice:
-- one under a Windows drive-RELATIVE stored path (e.g. "u:Clips\..." — missing '\' after drive letter)
-- and one under a canonical path (e.g. "u:\Clips\...").
-- Keeps the canonical row; deletes the drive-relative row.
-- Matches duplicates by oshash fingerprint + same basename; only non-zip files.

BEGIN IMMEDIATE;

DROP TABLE IF EXISTS _dedupe_bad_files;
CREATE TEMP TABLE _dedupe_bad_files AS
SELECT
  sf_bad.scene_id AS scene_id,
  sf_bad.file_id AS bad_fid,
  MIN(sf_good.file_id) AS good_fid
FROM scenes_files AS sf_bad
INNER JOIN files AS f_bad ON f_bad.id = sf_bad.file_id
INNER JOIN folders AS fol_bad ON fol_bad.id = f_bad.parent_folder_id
INNER JOIN files_fingerprints AS fp_bad
  ON fp_bad.file_id = f_bad.id AND fp_bad.type = 'oshash'
INNER JOIN scenes_files AS sf_good
  ON sf_good.scene_id = sf_bad.scene_id AND sf_good.file_id != sf_bad.file_id
INNER JOIN files AS f_good ON f_good.id = sf_good.file_id
INNER JOIN folders AS fol_good ON fol_good.id = f_good.parent_folder_id
INNER JOIN files_fingerprints AS fp_good
  ON fp_good.file_id = f_good.id AND fp_good.type = 'oshash'
WHERE
  f_bad.zip_file_id IS NULL
  AND f_good.zip_file_id IS NULL
  AND f_bad.basename = f_good.basename
  AND fp_bad.fingerprint = fp_good.fingerprint
  AND LENGTH(fol_bad.path) >= 3
  AND SUBSTR(fol_bad.path, 2, 1) = ':'
  AND SUBSTR(fol_bad.path, 3, 1) NOT IN (CHAR(92), CHAR(47))
  AND NOT (
    LENGTH(fol_good.path) >= 3
    AND SUBSTR(fol_good.path, 2, 1) = ':'
    AND SUBSTR(fol_good.path, 3, 1) NOT IN (CHAR(92), CHAR(47))
  )
GROUP BY sf_bad.scene_id, sf_bad.file_id;

-- Clear primary on drive-relative duplicates first, so _need_primary sees scenes with no primary.
UPDATE scenes_files
SET [primary] = 0
WHERE (scene_id, file_id) IN (
  SELECT scene_id, bad_fid FROM _dedupe_bad_files
);

DROP TABLE IF EXISTS _need_primary;
CREATE TEMP TABLE _need_primary AS
SELECT d.scene_id, MIN(d.good_fid) AS good_fid
FROM _dedupe_bad_files AS d
WHERE NOT EXISTS (
  SELECT 1
  FROM scenes_files AS x
  WHERE x.scene_id = d.scene_id AND x.[primary] = 1
)
GROUP BY d.scene_id;

UPDATE scenes_files
SET [primary] = 1
WHERE (scene_id, file_id) IN (
  SELECT scene_id, good_fid FROM _need_primary
);

DELETE FROM scenes_files
WHERE (scene_id, file_id) IN (
  SELECT scene_id, bad_fid FROM _dedupe_bad_files
);

COMMIT;

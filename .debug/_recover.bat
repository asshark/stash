@echo off
set SQLITE=%TEMP%\sqlite_tools\sqlite3.exe
set DIR=%USERPROFILE%\.stash\bin
cd /d "%DIR%"
echo Odzyskiwanie danych z clips.CORRUPT_20260727_0940 ...
"%SQLITE%" clips.CORRUPT_20260727_0940 ".recover --ignore-freelist" > recover.sql 2> recover.err
echo exit=%ERRORLEVEL%
dir recover.sql recover.err

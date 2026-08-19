@echo off
set SQLITE=%TEMP%\sqlite_tools\sqlite3.exe
set DIR=%USERPROFILE%\.stash\bin
cd /d "%DIR%"
if exist clips_recovered del clips_recovered
echo Budowanie clips_recovered z recover.sql ...
"%SQLITE%" clips_recovered ".read recover.sql" > rebuild.log 2> rebuild.err
echo exit=%ERRORLEVEL%
dir clips_recovered rebuild.err

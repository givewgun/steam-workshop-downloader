@echo off
cd /d "%~dp0"
echo Steam Workshop Downloader - choose any game by Steam App ID.
echo Enter passwords and Steam Guard codes only in SteamCMD.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0download-mods.ps1" %*
set "result=%errorlevel%"
pause
exit /b %result%

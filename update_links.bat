@echo off
cd /d "%~dp0"
set "PY=python"
if exist "%~dp0python\python.exe" set "PY=%~dp0python\python.exe"
echo Updating the link downloaders. Twitch/YouTube change often;
echo run this if links stop working.
"%PY%" -m pip install -U --disable-pip-version-check --no-warn-script-location yt-dlp curl_cffi
pause

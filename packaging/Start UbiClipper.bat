@echo off
rem Starts UbiClipper without a console window.
rem Files unzipped from a download carry Windows' "from the internet" mark, which
rem makes Smart App Control block them. The first start removes that mark
rem (the same as Properties - Unblock on the zip).
if not exist "%~dp0.unblocked" (
  powershell -NoProfile -Command "Get-ChildItem -LiteralPath '%~dp0' -Recurse -File | Unblock-File" >nul 2>nul
  echo ok> "%~dp0.unblocked"
)
start "" "%~dp0python\pythonw.exe" "%~dp0app.py"

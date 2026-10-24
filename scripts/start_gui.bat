@echo off
rem Startet die AI-Mix-Engineer-Oberflaeche (nach scripts\install_windows.ps1)
cd /d "%~dp0\.."
if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" -m app gui
) else (
  echo Python-Umgebung fehlt. Bitte zuerst: powershell -ExecutionPolicy Bypass -File scripts\install_windows.ps1
  pause
)

@echo off
rem Double-click to start the Quotex Trade Engine (the same as `npm start`).
cd /d "%~dp0"
where uv >nul 2>nul
if errorlevel 1 (
  echo uv is not installed. Install it from https://docs.astral.sh/uv/ and run this again.
  pause
  exit /b 1
)
uv run --directory backend python -m scripts.start %*
if errorlevel 1 pause

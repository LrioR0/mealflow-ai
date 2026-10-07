@echo off
REM MealFlow dev launcher: backend (apps/api, --reload) + frontend (apps/web)
REM Usage: double-click, or run from repo root. Close the two popped-up windows to stop.
start "MealFlow API 8000" cmd /k "cd /d %~dp0apps\api && ..\..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000"
start "MealFlow Web 5173" cmd /k "cd /d %~dp0apps\web && npm run dev"
echo Backend :8000 and frontend :5173 are starting in new windows.
echo Open http://localhost:5173 in your browser.

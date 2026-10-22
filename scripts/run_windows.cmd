@echo off
setlocal
cd /d "%~dp0.."

if not exist ".venv\Scripts\python.exe" (
    echo [1/5] Creating virtual environment...
    py -3 -m venv .venv || goto :error
)

echo [2/5] Installing core requirements...
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :error

echo [3/5] Starting PostgreSQL (Docker)...
docker compose up -d || goto :error

echo [4/5] Waiting for the database...
".venv\Scripts\python.exe" scripts\wait_for_db.py || goto :error

echo [5/5] Starting API and UI...
start "Voice Property API" ".venv\Scripts\python.exe" -m uvicorn app:app --host 127.0.0.1 --port 8000
start "Voice Property UI" ".venv\Scripts\python.exe" -m streamlit run frontend\streamlit_app.py --server.port 8501

echo.
echo API: http://127.0.0.1:8000/docs
echo UI : http://127.0.0.1:8501
exit /b 0

:error
echo.
echo Setup failed. See SETUP.md for troubleshooting.
exit /b 1

@echo off
REM One-click local deployment for Windows: installs on first run, then starts the app.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Creating virtual environment...
  python -m venv .venv || goto :err
  .venv\Scripts\pip install -r requirements.txt || goto :err
)
if not exist .env (
  copy .env.example .env >nul
  echo Add your GEMINI_API_KEY to .env, then run start.bat again.
  notepad .env
  exit /b 1
)
if not exist data\chroma (
  echo First run: building knowledge base and profiles, about 5-10 minutes...
  .venv\Scripts\python scripts\setup.py || goto :err
)
echo Starting SecurityPolicy AI at http://localhost:8000
start "" http://localhost:8000
.venv\Scripts\python -m uvicorn spai.api:app --host 127.0.0.1 --port 8000
exit /b 0
:err
echo Setup failed. See the messages above.
exit /b 1

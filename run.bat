@echo off
title GEM Tender Intelligence System - Launcher
color 0B
cd /d "%~dp0"

echo.
echo  =============================================================
echo   G E M   T E N D E R   I N T E L L I G E N C E   S Y S T E M
echo  =============================================================
echo             * All-in-One Automated Runtime Launcher *
echo  =============================================================
echo.

:: ── 1. Detect Python ─────────────────────────────────────────────
echo  [1/9] Detecting Python installation...
set "PY_CMD="

python --version >nul 2>&1
if %errorlevel% equ 0 (
    set "PY_CMD=python"
    goto :py_found
)
py --version >nul 2>&1
if %errorlevel% equ 0 (
    set "PY_CMD=py"
    goto :py_found
)
python3 --version >nul 2>&1
if %errorlevel% equ 0 (
    set "PY_CMD=python3"
    goto :py_found
)

echo  [ERROR] Python was not found in your PATH.
echo          Please install Python 3.10+ and check 'Add to PATH' during setup.
echo          Download: https://www.python.org/downloads/
echo.
pause
exit /b 1

:py_found
for /f "tokens=*" %%i in ('%PY_CMD% --version') do set "PY_VER=%%i"
echo        %PY_VER% detected successfully.

:: ── 2. Initialize Virtual Environment ────────────────────────────
echo  [2/9] Checking Python virtual environment (.venv)...
if exist ".venv\Scripts\python.exe" (
    rem Quick check if the python.exe is valid
    .venv\Scripts\python.exe --version >nul 2>&1
    if errorlevel 1 (
        echo Existing virtual environment is broken. Recreating...
        rmdir /s /q .venv
        goto :create_venv
    )
    goto :venv_exists
)
:create_venv

echo        Virtual environment not found. Setting it up now...
%PY_CMD% -m venv .venv
if errorlevel 1 goto :venv_fail
echo  [OK] Created .venv virtual environment.

echo  [INFO] Upgrading pip and installing build tools...
.venv\Scripts\python.exe -m pip install --upgrade pip --disable-pip-version-check -q
.venv\Scripts\python.exe -m pip install wheel setuptools --disable-pip-version-check -q

echo  [INFO] Installing project dependencies (this may take a few minutes)...
.venv\Scripts\python.exe -m pip install -r backend\requirements.txt --disable-pip-version-check
if errorlevel 1 goto :venv_fail
echo  [OK] Dependencies installed successfully.
goto :venv_exists

:venv_fail
echo  [ERROR] Failed to set up virtual environment.
pause
exit /b 1

:venv_exists
echo        Virtual environment .venv detected.

:: Define environment-specific python executor
set "PY_EXE=%~dp0.venv\Scripts\python.exe"

:: ── 3. Configure Environment File (.env) ─────────────────────────
echo  [3/9] Validating environment configuration (.env)...
if exist ".env" goto :env_ok
if exist ".env.example" goto :copy_env

echo STRICT_OPEN_SOURCE=true> .env
echo LLM_PROVIDER=ollama>> .env
echo OLLAMA_URL=http://localhost:11434/api/generate>> .env
echo OLLAMA_MODEL=llama3.1:8b>> .env
echo MONGO_URL=mongodb://127.0.0.1:27017/gem_tender>> .env
echo REDIS_URL=redis://localhost:6379/0>> .env
echo ENABLE_DOCS=true>> .env
echo AUTH_BYPASS_ENABLED=false>> .env
"%PY_EXE%" -c "import secrets; print(f'JWT_SECRET_KEY={secrets.token_hex(32)}')" >> .env
echo        Generated new .env configuration file.
goto :env_ok

:copy_env
copy ".env.example" ".env" >nul
echo        Created .env configuration from .env.example
goto :env_ok

:env_ok
echo        .env configuration file detected.

:: ── 4. Locate External System Tools (Tesseract) ─────────────────
echo  [4/9] Scanning local system paths for OCR tools...
where tesseract >nul 2>&1
if %errorlevel% equ 0 (
    echo        Tesseract OCR is active in PATH.
    goto :tesseract_ok
)
if exist "C:\Program Files\Tesseract-OCR\tesseract.exe" (
    set "PATH=C:\Program Files\Tesseract-OCR;%PATH%"
    echo        Tesseract OCR added to local PATH.
    goto :tesseract_ok
)
echo        [WARNING] Tesseract OCR not found. PDF OCR features will run in degraded fallback mode.

:tesseract_ok

:: ── 5. Start Ollama Service and Models ───────────────────────────
echo  [5/9] Checking Ollama local AI server...
netstat -ano | findstr ":11434" | findstr "LISTENING" >nul 2>&1
if %errorlevel% equ 0 goto :ollama_running

echo        Ollama server is offline. Launching background service...
start /B "" ollama serve
ping 127.0.0.1 -n 5 >nul

:ollama_running
echo        Ollama server is active on port 11434.

:: Extract model name from .env (fallback to llama3.1:8b)
set "OLLAMA_MODEL=llama3.1:8b"
for /f "tokens=2 delims==" %%i in ('findstr "OLLAMA_MODEL" .env 2^>nul') do set "OLLAMA_MODEL=%%i"
set OLLAMA_MODEL=%OLLAMA_MODEL: =%
set OLLAMA_MODEL=%OLLAMA_MODEL:"=%
set OLLAMA_MODEL=%OLLAMA_MODEL:'=%

echo        Checking configured LLM model: %OLLAMA_MODEL%
ollama list 2>nul | findstr /i "%OLLAMA_MODEL%" >nul 2>&1
if %errorlevel% equ 0 goto :model_ok

echo        LLM model "%OLLAMA_MODEL%" not found locally. Pulling now...
ollama pull %OLLAMA_MODEL%

:model_ok
echo        LLM model "%OLLAMA_MODEL%" is ready.

:: ── 6. Start Local MongoDB ───────────────────────────────────────
echo  [6/9] Verifying database listener (MongoDB)...
netstat -ano | findstr ":27017" | findstr "LISTENING" >nul 2>&1
if %errorlevel% equ 0 (
    echo        MongoDB is already running on port 27017.
    goto :mongodb_ok
)

echo        MongoDB not running on port 27017. Scanning binary executable...
set "MONGOD_BIN="
if exist "C:\Program Files\MongoDB\Server\7.0\bin\mongod.exe" (
    set "MONGOD_BIN=C:\Program Files\MongoDB\Server\7.0\bin\mongod.exe"
)
if not "%MONGOD_BIN%"=="" goto :mongod_found
if exist "C:\Program Files\MongoDB\Server\6.0\bin\mongod.exe" (
    set "MONGOD_BIN=C:\Program Files\MongoDB\Server\6.0\bin\mongod.exe"
)
if not "%MONGOD_BIN%"=="" goto :mongod_found

where mongod >nul 2>&1
if %errorlevel% neq 0 goto :mongodb_not_found
for /f "tokens=*" %%i in ('where mongod') do set "MONGOD_BIN=%%i"

:mongod_found
echo        Starting MongoDB using local data directory "%~dp0mongodb_data"...
if not exist "%~dp0mongodb_data" mkdir "%~dp0mongodb_data"
start /B "" "%MONGOD_BIN%" --dbpath "%~dp0mongodb_data" --port 27017 --bind_ip 127.0.0.1 --logpath "%~dp0mongodb_data\mongod.log" --logappend

:: Wait 4 seconds for DB to spin up
ping 127.0.0.1 -n 5 >nul

netstat -ano | findstr ":27017" | findstr "LISTENING" >nul 2>&1
if %errorlevel% equ 0 (
    echo        MongoDB started successfully.
) else (
    echo        [WARNING] Failed to bind local MongoDB. Running backend in degraded mode.
)
goto :mongodb_ok

:mongodb_not_found
echo        [WARNING] mongod.exe was not found in standard paths.
echo                  App will run in degraded mode unless MongoDB is started manually on port 27017.

:mongodb_ok

:: ── 7. Verify Database Schemas ───────────────────────────────────
echo  [7/9] Running database migrations and schema checks...
cd backend
"%PY_EXE%" -c "from database import Base; Base.metadata.create_all(); print('        Database schema verification complete.')"
cd ..

:: ── 8. Check Redis Cache (Optional) ──────────────────────────────
echo  [8/9] Checking Redis cache connection...
netstat -ano | findstr ":6379" | findstr "LISTENING" >nul 2>&1
if %errorlevel% equ 0 (
    echo        Redis service detected. LLM fast caching enabled.
) else (
    echo        Redis offline. LLM responses will use local file caching.
)

:: ── 9. Launch FastAPI Backend ────────────────────────────────────
echo  [9/9] Booting GEM Backend Server...

:: Release port 8000 if occupied
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8000" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
)
ping 127.0.0.1 -n 2 > nul

:: Open browser after a longer delay, but do it in background so it doesn't block
start "" cmd /c "timeout /t 8 /nobreak >nul & start http://127.0.0.1:8000/app/index.html"

echo.
echo  =============================================================
echo   SYSTEM BOOTING SUCCESSFULLY!
echo   -------------------------------------------------------------
echo   Backend URL:  http://127.0.0.1:8000
echo   API Docs:     http://127.0.0.1:8000/docs
echo   Ecosystem:    http://127.0.0.1:8000/app/index.html
echo  =============================================================
echo.
echo  Press Ctrl+C to terminate the application.
echo.

cd backend
"%PY_EXE%" -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
pause
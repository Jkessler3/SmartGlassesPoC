@echo off
setlocal enabledelayedexpansion

REM --- pick python: prefer 3.13 if installed, else default py ---
set "PY=py"
py -3.13 -c "import sys; print(sys.version)" >nul 2>&1
if %errorlevel%==0 set "PY=py -3.13"

echo Using: %PY%
%PY% -c "import sys; print('Python:', sys.version); print('Version:', sys.version_info[:3])"

REM --- warn if Python 3.14+ because opencv wheels may not exist ---
%PY% -c "import sys; exit(0 if sys.version_info[:2] <= (3,13) else 1)"
if not %errorlevel%==0 (
  echo.
  echo WARNING: Python 3.14+ detected.
  echo opencv-python wheels officially support up to Python 3.13.
  echo If install fails, install Python 3.13 and re-run INSTALL.bat
  echo.
)

REM --- create venv ---
if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  %PY% -m venv .venv
  if not %errorlevel%==0 (
    echo ERROR: venv creation failed.
    pause
    exit /b 1
  )
)

echo Upgrading pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip

echo Installing dependencies...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if not %errorlevel%==0 (
  echo.
  echo ERROR: pip install failed.
  echo If you are on Python 3.14, install Python 3.13 and try again.
  echo.
  pause
  exit /b 1
)

echo.
echo INSTALL OK.
echo Next: double-click RUN.bat
echo.
pause
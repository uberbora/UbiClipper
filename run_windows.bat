@echo off
cd /d "%~dp0"
rem Only run pip when requirements changed since the last successful install
fc /b requirements.txt .installed_requirements >nul 2>nul
if errorlevel 1 (
  echo Installing requirements...
  python -m pip install -q --disable-pip-version-check -r requirements.txt
  if errorlevel 1 (
    echo.
    echo Installing requirements failed - see the message above.
    pause
    exit /b 1
  )
  copy /y requirements.txt .installed_requirements >nul
)
fc /b requirements-optional.txt .installed_optional >nul 2>nul
if errorlevel 1 (
  echo Installing optional extras ^(drag and drop, Kick/Twitch helper^)...
  python -m pip install -q --disable-pip-version-check -r requirements-optional.txt
  copy /y requirements-optional.txt .installed_optional >nul
)
where nvidia-smi >nul 2>nul
if not errorlevel 1 (
  fc /b requirements-gpu.txt .installed_gpu >nul 2>nul
  if errorlevel 1 (
    echo Installing NVIDIA libraries...
    python -m pip install -q --disable-pip-version-check -r requirements-gpu.txt && copy /y requirements-gpu.txt .installed_gpu >nul
  )
)
if not exist .models_ok (
  echo.
  echo Downloading the AI models once ^(about 6 GB^). This can take a while...
  python get_models.py
  if not errorlevel 1 echo ok> .models_ok
)
python app.py
if errorlevel 1 pause

@echo off
cd /d "%~dp0"
echo Installing NVIDIA CUDA libraries for GPU subtitles (about 1 GB, one time)...
python -m pip install --disable-pip-version-check -r requirements-gpu.txt
echo.
python check_setup.py
pause

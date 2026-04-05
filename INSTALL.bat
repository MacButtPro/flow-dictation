@echo off
setlocal
title Flow — Installer
cd /d "%~dp0flow_ui"

echo.
echo  ============================================================
echo   Flow — Dependency Installer
echo  ============================================================
echo.

REM ── Check Python ──────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo  ERROR: Python not found.
    echo  Please install Python 3.10+ from https://www.python.org/downloads/
    echo  Make sure to check "Add Python to PATH" during install.
    pause
    exit /b 1
)

for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PY_VER=%%v
echo  Python %PY_VER% found.
echo.

REM ── Detect NVIDIA GPU ─────────────────────────────────────────
nvidia-smi >nul 2>&1
if errorlevel 1 (
    echo  No NVIDIA GPU detected — installing CPU-only PyTorch.
    echo.
    pip install torch --index-url https://download.pytorch.org/whl/cpu
) else (
    echo  NVIDIA GPU detected — installing CUDA 12.1 PyTorch.
    echo  ^(This is a large download: ~2.5 GB^)
    echo.
    pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
)

echo.
echo  Installing remaining dependencies...
echo.
pip install -r requirements.txt

if errorlevel 1 (
    echo.
    echo  ERROR: Some packages failed to install.
    echo  Check the output above for details.
    pause
    exit /b 1
)

echo.
echo  ============================================================
echo   Installation complete!
echo   Run LAUNCH_FLOW.bat to start Flow.
echo  ============================================================
echo.
pause

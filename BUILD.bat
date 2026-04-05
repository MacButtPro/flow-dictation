@echo off
setlocal
title Flow — Build
cd /d "%~dp0flow_ui"

echo.
echo  ============================================================
echo   Flow — Build Script
echo  ============================================================
echo.

REM ── 1. Check Python ───────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo  ERROR: Python not found. Run INSTALL.bat first.
    pause & exit /b 1
)

REM ── 2. Check / install PyInstaller (do NOT auto-upgrade) ──────
python -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo  Installing PyInstaller...
    pip install pyinstaller
    if errorlevel 1 ( echo  ERROR: Could not install PyInstaller. & pause & exit /b 1 )
)

REM ── 3. Check required packages ────────────────────────────────
echo  Checking required packages...
python -c "import PyQt6, whisper, pyaudio, pyperclip" 2>&1
if errorlevel 1 (
    echo.
    echo  ERROR: Missing packages. Run INSTALL.bat first.
    pause & exit /b 1
)
echo  All packages found.
echo.

REM ── 4. Ensure flow_config.json exists ─────────────────────────
if not exist "flow_config.json" (
    python -c "import json; open('flow_config.json','w').write(json.dumps({}))"
)

REM ── 5. Clean previous build ───────────────────────────────────
echo  Cleaning previous build...
rmdir /s /q build 2>nul
rmdir /s /q dist  2>nul
del Flow.spec     2>nul
del flow.spec     2>nul

echo.
echo  Building — this takes 5-15 minutes, please wait...
echo  Output is being saved to build_log.txt
echo.

REM ── 6. Build (log saved to build_log.txt via PowerShell Tee) ──
powershell -Command "& python -m PyInstaller --name 'Flow' --windowed --onedir --icon 'flow_icon.ico' --add-data 'flow_icon.ico;.' --add-data 'flow_config.json;.' --hidden-import 'comtypes.stream' --hidden-import 'comtypes.client' --hidden-import 'comtypes.server' --hidden-import 'comtypes.typeinfo' --hidden-import 'winreg' --hidden-import 'pyaudio' --hidden-import 'pyperclip' --hidden-import 'PyQt6.sip' --collect-all 'whisper' --exclude-module 'PyQt5' --exclude-module 'PySide2' --exclude-module 'PySide6' --noconfirm flow_ui.py 2>&1 | Tee-Object -FilePath build_log.txt; exit $LASTEXITCODE"

if errorlevel 1 (
    echo.
    echo  ============================================================
    echo   BUILD FAILED — last 30 lines of build_log.txt:
    echo  ============================================================
    powershell -Command "Get-Content build_log.txt | Select-Object -Last 30"
    echo.
    echo  Full log saved to: flow_ui\build_log.txt
    echo  ============================================================
    pause & exit /b 1
)

REM ── 7. Remove bundled config so users get a clean first run ───
del "dist\Flow\flow_config.json" 2>nul
del "dist\Flow\_internal\flow_config.json" 2>nul

echo.
echo  ============================================================
echo   BUILD COMPLETE
echo   Test it:   dist\Flow\Flow.exe
echo  ============================================================
echo.

REM ── 8. Build installer if Inno Setup is installed ─────────────
cd /d "%~dp0"
set ISCC=
for %%P in (
    "%ProgramFiles(x86)%\Inno Setup 6\iscc.exe"
    "%ProgramFiles%\Inno Setup 6\iscc.exe"
) do ( if exist %%P set ISCC=%%P )

if defined ISCC (
    echo  Building installer...
    %ISCC% "Flow_Setup.iss"
    if not errorlevel 1 (
        echo.
        echo  Installer ready: installer_output\Flow_Setup.exe
    )
) else (
    echo  Tip: Install Inno Setup 6 from jrsoftware.org to auto-build
    echo  the setup wizard installer next time.
)

echo.
pause

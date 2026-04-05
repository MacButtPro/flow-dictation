@echo off
echo ════════════════════════════════════════════════
echo   Flow E2E Test Suite
echo ════════════════════════════════════════════════
echo.
echo  This will:
echo    - Launch Flow automatically
echo    - Simulate keypresses to test recording
echo    - Test hotkey changes
echo    - Check for errors in logs
echo    - Save results to test_flow_e2e_results.txt
echo.
echo  Do NOT touch your keyboard or mouse during the test.
echo  It takes about 30 seconds.
echo.
pause
cd /d "%~dp0"
python test_flow_e2e.py

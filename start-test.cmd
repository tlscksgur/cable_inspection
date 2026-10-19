@echo off
cd /d "%~dp0"
python test_service.py %*
pause

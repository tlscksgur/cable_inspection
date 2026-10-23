@echo off
cd /d "%~dp0"
python -X utf8 public_inspection.py --port 7777 %*

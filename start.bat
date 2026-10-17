@echo off
rem Windows: double-click to open Grok Collab Room.
cd /d "%~dp0"
where py >nul 2>nul && (py -3 backend\server.py --open %* & goto :eof)
where python >nul 2>nul && (python backend\server.py --open %* & goto :eof)
echo Python 3.9+ is required: https://www.python.org/downloads/
pause

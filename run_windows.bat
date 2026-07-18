@echo off
REM Double-click to run the Loaner Payment Sheet generator on this PC.
REM Requires Python from https://www.python.org/downloads/ (check "Add to PATH").
cd /d "%~dp0"
py -m pip install --quiet -r requirements.txt
start "" http://localhost:5000
py -m loaner_platform.webapp
pause

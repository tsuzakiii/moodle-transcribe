@echo off
REM Launch GUI without console window (Windows)
set ROOT=%~dp0..
start "" "%ROOT%\.venv\Scripts\pythonw.exe" -m moodle_transcribe.gui

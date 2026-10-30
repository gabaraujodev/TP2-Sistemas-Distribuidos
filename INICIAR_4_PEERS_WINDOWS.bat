@echo off
cd /d "%~dp0"
where py >nul 2>&1
if %ERRORLEVEL%==0 (
    py scripts\run_config.py config\4_peers.json
) else (
    python scripts\run_config.py config\4_peers.json
)
pause

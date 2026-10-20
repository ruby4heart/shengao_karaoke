@echo off
setlocal
cd /d "%~dp0.."
call "%~dp0environment.cmd"
if errorlevel 1 exit /b 1
python scripts\apply-studio.py
if errorlevel 1 exit /b 1
python -m mesonbuild.mesonmain compile -C build\baseline -j 6
exit /b %ERRORLEVEL%

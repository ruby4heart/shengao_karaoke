@echo off
setlocal
cd /d "%~dp0.."
call "%~dp0environment.cmd"
if errorlevel 1 exit /b 1
python -m mesonbuild.mesonmain setup build\baseline vendor\aegisub --buildtype=release -Ddefault_library=static -Dtests=true -Dfftw3=disabled -Dhunspell=disabled -Duchardet=disabled -Dcsri=disabled -Denable_update_checker=false -Dffmpeg:programs=enabled -Dffmpeg:ffplay=disabled -Dffmpeg:ffprobe=disabled -Dffmpeg:libass=enabled
exit /b %ERRORLEVEL%

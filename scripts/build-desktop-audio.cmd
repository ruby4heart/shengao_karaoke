@echo off
setlocal
cd /d "%~dp0.."
call scripts\environment.cmd >nul
if errorlevel 1 exit /b 1
if not exist build\desktop mkdir build\desktop
cl /nologo /O2 /EHsc /std:c++17 /MD /LD desktop\native\audio_core.cpp desktop\native\aegisub\fft.cpp desktop\native\aegisub\hsl.cpp /Fo:build\desktop\ /link /OUT:build\desktop\shengao-audio.dll /IMPLIB:build\desktop\shengao-audio.lib
exit /b %errorlevel%

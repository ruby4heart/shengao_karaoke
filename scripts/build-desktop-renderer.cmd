@echo off
setlocal
cd /d "%~dp0.."
call scripts\environment.cmd >nul
if errorlevel 1 exit /b 1
if not exist build\desktop mkdir build\desktop
cl /nologo /O2 /MD /LD /I vendor\aegisub\subprojects\libass\libass desktop\native\renderer.c /Fo:build\desktop\renderer.obj /link /OUT:build\desktop\shengao-render.dll /IMPLIB:build\desktop\shengao-render.lib build\baseline\subprojects\libass\libass\libass.a build\baseline\subprojects\freetype2\libfreetype.a build\baseline\subprojects\fribidi\lib\libfribidi.a build\baseline\subprojects\harfbuzz\src\libharfbuzz.a build\baseline\subprojects\zlib-1.3.1\libz.a build\baseline\subprojects\iconv\libiconv.a dwrite.lib gdi32.lib user32.lib ole32.lib advapi32.lib
exit /b %errorlevel%

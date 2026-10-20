@echo off
setlocal
cd /d "%~dp0.."
call scripts\environment.cmd >nul
if errorlevel 1 exit /b 1
cl /nologo /O2 /MD /EHsc /std:c++17 /D__WXMSW__ /DUNICODE /D_UNICODE /DNOMINMAX /I build\baseline\subprojects\wxWidgets\__CMake_build\lib\vc_x64_lib\mswu /I vendor\aegisub\subprojects\wxWidgets\include build\desktop-reference\reference.cpp desktop\native\aegisub\fft.cpp desktop\native\aegisub\hsl.cpp /Fo:build\desktop-reference\ /LD /link /OUT:build\desktop-reference\shengao-reference.dll /IMPLIB:build\desktop-reference\shengao-reference.lib build\baseline\subprojects\wxWidgets\libwxmono.a build\baseline\subprojects\wxWidgets\libwxregex.a build\baseline\subprojects\wxWidgets\libwxpng.a build\baseline\subprojects\wxWidgets\libwxjpeg.a build\baseline\subprojects\wxWidgets\libwxexpat.a build\baseline\subprojects\wxWidgets\libwxscintilla.a build\baseline\subprojects\zlib-1.3.1\libz.a kernel32.lib user32.lib gdi32.lib comdlg32.lib winspool.lib winmm.lib shell32.lib shlwapi.lib comctl32.lib ole32.lib oleaut32.lib uuid.lib rpcrt4.lib advapi32.lib version.lib ws2_32.lib wininet.lib oleacc.lib uxtheme.lib winhttp.lib imm32.lib opengl32.lib glu32.lib
exit /b %errorlevel%

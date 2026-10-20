@echo off
setlocal
cd /d "%~dp0.."
call scripts\environment.cmd >nul
if errorlevel 1 exit /b 1
if exist build\independent-engine\meson-private\coredata.dat (
  python -m mesonbuild.mesonmain setup build\independent-engine . --reconfigure --wrap-mode=forcefallback
) else (
  python -m mesonbuild.mesonmain setup build\independent-engine . --wrap-mode=forcefallback
)
if errorlevel 1 exit /b 1
python -m mesonbuild.mesonmain compile -C build\independent-engine -j 4 shengao-audio shengao-render shengao-view
if errorlevel 1 exit /b 1
if not exist build\desktop mkdir build\desktop
copy /y build\independent-engine\shengao-audio.dll build\desktop\shengao-audio.dll >nul
copy /y build\independent-engine\shengao-render.dll build\desktop\shengao-render.dll >nul
copy /y build\independent-engine\shengao-view.dll build\desktop\shengao-view.dll >nul
exit /b %errorlevel%

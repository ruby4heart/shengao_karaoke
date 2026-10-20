@echo off
set "STUDIO_VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
if not exist "%STUDIO_VSWHERE%" (
  echo Visual Studio C++ Build Tools not found.
  exit /b 1
)
set "STUDIO_VS="
for /f "usebackq delims=" %%V in (`"%STUDIO_VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set "STUDIO_VS=%%V"
if not defined STUDIO_VS exit /b 1
call "%STUDIO_VS%\VC\Auxiliary\Build\vcvars64.bat"
if errorlevel 1 exit /b 1
set "PATH=%~dp0..\.venv\Scripts;%PATH%"
set "STUDIO_GIT="
for /f "delims=" %%G in ('where git.exe 2^>nul') do if not defined STUDIO_GIT set "STUDIO_GIT=%%~dpG"
if defined STUDIO_GIT set "PATH=%PATH%;%STUDIO_GIT%..\usr\bin"
set "TEMP=%~dp0..\tmp"
set "TMP=%TEMP%"
if not exist "%TEMP%" mkdir "%TEMP%"
exit /b 0

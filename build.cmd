@echo off
rem Windows refuses to run .ps1 files at all under its default execution policy, so `.\build.ps1`
rem fails with UnauthorizedAccess on a machine nobody has configured. This wrapper lifts that for
rem the one process it starts -- it changes no setting, for the machine or for the user, and needs
rem no administrator. Double-click it, or run:
rem
rem     build.cmd              app + installer
rem     build.cmd -SkipApp     installer only, reusing dist\AutoPara\
rem
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build.ps1" %*
exit /b %ERRORLEVEL%

# Authorised by MaBoRo (Vladyslav Tishyn), vlad.tishyn@gmail.com
# Builds installer.exe in the repository root.
#
#   .\installer\build_installer.ps1
#
# The resulting installer.exe carries both the installer and the application itself (the
# "payload" folder), so it runs on a machine that has neither Python nor PySide6 -- installing
# those is exactly its job.
#
# Requires PyInstaller:  python -m pip install pyinstaller
#
# ASCII only on purpose: Windows PowerShell 5.1 reads .ps1 files in the ANSI code page unless
# they carry a BOM, and non-ASCII text there fails to parse.

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

Write-Host "==> Building installer.exe (PyInstaller)" -ForegroundColor Cyan

# PyInstaller writes its progress to stderr; with $ErrorActionPreference = "Stop" that alone
# would abort the script, so the exit code is what decides success here.
$ErrorActionPreference = "Continue"

# --add-data paths are resolved relative to --specpath, not to the working directory, so they are
# spelled out in full.
$root = (Get-Location).Path

python -m PyInstaller --noconfirm --onefile --windowed `
    --name installer `
    --distpath $root `
    --workpath "$root\build\installer" `
    --specpath "$root\build\installer" `
    --add-data "$root\autopara;payload/autopara" `
    --add-data "$root\autopara_launch.pyw;payload" `
    --add-data "$root\requirements.txt;payload" `
    --add-data "$root\README.md;payload" `
    --add-data "$root\docs;payload/docs" `
    --exclude-module PySide6 `
    --exclude-module shiboken6 `
    --exclude-module pytest `
    "$root\installer\install_app.py"

$ErrorActionPreference = "Stop"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

Write-Host ""
Write-Host "==> Done" -ForegroundColor Green
Get-Item installer.exe | ForEach-Object {
    "{0,-20} {1,7:N1} MB" -f $_.Name, ($_.Length / 1MB)
}

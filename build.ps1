# Authorised by MaBoRo (Vladyslav Tishyn), vlad.tishyn@gmail.com
# Builds AutoPara: PyInstaller bundle, then the NSIS installer.
#
#   .\build.ps1              app + installer
#   .\build.ps1 -SkipApp     installer only (reuses dist\AutoPara)
#
# Output: dist\AutoPara\AutoPara.exe  and  dist\AutoPara-<version>-Setup.exe

param(
    [switch]$SkipApp,
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not $SkipApp) {
    Write-Host "==> Building application bundle (PyInstaller)" -ForegroundColor Cyan
    python -m PyInstaller AutoPara.spec --noconfirm
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
}

if (-not (Test-Path "dist\AutoPara\AutoPara.exe")) {
    throw "dist\AutoPara\AutoPara.exe is missing - run without -SkipApp first"
}

if (-not $SkipInstaller) {
    $makensis = @(
        "$env:ProgramFiles\NSIS\makensis.exe"
        "${env:ProgramFiles(x86)}\NSIS\makensis.exe"
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1

    if (-not $makensis) {
        throw "makensis.exe not found. Install NSIS: winget install NSIS.NSIS"
    }

    Write-Host "==> Building installer (NSIS)" -ForegroundColor Cyan
    & $makensis "/V2" "installer\AutoPara.nsi"
    if ($LASTEXITCODE -ne 0) { throw "makensis failed" }
}

Write-Host ""
Write-Host "==> Done" -ForegroundColor Green
Get-ChildItem dist -Filter *.exe | ForEach-Object {
    "{0,-34} {1,7:N1} MB" -f $_.Name, ($_.Length / 1MB)
}
Get-ChildItem dist\AutoPara -Filter AutoPara.exe | ForEach-Object {
    "{0,-34} {1,7:N1} MB" -f "AutoPara\$($_.Name)", ($_.Length / 1MB)
}

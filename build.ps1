# Construit FootAnalytics pour Windows :
#   dist\FootAnalytics\FootAnalytics.exe        application (dossier, démarrage rapide)
#   dist\FootAnalytics-<version>-portable.zip   version portable (dézipper et lancer)
#   dist\FootAnalytics-Setup-<version>.exe      installeur (si Inno Setup 6 est installé)
# Usage : powershell -ExecutionPolicy Bypass -File build.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# PYTHON_EXE permet d'utiliser un Python déjà prêt (ex. intégration continue GitHub Actions)
$python = if ($env:PYTHON_EXE) { $env:PYTHON_EXE } else { ".\.venv\Scripts\python.exe" }
if (-not $env:PYTHON_EXE -and -not (Test-Path $python)) {
    python -m venv .venv
    & $python -m pip install --upgrade pip
    & $python -m pip install -r requirements.txt
}
$version = & $python -c "from footapp.config import APP_VERSION; print(APP_VERSION)"

# Modules Qt lourds inutiles pour l'application : exclus pour alléger le build
$exclude = @(
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtQuickWidgets", "PySide6.QtMultimedia",
    "PySide6.QtPdf", "PySide6.Qt3DCore", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtBluetooth", "PySide6.QtPositioning", "PySide6.QtSql", "PySide6.QtTest",
    "tkinter", "IPython", "pytest"
) | ForEach-Object { "--exclude-module=$_" }

& $python -m PyInstaller --noconfirm --clean --onedir --windowed `
    --name FootAnalytics `
    --icon assets\icon.ico `
    --add-data "assets;assets" `
    --collect-data mplsoccer `
    --collect-data qtawesome `
    @exclude `
    main.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller a échoué" }

$zip = "dist\FootAnalytics-$version-portable.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path dist\FootAnalytics -DestinationPath $zip
Write-Host "Version portable : $zip"

# Installeur Inno Setup (facultatif)
$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
          "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($iscc) {
    & $iscc /Q "/DAppVersion=$version" installer.iss
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup a échoué" }
    Write-Host "Installeur : dist\FootAnalytics-Setup-$version.exe"
} else {
    Write-Host "Inno Setup 6 non trouvé : installeur non généré (winget install JRSoftware.InnoSetup)"
}

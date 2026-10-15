# Génère dist\FootAnalytics.exe (un seul fichier, sans console).
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

# Modules Qt lourds inutiles pour l'application : exclus pour alléger l'exe
$exclude = @(
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtQuickWidgets", "PySide6.QtMultimedia",
    "PySide6.QtPdf", "PySide6.Qt3DCore", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtBluetooth", "PySide6.QtPositioning", "PySide6.QtSql", "PySide6.QtTest",
    "tkinter", "IPython", "pytest"
) | ForEach-Object { "--exclude-module=$_" }

& $python -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name FootAnalytics `
    --collect-data mplsoccer `
    --collect-data qtawesome `
    @exclude `
    main.py

Write-Host "`nExécutable généré : $PSScriptRoot\dist\FootAnalytics.exe"

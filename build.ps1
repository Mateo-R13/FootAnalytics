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
    & $python -m pip install -r requirements.lock   # versions exactes : build reproductible
}
$version = & $python -c "from footapp.config import APP_VERSION; print(APP_VERSION)"

# Modules Python inutiles à l'application : exclus du build
$exclude = @(
    "PySide6.QtNetwork", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtQml", "PySide6.QtQuick",
    "PySide6.QtQuickWidgets", "PySide6.QtPdf", "PySide6.QtTest", "PySide6.QtSql", "PySide6.QtMultimedia",
    "PIL._avif", "tkinter", "IPython", "pytest"
) | ForEach-Object { "--exclude-module=$_" }

& $python -m PyInstaller --noconfirm --clean --onedir --windowed `
    --name FootAnalytics `
    --icon assets\icon.ico `
    --add-data "assets;assets" `
    --collect-data qtawesome `
    @exclude `
    main.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller a échoué" }

# Composants Qt embarqués par défaut mais jamais utilisés (l'application n'utilise que Qt Widgets) :
# moteur OpenGL logiciel, clavier virtuel (qui entraîne Qt Quick / QML), Qt PDF, formats d'image
# et plateformes inutiles, traductions autres que le français.
$qt = "dist\FootAnalytics\_internal\PySide6"
$unused = @(
    "opengl32sw.dll", "Qt6Quick.dll", "Qt6Qml.dll", "Qt6QmlModels.dll", "Qt6QmlMeta.dll", "Qt6QmlWorkerScript.dll",
    "Qt6VirtualKeyboard.dll", "Qt6Pdf.dll", "Qt6OpenGL.dll", "Qt6Network.dll",
    "plugins\platforminputcontexts", "plugins\networkinformation", "plugins\tls", "plugins\styles",
    "plugins\imageformats\qpdf.dll", "plugins\imageformats\qicns.dll", "plugins\imageformats\qtga.dll",
    "plugins\imageformats\qtiff.dll", "plugins\imageformats\qwbmp.dll",
    "plugins\platforms\qdirect2d.dll", "plugins\platforms\qminimal.dll", "plugins\platforms\qoffscreen.dll"
)
foreach ($item in $unused) {
    $path = Join-Path $qt $item
    if (Test-Path $path) { Remove-Item $path -Recurse -Force }
}
Get-ChildItem "$qt\translations" -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -notmatch '^qtbase_fr\.qm$' } | Remove-Item -Force
$size = (Get-ChildItem dist\FootAnalytics -Recurse -File | Measure-Object Length -Sum).Sum / 1MB
Write-Host ("Application : {0:N0} Mo" -f $size)

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

#!/usr/bin/env bash
# Construit FootAnalytics pour macOS ou Linux (pour Windows : build.ps1).
#   macOS : dist/FootAnalytics.app, archivé dans dist/FootAnalytics-<version>-macos-arm64.zip
#           (signature ad hoc : l'application n'est pas notariée, voir le README)
#   Linux : dist/FootAnalytics/FootAnalytics, archivé dans dist/FootAnalytics-<version>-linux-x86_64.tar.gz
# Usage : ./build.sh   (PYTHON_EXE permet d'utiliser un Python déjà prêt, ex. intégration continue)
set -euo pipefail
cd "$(dirname "$0")"

python="${PYTHON_EXE:-.venv/bin/python}"
if [ -z "${PYTHON_EXE:-}" ] && [ ! -x "$python" ]; then
    python3 -m venv .venv
    "$python" -m pip install --upgrade pip
    "$python" -m pip install -r requirements.lock   # versions exactes : build reproductible
fi
version=$("$python" -c "from footapp.config import APP_VERSION; print(APP_VERSION)")
os=$(uname -s)
arch=$(uname -m)

# Modules Python inutiles à l'application : exclus du build (même liste que build.ps1)
exclude=()
for module in PySide6.QtNetwork PySide6.QtOpenGL PySide6.QtOpenGLWidgets PySide6.QtQml PySide6.QtQuick \
              PySide6.QtQuickWidgets PySide6.QtPdf PySide6.QtTest PySide6.QtSql PySide6.QtMultimedia \
              PIL._avif tkinter IPython pytest; do
    exclude+=("--exclude-module=$module")
done

options=()
if [ "$os" = "Darwin" ]; then
    options+=(--icon assets/icon.icns --osx-bundle-identifier io.github.mateo-r13.footanalytics)
else
    options+=(--strip)   # symboles de débogage retirés (libpython, extensions)
fi

"$python" -m PyInstaller --noconfirm --clean --onedir --windowed \
    --name FootAnalytics \
    "${options[@]}" \
    --add-data "assets:assets" \
    --collect-data qtawesome \
    "${exclude[@]}" \
    main.py

if [ "$os" = "Darwin" ]; then
    target=dist/FootAnalytics.app
else
    target=dist/FootAnalytics
fi

# Composants Qt embarqués par défaut mais jamais utilisés (l'application n'utilise que Qt Widgets) :
# Qt Quick / QML, clavier virtuel, Qt PDF, réseau, formats d'image et plateformes inutiles,
# traductions autres que le français. Noms des bibliothèques Linux (libQt6X.so.6) et macOS (QtX.framework).
for lib in Quick Qml QmlModels QmlMeta QmlWorkerScript VirtualKeyboard Pdf Network; do
    find "$target" \( -name "libQt6$lib.so*" -o -name "Qt$lib.framework" \) -prune -exec rm -rf {} +
done
for plugin in platforminputcontexts/libqtvirtualkeyboardplugin networkinformation tls styles \
              imageformats/libqpdf imageformats/libqtga imageformats/libqtiff imageformats/libqwbmp \
              platforms/libqminimal platforms/libqoffscreen platforms/libqvnc platforms/libqlinuxfb \
              platforms/libqeglfs platforms/libqminimalegl platforms/libqvkkhrdisplay egldeviceintegrations \
              generic/libqtuiotouchplugin platformthemes/libqgtk3; do
    find "$target" -path "*/PySide6/Qt/plugins/$plugin*" -prune -exec rm -rf {} +
done
find "$target" -path "*/PySide6/Qt/translations/*" -type f ! -name "qtbase_fr.qm" -delete
find "$target" -type l ! -exec test -e {} \; -delete   # liens symboliques devenus orphelins (bundle macOS)

# Linux : PyInstaller copie aussi les bibliothèques du système dont dépendent les extensions retirées
# (GTK 3 et toute sa pile pour le thème libqgtk3, par exemple). On retire celles dont plus rien ne dépend.
if [ "$os" = "Linux" ]; then
    while :; do
        needed=$(find "$target" -type f \( -name "*.so*" -o -name FootAnalytics \) -print0 \
                 | xargs -0 readelf -d 2>/dev/null | sed -n 's/.*(NEEDED).*\[\(.*\)\]/\1/p' | sort -u || true)
        removed=0
        for lib in "$target"/_internal/lib*.so*; do
            name=$(basename "$lib")
            case "$name" in libpython*) continue ;; esac
            if ! grep -qxF "$name" <<< "$needed"; then
                rm -f "$lib"
                removed=1
            fi
        done
        [ "$removed" = 0 ] && break
    done
fi

# Aucune bibliothèque restante ne doit dépendre d'un composant supprimé
if [ "$os" = "Linux" ]; then
    missing=$(find "$target" -name "*.so*" -type f -exec sh -c 'ldd "$1" 2>/dev/null | grep "not found" \
              | sed "s|^|$1 :|"' _ {} \; || true)
else
    missing=$(find "$target" -type f \( -perm -u+x -o -name "*.dylib" -o -name "*.so" \) -exec sh -c 'otool -L "$1" \
              2>/dev/null | grep -E "Qt(Quick|Qml|QmlModels|QmlMeta|QmlWorkerScript|VirtualKeyboard|Pdf|Network)\.framework" \
              | sed "s|^|$1 :|"' _ {} \; || true)
fi
if [ -n "$missing" ]; then
    echo "Dépendances supprimées mais encore utilisées :" >&2
    echo "$missing" >&2
    exit 1
fi
echo "Application : $(du -sm "$target" | cut -f1) Mo"

if [ "$os" = "Darwin" ]; then
    plist="$target/Contents/Info.plist"
    plutil -replace CFBundleShortVersionString -string "$version" "$plist"
    plutil -replace CFBundleVersion -string "$version" "$plist"
    plutil -replace NSHighResolutionCapable -bool true "$plist"
    # fichiers retirés après coup : la signature ad hoc posée par PyInstaller est refaite sur tout le bundle
    codesign --force --deep --sign - "$target"
    codesign --verify --deep --strict "$target"
    archive="dist/FootAnalytics-$version-macos-$arch.zip"
    rm -f "$archive"
    ditto -c -k --keepParent "$target" "$archive"   # conserve liens symboliques et signature
else
    archive="dist/FootAnalytics-$version-linux-$arch.tar.gz"
    rm -f "$archive"
    tar -czf "$archive" -C dist FootAnalytics
fi
echo "Archive : $archive ($(du -m "$archive" | cut -f1) Mo)"

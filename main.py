"""Point d'entrée de FootAnalytics.

Ordre volontaire : l'écran de chargement s'affiche avant l'import des bibliothèques lourdes
(pandas, matplotlib), pour que le lancement réagisse immédiatement.
"""
import logging
import sys

from PySide6.QtCore import QLibraryInfo, QLocale, Qt, QTranslator
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QSplashScreen

from footapp.config import APP_NAME, resource_path


def install_french_translation(app: QApplication) -> None:
    """Boîtes de dialogue standard de Qt en français (« Oui / Non », sélecteur de fichiers…)."""
    translator = QTranslator(app)
    if translator.load(QLocale(QLocale.French, QLocale.France), "qtbase", "_",
                       QLibraryInfo.path(QLibraryInfo.TranslationsPath)):
        app.installTranslator(translator)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(QIcon(str(resource_path("assets/icon.png"))))
    splash = QSplashScreen(QPixmap(str(resource_path("assets/icon.png"))))
    splash.showMessage(f"{APP_NAME}  -  chargement…", Qt.AlignBottom | Qt.AlignHCenter, QColor("#ffffff"))
    splash.show()
    app.processEvents()

    from footapp.logs import setup_logging
    from footapp.ui import theme
    from footapp.ui.settings import open_settings

    setup_logging()
    install_french_translation(app)
    # le thème doit être fixé avant de construire la moindre fenêtre
    theme.configure(str(open_settings().value("theme") or "dark"))
    theme.apply_qt(app)
    theme.apply_matplotlib()

    from footapp.ui.main_window import MainWindow
    window = MainWindow()
    window.show()
    splash.finish(window)
    log = logging.getLogger("footapp")
    app.lastWindowClosed.connect(lambda: log.info("Dernière fenêtre fermée"))
    code = app.exec()
    log.info("Fermeture (code %s)", code)
    sys.exit(code)


if __name__ == "__main__":
    main()

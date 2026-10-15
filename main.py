"""Point d'entrée de FootAnalytics."""
import sys

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QSplashScreen

from footapp.config import APP_NAME, resource_path
from footapp.ui import theme


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(QIcon(str(resource_path("assets/icon.png"))))
    # le thème doit être fixé avant de construire la moindre fenêtre
    theme.configure(str(QSettings(APP_NAME, APP_NAME).value("theme") or "dark"))
    theme.apply_qt(app)
    theme.apply_matplotlib()

    # écran de chargement pendant l'import des bibliothèques et la construction de la fenêtre
    splash = QSplashScreen(QPixmap(str(resource_path("assets/icon.png"))))
    splash.showMessage(f"{APP_NAME}  -  chargement…", Qt.AlignBottom | Qt.AlignHCenter, QColor("#ffffff"))
    splash.show()
    app.processEvents()

    from footapp.ui.main_window import MainWindow
    window = MainWindow()
    window.show()
    splash.finish(window)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

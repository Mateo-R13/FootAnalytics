"""Point d'entrée de FootAnalytics."""
import sys

from PySide6.QtWidgets import QApplication

from footapp.config import APP_NAME
from footapp.ui import theme
from footapp.ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    theme.apply_qt(app)
    theme.apply_matplotlib()
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

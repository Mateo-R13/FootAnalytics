"""Génère l'icône de l'application (assets/icon.png et assets/icon.ico).

Usage : .venv\\Scripts\\python.exe tools\\make_icon.py
Carré arrondi en dégradé vert -> bleu -> violet (couleurs de la marque) et ballon blanc.
"""
import sys
from pathlib import Path

import qtawesome as qta
from PIL import Image
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath

ASSETS = Path(__file__).resolve().parent.parent / "assets"
SIZE = 512


def render() -> QImage:
    img = QImage(SIZE, SIZE, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    grad = QLinearGradient(0, 0, SIZE, SIZE)
    grad.setColorAt(0, QColor("#22c55e"))
    grad.setColorAt(0.5, QColor("#3b82f6"))
    grad.setColorAt(1, QColor("#8b5cf6"))
    path = QPainterPath()
    margin = SIZE * 0.04
    path.addRoundedRect(QRectF(margin, margin, SIZE - 2 * margin, SIZE - 2 * margin), SIZE * 0.22, SIZE * 0.22)
    p.fillPath(path, grad)
    ball = qta.icon("fa5s.futbol", color="#ffffff").pixmap(int(SIZE * 0.6), int(SIZE * 0.6))
    p.drawPixmap(int(SIZE * 0.2), int(SIZE * 0.2), ball)
    p.end()
    return img


def main():
    app = QGuiApplication(sys.argv)  # requis par qtawesome
    ASSETS.mkdir(exist_ok=True)
    png = ASSETS / "icon.png"
    render().scaled(256, 256, Qt.KeepAspectRatio, Qt.SmoothTransformation).save(str(png))
    full = ASSETS / "icon_512.png"
    render().save(str(full))
    Image.open(full).save(ASSETS / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
                                                      (128, 128), (256, 256)])
    full.unlink()
    print("icône générée dans", ASSETS)
    del app


if __name__ == "__main__":
    main()

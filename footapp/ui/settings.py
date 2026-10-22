"""Paramètres de l'utilisateur (thème, compétition, liste de suivi, recherches…).

Un seul point d'entrée : la variable d'environnement FOOTAPP_SETTINGS (chemin d'un fichier .ini)
permet d'isoler les paramètres, par exemple pendant les tests, sans toucher à ceux de l'utilisateur.
"""
import os

from PySide6.QtCore import QSettings

from ..config import APP_NAME


def open_settings() -> QSettings:
    path = os.environ.get("FOOTAPP_SETTINGS")
    if path:
        return QSettings(path, QSettings.Format.IniFormat)
    return QSettings(APP_NAME, APP_NAME)

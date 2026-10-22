"""Journal de l'application : fichier tournant dans le sous-dossier logs du dossier de données (config.data_dir).

Les erreurs non gérées (fil principal et fils d'arrière-plan) y sont enregistrées avec leur trace
complète : indispensable pour diagnostiquer un problème signalé par un utilisateur.
"""
import logging
import sys
import threading
from logging.handlers import RotatingFileHandler
from types import TracebackType

from .config import LOG_DIR

logger = logging.getLogger("footapp")


def setup_logging(level: int = logging.INFO) -> None:
    if logger.handlers:  # déjà configuré
        return
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        handler: logging.Handler = RotatingFileHandler(LOG_DIR / "footanalytics.log", maxBytes=1_000_000, backupCount=3,
                                      encoding="utf-8")
    except OSError:
        handler = logging.StreamHandler()  # dossier inaccessible : journal sur la console
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(name)s : %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(level)

    def log_uncaught(exc_type: type[BaseException], exc: BaseException, tb: TracebackType | None) -> None:
        logger.critical("Erreur non gérée", exc_info=(exc_type, exc, tb))
        sys.__excepthook__(exc_type, exc, tb)

    def log_thread(args: threading.ExceptHookArgs) -> None:
        logger.critical("Erreur non gérée dans un fil d'exécution",
                        exc_info=args.exc_value)  # l'exception porte sa trace (__traceback__)

    sys.excepthook = log_uncaught
    threading.excepthook = log_thread
    logger.info("Démarrage")

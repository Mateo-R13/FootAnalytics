import sys

from PySide6.QtCore import QProcess
from PySide6.QtWidgets import (QApplication, QComboBox, QHBoxLayout, QLabel, QMessageBox, QTextBrowser, QVBoxLayout,
                               QWidget)

from ... import updates
from ...config import APP_VERSION, CACHE_DIR, GITHUB_REPO
from .. import theme
from ..widgets import Card, tool_button
from . import Page

GLOSSARY = [
    ("xG (expected goals)", "Probabilité qu'un tir se transforme en but, d'après sa position, le type d'action, la partie du corps… "
     "La somme des xG mesure la qualité des occasions, indépendamment de la réussite."),
    ("npxG", "xG hors penalties (Understat le fournit directement ; côté Sofascore, estimé en retirant 0,79 xG par penalty)."),
    ("xGOT (xG cadré)", "xG recalculé après le tir, selon l'endroit où le ballon arrive dans le cadre : mesure la qualité de frappe."),
    ("Buts évités", "Pour un gardien : xGOT des tirs subis moins buts encaissés. Positif = mieux qu'attendu."),
    ("xA (expected assists)", "Probabilité qu'une passe devienne une passe décisive, quel que soit le résultat du tir."),
    ("xPts (points attendus)", "Points qu'une équipe aurait dû prendre d'après les xG des deux équipes (loi de Poisson). "
     "Pts - xPts > 0 : l'équipe a pris plus de points que ses occasions ne le justifient (réussite, gardien en forme…)."),
    ("Par 90 min", "Valeur cumulée ÷ minutes jouées × 90 : compare titulaires et remplaçants. "
     "Filtrez un temps de jeu minimum pour éviter les extrêmes."),
    ("Centile", "Position parmi les joueurs du même poste : 80e centile = meilleur que 80 % d'entre eux. "
     "Pour les métriques « négatives » (ballons perdus, fautes…), l'échelle est inversée."),
    ("Similarité", "100 - écart moyen de centiles sur le profil du poste : 90 % = en moyenne 10 centiles d'écart par métrique."),
    ("PPDA", "Passes adverses par action défensive (tacles, interceptions, fautes). Bas = pressing intense. "
     "Officiel (Understat) pour les 5 grands championnats, approximé ailleurs."),
    ("Pronostics", "Modèle de Poisson : forces d'attaque et de défense calculées sur les xG de la saison, avantage du "
     "terrain. Indicatif : ne connaît ni les absences ni la forme du moment."),
    ("Grosse occasion", "Situation où l'on attend raisonnablement un but (définition Opta / Sofascore)."),
    ("Actions défensives", "Tacles + interceptions + dégagements + tirs contrés."),
    ("Raccourcis", "Ctrl+K (ou Ctrl+F) : recherche globale · double-clic sur un joueur : sa fiche."),
]


class HelpPage(Page):
    key = "help"
    title = "Aide & paramètres"
    subtitle = "Définitions des indicateurs, apparence, mises à jour, source des données et cache"
    icon_name = "fa5s.question-circle"

    def __init__(self, state):
        super().__init__(state)
        rows = "".join(
            f"<tr><td style='padding:7px 16px 7px 0; color:{theme.INK}; font-weight:600; white-space:nowrap; "
            f"vertical-align:top'>{term}</td><td style='padding:7px 0; color:{theme.INK2}'>{text}</td></tr>"
            for term, text in GLOSSARY)
        glossary = QTextBrowser()
        glossary.setHtml(f"<table cellspacing=0 width='100%'>{rows}</table>")
        g_card = Card("Glossaire")
        g_card.add(glossary, 1)

        # apparence
        self.theme_box = QComboBox()
        self.theme_box.addItem("Sombre", "dark")
        self.theme_box.addItem("Clair", "light")
        self.theme_box.setCurrentIndex(max(0, self.theme_box.findData(theme.MODE)))
        restart = tool_button("Appliquer (redémarre)", "fa5s.redo")
        restart.clicked.connect(self._apply_theme)
        look = Card("Apparence")
        row = QHBoxLayout()
        row.addWidget(QLabel("Thème"))
        row.addWidget(self.theme_box, 1)
        row.addWidget(restart)
        look.body.addLayout(row)

        # mises à jour
        self.update_label = QLabel(f"Version installée : {APP_VERSION}", objectName="Muted")
        self.update_label.setOpenExternalLinks(True)
        self.update_label.setWordWrap(True)
        check = tool_button("Vérifier", "fa5s.cloud-download-alt")
        check.clicked.connect(self._check_updates)
        upd = Card("Mises à jour")
        row = QHBoxLayout()
        row.addWidget(self.update_label, 1)
        row.addWidget(check)
        upd.body.addLayout(row)

        # données & cache
        src = QLabel(
            f"<p style='color:{theme.INK2}'>Statistiques : API publique du site <b style='color:{theme.INK}'>Sofascore</b> "
            "(non officielle). xG par match, xPts et PPDA des 5 grands championnats : <b style='color:"
            f"{theme.INK}'>Understat</b>, qui sert aussi de secours si Sofascore est indisponible. "
            "Usage personnel uniquement.</p>"
            f"<p style='color:{theme.INK2}'>Cache : matchs terminés conservés définitivement, le reste de 15 min à "
            "12 h. « Actualiser » (en haut) vide le cache temporaire.</p>"
            f"<p style='color:{theme.MUTED}'>{CACHE_DIR}</p>")
        src.setWordWrap(True)
        self.cache_label = QLabel(objectName="Muted")
        clear = tool_button("Vider tout le cache", "fa5s.trash-alt", "Supprime aussi les matchs et images en cache")
        clear.clicked.connect(self._clear_cache)
        row = QHBoxLayout()
        row.addWidget(self.cache_label)
        row.addStretch()
        row.addWidget(clear)
        data = Card("Données & cache")
        data.add(src)
        data.body.addLayout(row)

        right = QWidget()
        right.setFixedWidth(430)
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(12)
        for card in (look, upd, data):
            rl.addWidget(card)
        rl.addStretch()
        content = QHBoxLayout()
        content.setSpacing(12)
        content.addWidget(g_card, 1)
        content.addWidget(right)
        self.body.addLayout(content, 1)

    def showEvent(self, event):
        super().showEvent(event)
        self.cache_label.setText(f"Taille du cache : {self.state.data.client.cache_size_mb():.1f} Mo")

    def _apply_theme(self):
        self.state.settings.setValue("theme", self.theme_box.currentData())
        self.state.settings.sync()
        # relance l'application (exécutable ou script) puis ferme celle-ci
        args = sys.argv[1:] if getattr(sys, "frozen", False) else sys.argv
        QProcess.startDetached(sys.executable, args)
        QApplication.quit()

    def _check_updates(self):
        self.update_label.setText("Vérification…")
        self.state.runner.run("updates_manual", lambda progress: updates.latest_release(), self._on_release,
                              on_error=lambda message: self.update_label.setText("Vérification impossible."))

    def _on_release(self, release):
        if release is None:
            self.update_label.setText(f"Version installée : {APP_VERSION} · aucune version publiée sur "
                                      f"<a href='https://github.com/{GITHUB_REPO}/releases'>GitHub</a> pour l'instant.")
        elif updates.is_newer(release["version"], APP_VERSION):
            self.update_label.setText(f"Nouvelle version {release['version']} disponible : "
                                      f"<a href='{release['url']}'>télécharger</a>")
        else:
            self.update_label.setText(f"Version installée : {APP_VERSION} · vous êtes à jour.")

    def _clear_cache(self):
        if QMessageBox.question(self, "Vider le cache",
                                "Supprimer toutes les données en cache ? Elles seront retéléchargées au besoin.") \
                != QMessageBox.Yes:
            return
        self.state.data.client.clear_all_cache()
        self.cache_label.setText(f"Taille du cache : {self.state.data.client.cache_size_mb():.1f} Mo")

import sys

from PySide6.QtCore import QProcess, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ... import updates
from ...config import APP_VERSION, CACHE_DIR, GITHUB_REPO, LOG_DIR
from .. import theme
from ..widgets import Card, tool_button
from . import Page

GLOSSARY = [
    ("xG (expected goals)", "Probabilité qu'un tir se transforme en but, d'après sa position, le type d'action, "
     "la partie du corps… La somme des xG mesure la qualité des occasions, indépendamment de la réussite."),
    ("npxG", "xG hors penalties (Understat le fournit directement ; côté Sofascore, estimé en retirant 0,79 xG "
     "par penalty)."),
    ("xGOT (xG cadré)", "xG recalculé après le tir, selon l'endroit où le ballon arrive dans le cadre : "
     "mesure la qualité de frappe."),
    ("xGOT - xG", "Fiche joueur, onglet Tirs : xGOT moins xG des tirs hors penalty. Positif = le joueur cadre "
     "mieux que la moyenne ses occasions (qualité de frappe), négatif = il les gâche."),
    ("xG par tir", "npxG ÷ tirs hors penalty : qualité moyenne des positions de tir. Comparé à la moyenne du poste "
     "(somme des npxG ÷ somme des tirs des joueurs du même poste)."),
    ("Conversion hors penalty", "Buts hors penalty ÷ tirs hors penalty. Très instable sur moins de ~50 tirs : "
     "à lire avec l'xG par tir."),
    ("Buts évités", "Pour un gardien : xGOT des tirs subis moins buts encaissés. Positif = mieux qu'attendu."),
    ("xA (expected assists)", "Probabilité qu'une passe devienne une passe décisive, quel que soit le résultat "
     "du tir."),
    ("xPts (points attendus)", "Points qu'une équipe aurait dû prendre d'après les xG des deux équipes (loi de "
     "Poisson). Pts - xPts > 0 : l'équipe a pris plus de points que ses occasions ne le justifient (réussite, "
     "gardien en forme…)."),
    ("Par 90 min", "Valeur cumulée ÷ minutes jouées × 90 : compare titulaires et remplaçants. "
     "Filtrez un temps de jeu minimum pour éviter les extrêmes."),
    ("Centile", "Position parmi les joueurs du même poste : 80e centile = meilleur que 80 % d'entre eux. "
     "Pour les métriques « négatives » (ballons perdus, fautes…), l'échelle est inversée."),
    ("Similarité", "100 - écart moyen de centiles sur le profil du poste : 90 % = en moyenne 10 centiles d'écart "
     "par métrique."),
    ("Indice personnalisé", "Moyenne pondérée de centiles (calculés au sein de chaque poste), de 0 à 100."),
    ("Valeur estimée", "Valeur marchande estimée par Sofascore (pas un prix de transfert), avec l'âge et la fin de "
     "contrat issus des effectifs actuels : disponibles pour la saison en cours uniquement."),
    ("Sous-évalué / surévalué", "Page Valeur vs performance : score attendu d'après la valeur estimée (échelle "
     "logarithmique), le poste et l'âge, par une régression robuste (Huber) ; z = écart au score attendu en écarts "
     "types robustes. Le R² affiché indique la part du score expliquée par la valeur (souvent faible en début de "
     "saison) : un z élevé est une piste à vérifier, pas un verdict."),
    ("PPDA", "Passes adverses par action défensive (tacles, interceptions, fautes). Bas = pressing intense. "
     "Officiel (Understat) pour les 5 grands championnats, approximé ailleurs (passes adverses dans leur moitié : "
     "valeurs plus basses, à ne comparer qu'entre elles)."),
    ("Évolution & carrière", "Fiche joueur : une métrique par 90 min saison après saison, en championnat (et en "
     "coupes d'Europe si coché). Saisons de moins de 180 min ignorées ; sous le seuil « Fiable dès » (900 min par "
     "défaut), points creux et pointillés. Transfert en cours de saison : la ligne la plus fournie est gardée. "
     "Moyenne pondérée = saisons fiables du championnat pondérées par les minutes. « n.d. » : donnée absente cette "
     "saison-là (Sofascore n'a pas toujours tout mesuré). Les xG d'une saison à l'autre intègrent aussi les "
     "évolutions du modèle."),
    ("Historique (5 saisons)", "Équipes : saison en cours et 5 précédentes du championnat. Points, rang et buts : "
     "classement officiel Sofascore (pénalités de points incluses) ; xG, xPts et PPDA : Understat pour les 5 grands "
     "championnats, sinon statistiques de saison Sofascore (xG quand ils existent, grosses occasions, PPDA "
     "approché). Pas d'historique pour les coupes d'Europe (format changé en 24/25)."),
    ("Pronostics", "Modèle de Poisson : forces d'attaque et de défense calculées sur les xG de la saison, avantage du "
     "terrain. Indicatif : ne connaît ni les absences ni la forme du moment."),
    ("Score de Brier", "Erreur moyenne des probabilités annoncées (0 = parfait, plus bas = mieux), comparée à une "
     "référence naïve qui annoncerait toujours la répartition moyenne victoire / nul / défaite."),
    ("Avant-match", "Pronostics : bouton « Avant-match » ou double-clic sur un match. Pronostic du modèle, classement "
     "et rang xPts, forme, repos (jours depuis le dernier match, matchs sur 14 jours, toutes compétitions), profils, "
     "joueurs clés, absents, XI probable et 10 dernières confrontations officielles (amicaux exclus ; score sans les "
     "tirs au but, indiqués à part), avec export PDF. Absents et XI probable sont des estimations Sofascore, "
     "susceptibles de changer : le modèle n'en tient pas compte. Aucune cote de bookmaker."),
    ("Joueurs clés", "Avant-match : meilleur joueur de l'équipe pour la note, buts + passes décisives, npxG, passes "
     "clés et actions défensives (buts évités pour les gardiens), 270 min minimum, avec son centile parmi les joueurs "
     "du même poste. % minutes d'un absent = minutes jouées ÷ (matchs de l'équipe × 90)."),
    ("Fiabilité réduite", "Avant-match : une des deux équipes a joué moins de 5 matchs dans la compétition (coupes, "
     "début de saison). Les forces du modèle reposent sur trop peu de matchs : profils et joueurs clés sont masqués."),
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
            f"<p style='color:{theme.INK2}'>Statistiques : API publique du site "
            f"<b style='color:{theme.INK}'>Sofascore</b> "
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
        logs = tool_button("Journal", "fa5s.file-alt", f"Ouvrir le dossier du journal d'erreurs ({LOG_DIR})")
        logs.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(LOG_DIR))))
        row = QHBoxLayout()
        row.addWidget(self.cache_label)
        row.addStretch()
        row.addWidget(logs)
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

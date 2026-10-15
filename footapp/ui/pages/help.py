from PySide6.QtWidgets import QHBoxLayout, QLabel, QMessageBox, QTextBrowser

from ...config import APP_VERSION, CACHE_DIR
from .. import theme
from ..widgets import Card, tool_button
from . import Page

GLOSSARY = [
    ("xG (expected goals)", "Probabilité qu'un tir se transforme en but, d'après sa position, le type d'action, la partie du corps… "
     "La somme des xG mesure la qualité des occasions, indépendamment de la réussite."),
    ("npxG", "xG hors penalties. Estimé ici en retirant 0,79 xG par penalty tiré (valeur Sofascore d'un penalty)."),
    ("xGOT (xG cadré)", "xG recalculé après le tir, en tenant compte de l'endroit où le ballon arrive dans le cadre. "
     "Mesure la qualité de frappe."),
    ("Buts évités", "Pour un gardien : xGOT des tirs subis moins buts encaissés. Positif = le gardien a fait mieux qu'attendu."),
    ("xA (expected assists)", "Probabilité qu'une passe devienne une passe décisive, quel que soit le résultat du tir."),
    ("Buts - xG", "Écart entre buts marqués et xG. Positif = finition au-dessus de la moyenne (ou chance) ; "
     "sur de petits échantillons, c'est surtout du bruit."),
    ("Par 90 min", "Valeur cumulée divisée par les minutes jouées × 90. Permet de comparer titulaires et remplaçants. "
     "Filtrez un temps de jeu minimum (270 min par défaut) pour éviter les extrêmes."),
    ("Centile", "Position d'un joueur parmi ceux du même poste : 80e centile = meilleur que 80 % d'entre eux. "
     "Pour les métriques « négatives » (ballons perdus, fautes, buts encaissés…), l'échelle est inversée."),
    ("Grosse occasion", "Situation où l'on attend raisonnablement un but (définition Opta / Sofascore)."),
    ("Actions défensives", "Tacles + interceptions + dégagements + tirs contrés."),
    ("PPDA (approx.)", "Passes adverses dans leur propre moitié / (tacles + interceptions + fautes). Plus c'est bas, "
     "plus l'équipe presse haut. Approximation : la définition officielle se limite aux 60 % de terrain adverse."),
    ("Momentum", "Courbe de domination Sofascore minute par minute (positif = équipe à domicile)."),
    ("Valeurs d'impact", "Indices Sofascore normalisés de la contribution d'un joueur dans un match (passes, dribbles, "
     "tirs, défense, gardien)."),
]


class HelpPage(Page):
    key = "help"
    title = "Aide & glossaire"
    subtitle = "Définitions des indicateurs, source des données et gestion du cache"
    icon_name = "fa5s.question-circle"

    def __init__(self, state):
        super().__init__(state)
        rows = "".join(
            f"<tr><td style='padding:8px 16px 8px 0; color:{theme.INK}; font-weight:600; white-space:nowrap; "
            f"vertical-align:top'>{term}</td><td style='padding:8px 0; color:{theme.INK2}'>{text}</td></tr>"
            for term, text in GLOSSARY)
        glossary = QTextBrowser()
        glossary.setHtml(f"<table cellspacing=0 width='100%'>{rows}</table>")
        g_card = Card("Glossaire")
        g_card.add(glossary, 1)
        self.body.addWidget(g_card, 3)

        src = QLabel(
            f"<p style='color:{theme.INK2}'>Les données proviennent de l'API publique du site "
            f"<b style='color:{theme.INK}'>Sofascore</b> (non officielle, sans clé) : saison en cours, mise à jour "
            "quelques minutes après les matchs. Usage personnel uniquement.</p>"
            f"<p style='color:{theme.INK2}'>Les réponses sont gardées en cache : les matchs terminés définitivement, "
            "le reste de 15 minutes à 12 heures. « Actualiser » (en haut) vide le cache temporaire.</p>"
            f"<p style='color:{theme.MUTED}'>Version {APP_VERSION} · cache : {CACHE_DIR}</p>")
        src.setWordWrap(True)
        self.cache_label = QLabel(objectName="Muted")
        clear = tool_button("Vider tout le cache", "fa5s.trash-alt", "Supprime aussi les matchs et images en cache")
        clear.clicked.connect(self._clear_cache)
        row = QHBoxLayout()
        row.addWidget(self.cache_label)
        row.addStretch()
        row.addWidget(clear)
        s_card = Card("Données & cache")
        s_card.add(src)
        s_card.body.addLayout(row)
        self.body.addWidget(s_card, 1)

    def showEvent(self, event):
        super().showEvent(event)
        self.cache_label.setText(f"Taille du cache : {self.state.data.client.cache_size_mb():.1f} Mo")

    def _clear_cache(self):
        if QMessageBox.question(self, "Vider le cache",
                                "Supprimer toutes les données en cache ? Elles seront retéléchargées au besoin.") \
                != QMessageBox.Yes:
            return
        self.state.data.client.clear_all_cache()
        self.cache_label.setText(f"Taille du cache : {self.state.data.client.cache_size_mb():.1f} Mo")

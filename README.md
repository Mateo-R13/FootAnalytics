# FootAnalytics

Application de bureau pour **data analysts football** : statistiques de la saison en cours
(passes, dribbles, duels, xG/xA, tirs, pressing…), fiches joueurs, comparaisons et analyse de matchs.
Python + PySide6, distribuable en un seul `.exe` Windows.

![Tableau de bord](docs/screenshots/dashboard.png)

## Fonctionnalités

| Section | Contenu |
|---|---|
| **Tableau de bord** | Chiffres clés de la compétition, top 5 par métrique (buts, xG, passes clés, dribbles, actions défensives, notes, gardiens), finition buts vs xG |
| **Classement** | Classement avec logos, attaque vs défense, points par match |
| **Matchs** | Par journée : stats d'équipe par période (match / mi-temps) et catégorie, carte des tirs avec xG, courbe de domination, ~70 stats individuelles en 8 groupes, heatmaps, positions moyennes, chronologie |
| **Statistiques joueurs** | ~110 métriques en 11 catégories, filtres poste / équipe / temps de jeu, mode par 90 min, classement graphique, export Excel/CSV |
| **Fiche joueur** | Identité (âge, pied, valeur, contrat), profil en centiles vs joueurs du même poste, forme match par match, toutes les stats avec rang au poste |
| **Comparaison** | Radar en centiles de deux joueurs, nuage de points libre (deux métriques au choix) |
| **Équipes** | ~75 métriques d'équipe dont ce qui est concédé à l'adversaire, PPDA (pressing), total ou par match |
| **Aide & glossaire** | Définitions (xG, npxG, xGOT, centiles, PPDA…), gestion du cache |

Graphiques interactifs : survol = détail, barre d'outils = zoom et export PNG.
Double-clic sur un joueur dans n'importe quel tableau → sa fiche.

<p>
  <img src="docs/screenshots/fiche-joueur.png" width="49%">
  <img src="docs/screenshots/comparaison.png" width="49%">
  <img src="docs/screenshots/match.png" width="49%">
  <img src="docs/screenshots/joueurs.png" width="49%">
</p>

## Installation

### Exécutable
Télécharger `FootAnalytics.exe` dans les [Releases](../../releases) (ou l'artefact du dernier build
dans l'onglet *Actions*), puis le lancer. Aucune installation de Python nécessaire.

### Depuis les sources
```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

### Générer l'exécutable
```powershell
powershell -ExecutionPolicy Bypass -File build.ps1   # -> dist\FootAnalytics.exe
```
Le workflow GitHub Actions (`.github/workflows/build.yml`) le fait automatiquement à chaque push sur `main` ;
pousser un tag `v*` (ex. `git tag v2.0.0 && git push --tags`) publie l'exe dans une Release.

## Données

Source : API JSON publique utilisée par le site sofascore.com (non officielle, sans clé),
interrogée via `curl_cffi` qui imite un navigateur.

- **Usage personnel / expérimental uniquement** : l'API n'est pas documentée et ses conditions
  n'autorisent pas un usage commercial.
- Elle peut changer ou bloquer sans préavis : tout l'accès réseau est isolé dans `footapp/api/sofascore.py`.
- Cache disque dans `%LOCALAPPDATA%\FootAnalytics\cache` : matchs terminés conservés définitivement,
  le reste de 15 min à 12 h. Le bouton « Actualiser » vide le cache temporaire.

## Structure

```
main.py                       point d'entrée
footapp/
  config.py                   compétitions, catalogue des métriques et libellés
  api/sofascore.py            client HTTP + cache disque (JSON et images)
  data.py                     appels API -> DataFrames pandas (+ métriques dérivées)
  analysis.py                 par 90 min, centiles, rangs
  ui/
    main_window.py            fenêtre : navigation latérale + barre de contexte
    state.py                  état partagé (compétition, classement, joueurs)
    theme.py                  couleurs, feuille de style Qt, style matplotlib
    widgets.py                cartes, tuiles, tableaux, graphiques, images, tâches de fond
    charts.py                 tous les graphiques (matplotlib / mplsoccer)
    pages/                    une page par section
```

**Ajouter une compétition** : `(nom, id)` dans `COMPETITIONS` (l'id figure dans l'URL Sofascore du tournoi).
**Ajouter une métrique joueur ou équipe** : une ligne dans `PLAYER_METRICS` / `TEAM_METRICS`.

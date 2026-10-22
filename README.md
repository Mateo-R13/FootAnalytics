# FootAnalytics

Application de bureau pour **data analysts football** : statistiques de la saison en cours
(passes, dribbles, duels, xG/xA, tirs, pressing…), fiches joueurs, comparaisons et analyse de matchs.
Python + PySide6, pour Windows (installeur), macOS (Apple Silicon) et Linux (thème sombre ou clair).

![Tableau de bord](docs/screenshots/dashboard.png)

## Fonctionnalités

| Section | Contenu |
|---|---|
| **Tableau de bord** | Chiffres clés de la compétition, top 5 par métrique (buts, xG, passes clés, dribbles, actions défensives, notes, gardiens), finition buts vs xG |
| **Classement** | Classement avec logos, **classement xG** (points attendus xPts, chance / malchance, PPDA officiel), attaque vs défense, points par match |
| **Matchs** | Par journée (par semaine pour les saisons sans journées chez Sofascore, comme la MLS 2026) : stats d'équipe par période (match / mi-temps) et catégorie, carte des tirs avec xG, xG cumulés minute par minute, courbe de domination, ~70 stats individuelles en 8 groupes, heatmaps, positions moyennes, chronologie |
| **Pronostics** | Probabilités 1 / N / 2 des prochains matchs (modèle de Poisson / Dixon-Coles ajusté par maximum de vraisemblance sur xG et buts, matchs récents favorisés, saison précédente en point de départ pour les 5 grands championnats), matrice des scores, simulation de n'importe quelle affiche, **fiabilité du modèle** (rejoué sur les matchs passés : taux de réussite, score de Brier, log-loss, calibration, comparaison avec l'ancien modèle et une référence naïve) |
| **Avant-match** | Depuis Pronostics (bouton ou double-clic) : pronostic du modèle, classement et rang xPts, bilan domicile / extérieur, forme des deux équipes, repos et derniers matchs toutes compétitions, **profils comparés** (radar), **joueurs clés** croisés avec les **absents annoncés**, XI probable (estimations Sofascore), **10 dernières confrontations**, badge « fiabilité réduite » sous 5 matchs joués, **rapport PDF** (~7 pages, sans cotes de bookmakers) |
| **Statistiques joueurs** | ~110 métriques en 11 catégories, filtres poste / équipe / temps de jeu, mode par 90 min, classement graphique, export Excel/CSV |
| **Fiche joueur** | Identité (âge, pied, valeur, contrat), profil en centiles vs joueurs du même poste, forme match par match, **tirs & heatmap de la saison** (carte des tirs avec xG, xG par tir et % cadrés vs moyenne du poste, répartition par situation / surface de contact / zone), **profils similaires** (joueurs statistiquement les plus proches), **profil type** (rôle de jeu par regroupement statistique des joueurs du même poste : « Latéral offensif », « Pivot récupérateur »… avec carte ACP et métriques distinctives), **évolution & carrière** (n'importe quelle métrique par 90 min saison après saison : championnat et coupes d'Europe, saisons à faible temps de jeu signalées, moyenne pondérée), toutes les stats avec rang au poste, **liste de suivi**, **export PDF** |
| **Comparaison** | Radar en centiles de deux joueurs, nuage de points libre, référentiel compétition ou **5 grands championnats** |
| **Recherche avancée** | Joueurs remplissant plusieurs critères (centiles par poste), filtres **âge / valeur estimée / fin de contrat** et **profil type**, compétition ou 5 grands championnats, recherches enregistrables |
| **Valeur vs performance** | Nuage valeur estimée Sofascore (échelle log) vs score (note, profil du poste, indice ou métrique), performance attendue par régression robuste (poste, âge, championnat), joueurs **sous-évalués / surévalués** (pistes à vérifier), R² affiché, filtres âge / valeur / contrat, export — saison en cours |
| **Indices personnalisés** | Scores composés de métriques pondérées (Créateur, Finisseur, Récupérateur… ou les vôtres), classement et export |
| **Équipes** | ~75 métriques d'équipe dont ce qui est concédé à l'adversaire, PPDA, **comparaison de deux équipes** (radar), **forme** (xG glissants), **bilan domicile / extérieur**, **historique sur 5 saisons** (points et xPts par match, rang officiel avec pénalités, buts / xG pour et contre, PPDA, face à la moyenne de la ligue) |
| **Aide & paramètres** | Glossaire, thème sombre / clair, vérification des mises à jour, gestion du cache |

Graphiques interactifs : survol = détail, barre d'outils = zoom et export PNG.
Double-clic sur un joueur dans n'importe quel tableau → sa fiche. **Ctrl+K** : recherche globale (joueurs, équipes, pages).
Matchs en cours actualisés automatiquement (mode direct). Rapports PDF de fiches joueurs, de matchs et d'avant-match.
La compétition, la saison et la page ouvertes sont retrouvées au lancement suivant ; l'appli signale les nouvelles versions publiées.
Utilisable sur un écran 1920 x 1080 à 150 % (fenêtre de 1280 x 650 : les pages défilent au lieu de se tasser).

<p>
  <img src="docs/screenshots/classement-xg.png" width="49%">
  <img src="docs/screenshots/pronostics.png" width="49%">
  <img src="docs/screenshots/valeur-performance.png" width="49%">
  <img src="docs/screenshots/avant-match.png" width="49%">
  <img src="docs/screenshots/fiabilite-pronostics.png" width="49%">
  <img src="docs/screenshots/tirs-heatmap.png" width="49%">
  <img src="docs/screenshots/historique-equipe.png" width="49%">
  <img src="docs/screenshots/indices.png" width="49%">
  <img src="docs/screenshots/comparaison-equipes.png" width="49%">
  <img src="docs/screenshots/recherche-avancee.png" width="49%">
  <img src="docs/screenshots/theme-clair.png" width="49%">
  <img src="docs/screenshots/fiche-joueur.png" width="49%">
  <img src="docs/screenshots/comparaison.png" width="49%">
  <img src="docs/screenshots/profils-similaires.png" width="49%">
  <img src="docs/screenshots/xg-cumules.png" width="49%">
  <img src="docs/screenshots/match.png" width="49%">
  <img src="docs/screenshots/joueurs.png" width="49%">
</p>

## Installation

### Windows : installeur (recommandé)
Télécharger `FootAnalytics-Setup-<version>.exe` dans les [Releases](../../releases) (ou l'artefact du dernier
build dans l'onglet *Actions*) et le lancer : installation sans droits administrateur, raccourcis menu Démarrer
et Bureau, désinstallation depuis les paramètres Windows. Une version portable (`.zip`) est aussi fournie.
Aucune installation de Python nécessaire.

### macOS (Apple Silicon, macOS 14 ou plus récent)
Télécharger `FootAnalytics-<version>-macos-arm64.zip`, le décompresser et glisser `FootAnalytics.app` dans
*Applications*. L'application n'est pas signée par un développeur identifié Apple (signature ad hoc seulement) :
Gatekeeper la bloque au premier lancement. Au choix :
- clic droit (ou Ctrl-clic) sur l'application > **Ouvrir**, puis **Ouvrir** dans la boîte de dialogue
  (sur macOS 15 : *Réglages Système > Confidentialité et sécurité > Ouvrir quand même*) ;
- ou retirer l'attribut de quarantaine dans le Terminal :
  `xattr -dr com.apple.quarantine /Applications/FootAnalytics.app`

Données : `~/Library/Application Support/FootAnalytics`.

### Linux (x86_64, glibc 2.34 ou plus récent : Ubuntu 22.04, Debian 12, Fedora 35…)
```bash
tar -xzf FootAnalytics-<version>-linux-x86_64.tar.gz
./FootAnalytics/FootAnalytics
```
Bibliothèques système requises (déjà présentes sur un bureau courant) ; sur Debian/Ubuntu :
`sudo apt install libegl1 libgl1 libfontconfig1 libdbus-1-3 libxkbcommon-x11-0 libxcb-cursor0`.
Données : `$XDG_DATA_HOME/FootAnalytics` (par défaut `~/.local/share/FootAnalytics`).

### Depuis les sources
```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock   # versions exactes
.\.venv\Scripts\python.exe main.py
```
Sous macOS et Linux : `python3 -m venv .venv`, puis `.venv/bin/python -m pip install -r requirements.lock` et
`.venv/bin/python main.py`.

### Construire l'application
```powershell
powershell -ExecutionPolicy Bypass -File build.ps1
# -> dist\FootAnalytics\ (application), dist\FootAnalytics-<version>-portable.zip,
#    dist\FootAnalytics-Setup-<version>.exe (si Inno Setup 6 est installé : winget install JRSoftware.InnoSetup)
```
Sous macOS et Linux :
```bash
./build.sh
# macOS -> dist/FootAnalytics.app (signée ad hoc) et dist/FootAnalytics-<version>-macos-arm64.zip
# Linux -> dist/FootAnalytics/ et dist/FootAnalytics-<version>-linux-x86_64.tar.gz
```
Le workflow GitHub Actions (`.github/workflows/build.yml`) le fait automatiquement à chaque push sur `main`, sur
Windows, macOS et Linux (tests sur les trois systèmes) ; pousser un tag `v*` (ex. `git tag v2.5.0 && git push --tags`)
publie l'installeur et les archives des trois systèmes dans une Release.
L'icône (`.png`, `.ico`, `.icns`) se régénère avec `python tools\make_icon.py`.

## Développement

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt   # dépendances + outils (versions figées)
.\.venv\Scripts\python.exe -m ruff check .              # qualité du code (configuration : pyproject.toml)
.\.venv\Scripts\python.exe -m mypy                      # vérification des types (configuration : pyproject.toml)
.\.venv\Scripts\python.exe -m pytest -q                 # tests hors ligne, interface comprise
.\.venv\Scripts\python.exe -m pytest -q --cov=footapp   # idem + couverture (lignes manquantes, plancher 85 %)
$env:FOOT_LIVE="1"; .\.venv\Scripts\python.exe -m pytest tests/test_live.py   # contre la vraie API
.\.venv\Scripts\python.exe -m tests.record_fixtures      # ré-enregistrer les réponses de référence
.\.venv\Scripts\python.exe -m tests.record_fixtures --history   # n'ajouter que l'historique d'une équipe
.\.venv\Scripts\python.exe -m tests.record_fixtures --prematch  # n'ajouter que l'avant-match d'un match à venir
```

- **Dépendances** : `requirements.txt` liste les dépendances directes ; `requirements.lock` fige toutes les
  versions (directes et indirectes) pour des builds reproductibles. Pour les mettre à jour : environnement
  vierge, `pip install -r requirements.txt`, puis `pip freeze > requirements.lock`.
- **Tests** : réponses API réelles enregistrées (aucun réseau). Ils vérifient que chaque métrique demandée est
  toujours renseignée (si Sofascore renomme un champ, le test indique lequel), que le modèle de pronostic ne
  « connaît » pas l'avenir, et que chaque page de l'interface s'ouvre sans erreur (Qt sans fenêtre visible).
  Les clients HTTP sont testés avec des sessions factices (codes HTTP, empreintes refusées, cache, repli hors
  ligne). Couverture ≈ 90 % (tâches de fond comprises) ; `pytest --cov` échoue sous 85 %.
- **Types** : mypy vérifie tout le code ; le cœur (`analysis`, `data`, `api`, `config`, `logs`, `updates`) est
  entièrement annoté. Côté interface, énumérations Qt en nom complet (`Qt.AlignmentFlag.AlignLeft`) et
  `widgets.named()` pour nommer un widget ; ne jamais donner à un attribut le nom d'une méthode Qt (`event`,
  `metric`, `palette`, `actions`…) : PySide6 prendrait l'attribut pour une surcharge de la méthode virtuelle.
- **Intégration continue** (GitHub Actions) : ruff, mypy, pip-audit, tests avec couverture sous Windows, macOS
  et Linux, puis construction de l'installeur et des archives macOS et Linux (l'application construite est lancée
  pour vérifier qu'elle démarre) ; sur un tag, vérification que le tag correspond à la version de l'application
  avant publication.
- **Journal** : `logs/footanalytics.log` dans le dossier de données (Windows : `%LOCALAPPDATA%\FootAnalytics`,
  macOS : `~/Library/Application Support/FootAnalytics`, Linux : `~/.local/share/FootAnalytics`) :
  erreurs avec leur trace complète, accessible depuis Aide & paramètres.

## Performances

- Pages construites à leur première ouverture ; une page cachée ne recalcule rien (mises à jour différées).
- Données affichées immédiatement depuis le cache (même expiré), puis rafraîchies en arrière-plan.
- Valeurs et contrats chargés seulement à l'ouverture de la page Valeur vs performance ou à l'usage d'un filtre
  (une requête par équipe, réponses allégées à ~2 % de leur taille avant mise en cache, 3 jours) ; 5 grands
  championnats (~100 équipes) sur demande explicite uniquement.
- Écran de chargement affiché avant le chargement des bibliothèques ; modules lourds (PDF) chargés à la demande.
- Application allégée de moitié (~140 Mo installée) : terrain de football dessiné sans mplsoccer ni scipy,
  composants Qt inutilisés retirés du build.

## Sécurité

- Données reçues d'Internet jamais interprétées comme du HTML dans l'interface ; exports Excel/CSV protégés
  contre l'injection de formules ; lien de mise à jour vérifié (Releases de ce dépôt uniquement).
- Cache en JSON uniquement (jamais de code exécutable), écrit de façon atomique, purgé automatiquement.
- Dépendances vérifiées avec `pip-audit` ; build GitHub en lecture seule hors publication, actions figées
  sur des commits précis.

## Données

Sources : API JSON publique utilisée par le site sofascore.com (non officielle, sans clé), interrogée via
`curl_cffi` qui imite un navigateur ; **Understat** pour les xG par match, xPts et PPDA des 5 grands championnats,
et comme source de secours si Sofascore est indisponible ; **ESPN** (API JSON non officielle, sans clé) en dernier
recours, seulement après un échec des autres sources : classement, résultats et calendrier uniquement (ni xG ni
fiches joueurs) pour la Ligue 2, le Championship, l'Eredivisie, la Liga Portugal, la MLS, le Brasileirão, la Ligue
des champions, la Ligue Europa et les 5 grands championnats.

- **Usage personnel / expérimental uniquement** : l'API n'est pas documentée et ses conditions
  n'autorisent pas un usage commercial.
- Elle peut changer ou bloquer sans préavis : tout l'accès réseau est isolé dans `footapp/api/sofascore.py`.
- Cache disque dans le sous-dossier `cache` du dossier de données (Windows : `%LOCALAPPDATA%\FootAnalytics`) : matchs terminés conservés définitivement,
  le reste de 15 min à 12 h (effectifs, valeurs et contrats : 3 jours). Le bouton « Actualiser » vide le cache
  temporaire.
- Valeurs marchandes : estimations Sofascore (pas des prix de transfert) ; effectifs, âges et contrats décrivent
  la saison en cours uniquement.

## Structure

```
main.py                       point d'entrée
footapp/
  config.py                   compétitions, catalogue des métriques et libellés
  api/sofascore.py            client HTTP + cache disque (JSON et images)
  api/understat.py            client Understat (xG par match, xPts, PPDA, secours)
  api/espn.py                 client ESPN (secours réduit : classement, résultats, calendrier)
  data.py                     appels API -> DataFrames pandas (+ métriques dérivées)
  analysis.py                 par 90 min, centiles, profils similaires, recherche, Poisson (xPts, pronostics),
                              valeur vs performance (régression robuste de Huber), profils types (k-means, ACP)
  updates.py                  vérification des Releases GitHub
  logs.py                     journal (fichier tournant, erreurs non gérées)
  ui/
    main_window.py            fenêtre : navigation latérale + barre de contexte
    state.py                  état partagé, chargement « cache d'abord »
    settings.py               paramètres utilisateur
    theme.py                  couleurs, feuille de style Qt, style matplotlib
    widgets.py                cartes, tuiles, tableaux, graphiques, images, tâches de fond
    charts.py                 tous les graphiques (matplotlib)
    pitch.py                  terrain de football et heatmaps lissées
    report.py                 rapports PDF
    palette.py                recherche globale Ctrl+K
    pages/                    une page par section
tests/                        tests pytest (données, analyse, clients HTTP, interface, sécurité) + réponses API enregistrées
```

**Ajouter une compétition** : `(nom, id)` dans `COMPETITIONS` (l'id figure dans l'URL Sofascore du tournoi).
**Ajouter une métrique joueur ou équipe** : une ligne dans `PLAYER_METRICS` / `TEAM_METRICS`.

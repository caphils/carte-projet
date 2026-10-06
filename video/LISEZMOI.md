# Vidéo de présentation

Vidéo de présentation de la skill (≈ 1 min 40), **produite par programme** sur la carte du site officiel de Django
(`github.com/django/djangoproject.com`, cloné dans `video/build/`) : à refaire après une évolution de la page.

| Étape | Script | Sortie |
|---|---|---|
| Tournage : Chrome piloté par Playwright sur `analyser.py --serveur`, écran enregistré image par image | `scenario.py` (+ `tournage.py`) | `build/carte_projet/` |
| Montage : curseur, clics, zooms, légendes, cartons, encodage MP4 1920 × 1080 | `montage.py` | `sortie/carte_projet.mp4` (muette) |
| Voix off et rythme resserré sur la voix, sous-titres | `sonoriser.py` (+ `cloner.py`) | `sortie/carte_projet_voix.mp4`, `.srt` |

## Produire

Environnement : Python avec `playwright`, `pillow`, `imageio-ffmpeg` (et `edge-tts` pour la voix Microsoft) ; Google
Chrome installé.

```bash
python video/scenario.py
python video/montage.py carte_projet "La carte reliée de votre code"
python video/sonoriser.py                                         # voix clonée (échantillon ECHANTILLON)
VOIX=fr-FR-VivienneMultilingualNeural python video/sonoriser.py   # ou voix Microsoft
```

La voix clonée (Chatterbox multilingue, calculée sur la machine) demande un environnement à part (`PYTHON_CLONE`,
Python 3.11 : `chatterbox-tts`) et un échantillon de voix (`ECHANTILLON`, jamais versionné). Par défaut, les deux sont
repris du studio vidéo de LabManager (`LABMANAGER`).

## Modifier

- Texte d'une légende ou d'un carton : `scenario.py`, et la réplique correspondante dans `sonoriser.py` (`REPLIQUES`,
  une par carton et par légende, dans le même ordre).
- Couleurs, logo, mise en page : `montage.py`. Prononciation : `PRONONCIATION` dans `sonoriser.py`.
- En cas d'échec du tournage, une copie d'écran est écrite dans `build/carte_projet/erreur.png`.

"""Voix clonée, calculée sur cette machine (rien n'est envoyé en ligne) : Chatterbox multilingue (Resemble AI, licence
MIT) imite la voix de l'échantillon ma voix.* (jamais versionné). Appelé par sonoriser.py, dans son propre
environnement (Python 3.11, torch) :

    uv venv --python 3.11 .venv-clone
    uv pip install --python .venv-clone/bin/python chatterbox-tts "setuptools<81"

    python video/cloner.py <reference.wav> <commandes.json>

commandes.json : [{"texte": ..., "chemin": ...}] ; seules les répliques absentes sont calculées (≈ 35 s chacune sur
processeur, plus rapide que la puce graphique pour ce modèle).
"""
import json
import sys
import time
from pathlib import Path

import torch
import torchaudio
from chatterbox.mtl_tts import ChatterboxMultilingualTTS


def main(reference, commandes):
    a_faire = [c for c in json.loads(Path(commandes).read_text(encoding="utf-8")) if not Path(c["chemin"]).exists()]
    if not a_faire:
        return
    torch.manual_seed(7)  # même texte, même diction d'une production à l'autre
    modele = ChatterboxMultilingualTTS.from_pretrained(device="cpu")
    modele.prepare_conditionals(reference)
    for rang, commande in enumerate(a_faire, 1):
        debut = time.time()
        son = modele.generate(commande["texte"], language_id="fr")
        torchaudio.save(commande["chemin"], son, modele.sr)
        print(f"  voix clonée {rang}/{len(a_faire)} ({time.time() - debut:.0f} s) : {commande['texte'][:60]}",
              flush=True)


if __name__ == "__main__":
    main(*sys.argv[1:3])

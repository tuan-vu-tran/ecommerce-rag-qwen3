"""
test_stream.py
==============
Script de test CLI pour valider les 2 améliorations :
  1. STREAMING de la génération (generer_reponse_stream / repondre_stream)
  2. SYSTEM PROMPT STRICT (refus hors-sujet, pas d'invention de produit)

Il exécute 3 cas et affiche le flux tel qu'il arrive, puis vérifie le bloc
produits final.

Usage :
    conda activate rag-qwen
    python backend/test_stream.py
"""

import sys

from ingestion import obtenir_collection
from rag_pipeline import MARQUEUR_PRODUITS, repondre_stream

CAS = [
    ("a) HORS-SUJET (culture générale)", "Quelle est la capitale de la France ?"),
    ("b) PRODUIT ABSENT du catalogue", "Avez-vous des vélos électriques ?"),
    ("c) QUESTION NORMALE produit", "Je cherche un bon PC portable pour jouer, budget correct."),
]


def run_cas(titre, question, collection):
    print("\n" + "=" * 72)
    print(f"  CAS {titre}")
    print(f"  Question : {question}")
    print("=" * 72)

    # On accumule le flux pour, à la fin, séparer texte / bloc produits.
    complet = ""
    print("\n[FLUX en direct] ", end="", flush=True)
    for morceau in repondre_stream(question, collection=collection):
        # On affiche le texte avant marqueur au fil de l'eau (streaming réel).
        complet += morceau
        if MARQUEUR_PRODUITS not in complet:
            sys.stdout.write(morceau)
            sys.stdout.flush()

    avant, _, apres = complet.partition(MARQUEUR_PRODUITS)
    print("\n\n--- TEXTE FINAL ---")
    print(avant.strip())
    print("\n--- BLOC PRODUITS (JSON) ---")
    print(apres.strip() or "[]")


def main():
    collection = obtenir_collection()
    if collection.count() == 0:
        print("❌ Collection vide. Lance d'abord : python backend/ingestion.py")
        sys.exit(1)

    for titre, question in CAS:
        run_cas(titre, question, collection)

    print("\n" + "=" * 72)
    print("  Tests terminés. Vérifie :")
    print("   a) refus poli + produits []")
    print("   b) dit qu'il n'y a pas ce type de produit + produits []")
    print("   c) réponse utile + au moins 1 produit recommandé")
    print("=" * 72)


if __name__ == "__main__":
    main()

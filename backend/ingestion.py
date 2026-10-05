"""
ingestion.py
============
Charge le catalogue de produits (data/catalogue.json), génère un embedding
pour la DESCRIPTION de chaque produit via le modèle Ollama
`qwen3-embedding:0.6b`, puis stocke le tout dans une base ChromaDB persistante
(dossier chroma_db/).

Nouveau format de catalogue (RAG texte pur) :
    [
      {"id": "48213", "description": "..."},
      ...
    ]
Il n'y a plus AUCUN champ structuré (ni catégorie, ni prix, ni marque...).
Toutes les infos utiles sont contenues dans le texte de la description.

Points clés :
- ChromaDB en mode persistant (PersistentClient) : embeddings écrits sur disque.
- Idempotent : `upsert()` avec l'`id` produit comme identifiant (pas de doublon).
- La collection est VIDÉE puis recréée à chaque ingestion complète, pour éviter
  de garder des entrées d'un ancien format devenu invalide.

Les chemins (catalogue, base ChromaDB) et l'URL d'Ollama sont configurables par
variables d'environnement (voir config.py) : CATALOGUE_PATH, CHROMA_PATH,
OLLAMA_HOST. Sans rien définir, les valeurs par défaut sont celles du projet.

Usage :
    python backend/ingestion.py            # (ré)ingère le catalogue
    python backend/ingestion.py --check    # affiche ce qui est indexé
"""

import argparse
import json
import os
import sys

import chromadb

# Chemins et client Ollama viennent de config.py (surchargables par variables
# d'environnement ; les défauts reproduisent le comportement historique).
from config import CHEMIN_CATALOGUE, CHEMIN_CHROMA, OLLAMA_HOST, client_ollama

MODELE_EMBEDDING = "qwen3-embedding:0.6b"
NOM_COLLECTION = "produits"


# --------------------------------------------------------------------------
# Étape 1 : charger le catalogue JSON
# --------------------------------------------------------------------------
def charger_catalogue(chemin=CHEMIN_CATALOGUE):
    """Lit catalogue.json et renvoie la liste des produits (id + description)."""
    if not os.path.exists(chemin):
        raise FileNotFoundError(
            f"Catalogue introuvable : {chemin}\n"
            "Vérifie que data/catalogue.json existe."
        )
    with open(chemin, "r", encoding="utf-8") as f:
        try:
            produits = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"catalogue.json est mal formé (JSON invalide) : {e}")

    if not isinstance(produits, list) or len(produits) == 0:
        raise ValueError("Le catalogue doit être une liste non vide de produits.")

    # Contrôle minimal : chaque produit a bien un id et une description.
    for p in produits:
        if "id" not in p or "description" not in p:
            raise ValueError(
                "Chaque produit doit contenir les champs 'id' et 'description'. "
                f"Produit fautif : {p}"
            )
    return produits


# --------------------------------------------------------------------------
# Étape 2 : accès à la collection ChromaDB persistante
# --------------------------------------------------------------------------
def _client():
    """Renvoie le client ChromaDB persistant."""
    return chromadb.PersistentClient(path=CHEMIN_CHROMA)


def obtenir_collection():
    """
    Ouvre (ou crée) la collection. On ne fournit PAS d'embedding function :
    on calcule nous-mêmes les vecteurs avec Ollama pour maîtriser le modèle.
    """
    return _client().get_or_create_collection(
        name=NOM_COLLECTION,
        metadata={"description": "Catalogue produits e-commerce (RAG texte pur)"},
    )


def reinitialiser_collection():
    """
    Supprime la collection existante puis la recrée vide.
    Utile parce que le format des données a changé : on ne veut pas mélanger
    d'anciennes entrées (ancien format) avec les nouvelles.
    """
    client = _client()
    try:
        client.delete_collection(name=NOM_COLLECTION)
    except Exception:
        # La collection n'existe pas encore : rien à supprimer.
        pass
    return client.get_or_create_collection(
        name=NOM_COLLECTION,
        metadata={"description": "Catalogue produits e-commerce (RAG texte pur)"},
    )


# --------------------------------------------------------------------------
# Étape 3 : générer les embeddings via Ollama
# --------------------------------------------------------------------------
def generer_embeddings(textes):
    """Encode une liste de textes avec le modèle d'embedding Ollama."""
    try:
        reponse = client_ollama.embed(model=MODELE_EMBEDDING, input=textes)
    except Exception as e:
        raise ConnectionError(
            f"Impossible de générer les embeddings via Ollama ({OLLAMA_HOST}).\n"
            "Vérifie qu'Ollama tourne (ollama serve) et que le modèle "
            f"'{MODELE_EMBEDDING}' est installé.\n"
            f"Détail : {e}"
        )
    return reponse["embeddings"]


# --------------------------------------------------------------------------
# Étape 4 : ingestion complète
# --------------------------------------------------------------------------
def ingerer():
    """Pipeline d'ingestion : JSON -> embeddings (sur la description) -> ChromaDB."""
    print("→ Chargement du catalogue...")
    produits = charger_catalogue()
    print(f"  {len(produits)} produits chargés.")

    ids = [str(p["id"]) for p in produits]
    documents = [p["description"] for p in produits]
    # Seule métadonnée conservée : l'id (pratique pour l'affichage). Il n'y a
    # plus aucun champ structuré à filtrer, la recherche sera 100% sémantique.
    metadatas = [{"id": str(p["id"])} for p in produits]

    print(f"→ Génération des embeddings via '{MODELE_EMBEDDING}' (sur la description)...")
    embeddings = generer_embeddings(documents)
    print(f"  {len(embeddings)} embeddings générés (dimension {len(embeddings[0])}).")

    print("→ Réinitialisation de la collection (vidage + recréation)...")
    collection = reinitialiser_collection()

    print("→ Écriture dans ChromaDB (upsert sur id, idempotent)...")
    collection.upsert(
        ids=ids,
        embeddings=embeddings,
        documents=documents,
        metadatas=metadatas,
    )

    total = collection.count()
    print(f"✓ Ingestion terminée. {total} produits dans la collection '{NOM_COLLECTION}'.")
    return total


# --------------------------------------------------------------------------
# Vérification : afficher ce qui est réellement indexé
# --------------------------------------------------------------------------
def verifier():
    """Affiche un résumé de la collection pour valider l'indexation."""
    collection = obtenir_collection()
    total = collection.count()
    print(f"Collection '{NOM_COLLECTION}' : {total} produits indexés.\n")

    if total == 0:
        print("(Vide — lance d'abord `python backend/ingestion.py`.)")
        return

    data = collection.get(include=["documents"])
    lignes = sorted(zip(data["ids"], data["documents"]), key=lambda x: x[0])
    print(f"{'ID':<10} EXTRAIT DE DESCRIPTION")
    print("-" * 90)
    for pid, doc in lignes:
        extrait = doc[:75].replace("\n", " ")
        print(f"{pid:<10} {extrait}...")


# --------------------------------------------------------------------------
# Point d'entrée CLI
# --------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Ingestion du catalogue dans ChromaDB.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Affiche uniquement le contenu déjà indexé (sans réingérer).",
    )
    args = parser.parse_args()

    try:
        if args.check:
            verifier()
        else:
            ingerer()
            print()
            verifier()
    except (FileNotFoundError, ValueError, ConnectionError) as e:
        print(f"\n❌ Erreur : {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

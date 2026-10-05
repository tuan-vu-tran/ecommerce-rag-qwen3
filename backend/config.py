"""
config.py
=========
Configuration centralisée du backend, pilotée par variables d'environnement.

Toutes les valeurs par défaut reproduisent EXACTEMENT le comportement historique
(lancement local hors Docker) : sans aucune variable définie, le projet tourne
comme avant. Les variables ne servent qu'à adapter le déploiement (Docker,
chemins montés, Ollama sur l'hôte).

Variables reconnues :
    OLLAMA_HOST     URL du serveur Ollama        (défaut http://localhost:11434)
    CHROMA_PATH     dossier de la base ChromaDB  (défaut <racine>/chroma_db)
    CATALOGUE_PATH  fichier catalogue JSON       (défaut <racine>/data/catalogue.json)
    CORS_ORIGINS    origines autorisées, séparées par des virgules
                    (défaut http://localhost:3000,http://localhost:5173)
"""

import os

import ollama

# Racine du projet = dossier parent de backend/
RACINE_PROJET = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# --------------------------------------------------------------------------
# Chemins
# --------------------------------------------------------------------------
CHEMIN_CATALOGUE = os.environ.get(
    "CATALOGUE_PATH",
    os.path.join(RACINE_PROJET, "data", "catalogue.json"),
)
CHEMIN_CHROMA = os.environ.get(
    "CHROMA_PATH",
    os.path.join(RACINE_PROJET, "chroma_db"),
)

# --------------------------------------------------------------------------
# Ollama
# --------------------------------------------------------------------------
# Sous Docker, le backend tourne dans un conteneur alors qu'Ollama reste sur
# l'hôte (il a besoin du GPU) : on pointe alors vers host.docker.internal.
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

# Un seul client partagé par tout le backend : ainsi TOUS les appels Ollama
# (embeddings, génération, ping /health) visent bien le même serveur.
client_ollama = ollama.Client(host=OLLAMA_HOST)

# --------------------------------------------------------------------------
# CORS
# --------------------------------------------------------------------------
_ORIGINES_DEFAUT = "http://localhost:3000,http://localhost:5173"
CORS_ORIGINS = [
    origine.strip()
    for origine in os.environ.get("CORS_ORIGINS", _ORIGINES_DEFAUT).split(",")
    if origine.strip()
]

"""
conftest.py
===========
Fixtures partagées par les tests du backend.

PRINCIPE : aucun test par défaut ne doit toucher un vrai serveur Ollama ni une
vraie base ChromaDB. On remplace donc, AVANT l'import de `api`, les deux seuls
points de contact :

  - `ingestion.obtenir_collection()` -> une fausse collection en mémoire
    (`CollectionFactice`) ;
  - `config.client_ollama` -> un faux client (`ClientOllamaFactice`).

Le catalogue, lui, est le VRAI `data/catalogue.json` : c'est un simple fichier
texte, aucune dépendance externe, et on veut tester les endpoints /produits sur
les données réelles.
"""

import importlib
import json
import os
import sys

import pytest

# backend/ doit être importable (`import api`, `import config`...) comme quand
# uvicorn est lancé depuis ce dossier.
DOSSIER_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if DOSSIER_BACKEND not in sys.path:
    sys.path.insert(0, DOSSIER_BACKEND)

RACINE_PROJET = os.path.dirname(DOSSIER_BACKEND)
CHEMIN_CATALOGUE_REEL = os.path.join(RACINE_PROJET, "data", "catalogue.json")


# --------------------------------------------------------------------------
# Doublures
# --------------------------------------------------------------------------
class CollectionFactice:
    """Imite le strict minimum de l'API ChromaDB utilisé par le backend."""

    def __init__(self, produits):
        self._produits = produits

    def count(self):
        return len(self._produits)

    def query(self, query_embeddings=None, n_results=5, **_):
        """Renvoie les `n_results` premiers produits, au format ChromaDB."""
        echantillon = self._produits[:n_results]
        return {
            "ids": [[str(p["id"]) for p in echantillon]],
            "documents": [[p["description"] for p in echantillon]],
            "distances": [[0.1 * (i + 1) for i in range(len(echantillon))]],
            "metadatas": [[None] * len(echantillon)],
        }


class ClientOllamaFactice:
    """Faux client Ollama : répond sans réseau, et trace les appels reçus."""

    def __init__(self):
        self.appels = []

    def list(self):
        self.appels.append(("list", None))
        return {"models": []}

    def embed(self, model=None, input=None):
        self.appels.append(("embed", input))
        return {"embeddings": [[0.0] * 1024]}

    def chat(self, model=None, messages=None, stream=False, **_):
        self.appels.append(("chat", messages))
        if not stream:
            return {"message": {"content": "question reformulée factice"}}
        raise AssertionError(
            "Aucun test par défaut ne doit streamer via Ollama : "
            "mocke generer_reponse_stream."
        )


@pytest.fixture
def catalogue():
    """Le vrai catalogue (30 produits) chargé depuis data/catalogue.json."""
    with open(CHEMIN_CATALOGUE_REEL, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def ollama_factice():
    return ClientOllamaFactice()


@pytest.fixture
def client(monkeypatch, catalogue, ollama_factice):
    """
    TestClient FastAPI sur une app `api` fraîchement importée, avec Ollama et
    ChromaDB mockés. `api` est rechargé à chaque test parce qu'il ouvre la
    collection et charge le catalogue AU MOMENT DE L'IMPORT.
    """
    from fastapi.testclient import TestClient

    import config
    import ingestion

    collection = CollectionFactice(catalogue)
    monkeypatch.setattr(ingestion, "obtenir_collection", lambda: collection)
    monkeypatch.setattr(config, "client_ollama", ollama_factice)

    # `rag_pipeline` et `api` capturent `client_ollama` par `from config import`
    # au moment de leur import : on les recharge pour qu'ils prennent le faux.
    import rag_pipeline
    monkeypatch.setattr(rag_pipeline, "client_ollama", ollama_factice)

    for module in ("api",):
        sys.modules.pop(module, None)
    api = importlib.import_module("api")
    monkeypatch.setattr(api, "client_ollama", ollama_factice)

    with TestClient(api.app) as c:
        c.module_api = api          # accès à l'app pour les monkeypatch des tests
        c.collection_factice = collection
        yield c

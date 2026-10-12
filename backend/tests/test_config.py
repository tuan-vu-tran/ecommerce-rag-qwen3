"""
test_config.py
==============
`config.py` lit sa configuration dans l'environnement AU MOMENT DE L'IMPORT :
chaque test recharge donc le module avec `importlib.reload` après avoir posé
(ou retiré) les variables. Aucun appel réseau : `ollama.Client(host=...)` ne se
connecte pas à la création.
"""

import importlib
import os

import pytest

import config as config_module

VARIABLES = ("OLLAMA_HOST", "CHROMA_PATH", "CATALOGUE_PATH", "CORS_ORIGINS")


@pytest.fixture
def recharger_config(monkeypatch):
    """Recharge `config` avec un environnement donné, puis restaure l'original."""
    def _recharger(**variables):
        for nom in VARIABLES:
            monkeypatch.delenv(nom, raising=False)
        for nom, valeur in variables.items():
            monkeypatch.setenv(nom, valeur)
        return importlib.reload(config_module)

    yield _recharger
    # Remet le module dans l'état correspondant à l'environnement réel.
    importlib.reload(config_module)


# --------------------------------------------------------------------------
# Valeurs par défaut (= lancement local hors Docker)
# --------------------------------------------------------------------------
def test_defauts_sans_aucune_variable(recharger_config):
    config = recharger_config()

    assert config.OLLAMA_HOST == "http://localhost:11434"
    assert config.CHEMIN_CHROMA == os.path.join(config.RACINE_PROJET, "chroma_db")
    assert config.CHEMIN_CATALOGUE == os.path.join(
        config.RACINE_PROJET, "data", "catalogue.json"
    )
    assert config.CORS_ORIGINS == [
        "http://localhost:3000",
        "http://localhost:5173",
    ]


def test_client_ollama_unique_pointe_sur_ollama_host(recharger_config):
    """Un seul client partagé, construit sur OLLAMA_HOST."""
    config = recharger_config(OLLAMA_HOST="http://host.docker.internal:11434")
    assert config.client_ollama is not None
    assert "host.docker.internal" in str(config.client_ollama._client.base_url)


# --------------------------------------------------------------------------
# Surcharges par variables d'environnement
# --------------------------------------------------------------------------
def test_ollama_host_depuis_lenvironnement(recharger_config):
    config = recharger_config(OLLAMA_HOST="http://ollama-distant:9999")
    assert config.OLLAMA_HOST == "http://ollama-distant:9999"


def test_chemins_depuis_lenvironnement(recharger_config):
    config = recharger_config(
        CHROMA_PATH="/data/chroma",
        CATALOGUE_PATH="/data/catalogue.json",
    )
    assert config.CHEMIN_CHROMA == "/data/chroma"
    assert config.CHEMIN_CATALOGUE == "/data/catalogue.json"


def test_cors_origins_est_decoupe_sur_les_virgules(recharger_config):
    config = recharger_config(
        CORS_ORIGINS="http://a.test, http://b.test ,http://c.test"
    )
    assert config.CORS_ORIGINS == ["http://a.test", "http://b.test", "http://c.test"]


def test_cors_origins_ignore_les_entrees_vides(recharger_config):
    config = recharger_config(CORS_ORIGINS="http://a.test,,  ,")
    assert config.CORS_ORIGINS == ["http://a.test"]

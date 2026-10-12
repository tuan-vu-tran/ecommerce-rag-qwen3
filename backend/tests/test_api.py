"""
test_api.py
===========
Tests des endpoints HTTP. Ollama et ChromaDB sont mockés par la fixture
`client` (voir conftest.py) : aucun test ici n'ouvre de connexion réseau.
"""

import pytest

from rag_pipeline import MARQUEUR_PRODUITS


# --------------------------------------------------------------------------
# GET /health
# --------------------------------------------------------------------------
def test_health_repond_200(client):
    reponse = client.get("/health")
    assert reponse.status_code == 200

    corps = reponse.json()
    assert corps["status"] == "ok"
    assert corps["ollama"] is True
    # Le ping passe par le faux client : la collection factice compte 30 produits.
    assert corps["produits_indexes"] == 30


def test_health_degrade_si_ollama_injoignable(client):
    """Ollama KO -> l'API répond quand même 200, avec status 'degraded'."""
    def ping_casse():
        raise ConnectionError("boom")

    client.module_api.client_ollama.list = ping_casse

    corps = client.get("/health").json()
    assert corps["status"] == "degraded"
    assert corps["ollama"] is False


# --------------------------------------------------------------------------
# GET /produits
# --------------------------------------------------------------------------
def test_liste_produits_renvoie_30_produits(client):
    reponse = client.get("/produits")
    assert reponse.status_code == 200

    produits = reponse.json()
    assert len(produits) == 30
    assert all({"id", "description"} == set(p) for p in produits)


# --------------------------------------------------------------------------
# GET /produits/{id}
# --------------------------------------------------------------------------
def test_fiche_produit_id_existant(client, catalogue):
    id_attendu = str(catalogue[0]["id"])

    reponse = client.get(f"/produits/{id_attendu}")
    assert reponse.status_code == 200

    produit = reponse.json()
    assert produit["id"] == id_attendu
    assert produit["description"] == catalogue[0]["description"]


def test_fiche_produit_id_inconnu_renvoie_404(client):
    reponse = client.get("/produits/000000")
    assert reponse.status_code == 404
    assert "000000" in reponse.json()["detail"]


# --------------------------------------------------------------------------
# POST /chat
# --------------------------------------------------------------------------
def test_chat_corps_invalide_renvoie_422(client):
    """Champ obligatoire `question` absent -> validation Pydantic -> 422."""
    reponse = client.post("/chat", json={"historique": []})
    assert reponse.status_code == 422


def test_chat_question_vide_renvoie_400(client):
    reponse = client.post("/chat", json={"question": "   "})
    assert reponse.status_code == 400


def test_chat_streame_texte_puis_produits(client, catalogue):
    """
    Pipeline mocké : on vérifie que l'API renvoie 200 et streame bien le texte
    attendu, suivi du marqueur et du JSON produits.
    """
    candidats = [
        {"id": str(p["id"]), "description": p["description"], "distance": 0.1}
        for p in catalogue[:5]
    ]

    appels = {}

    def faux_preparer_recherche(question, historique, collection):
        appels["question"] = question
        appels["historique"] = historique
        return "question reformulée", candidats

    def faux_stream(question, produits, historique=None):
        assert produits == candidats
        yield "Voici "
        yield "mes conseils."
        yield "\n" + MARQUEUR_PRODUITS + "\n"
        yield '[{"id": "%s", "raison": "parfait"}]' % candidats[0]["id"]

    client.module_api.preparer_recherche = faux_preparer_recherche
    client.module_api.generer_reponse_stream = faux_stream

    reponse = client.post("/chat", json={"question": "un portable pour jouer"})
    assert reponse.status_code == 200
    assert reponse.headers["content-type"].startswith("text/plain")

    corps = reponse.text
    texte, _, bloc = corps.partition(MARQUEUR_PRODUITS)
    assert texte.strip() == "Voici mes conseils."
    assert candidats[0]["id"] in bloc
    assert appels["question"] == "un portable pour jouer"


def test_chat_503_si_ollama_injoignable(client):
    """`preparer_recherche` lève ConnectionError -> 503 avant l'ouverture du flux."""
    def preparer_casse(question, historique, collection):
        raise ConnectionError("Ollama injoignable")

    client.module_api.preparer_recherche = preparer_casse

    reponse = client.post("/chat", json={"question": "un portable"})
    assert reponse.status_code == 503
    assert "Ollama injoignable" in reponse.json()["detail"]


def test_chat_transmet_historique_au_pipeline(client):
    recu = {}

    def faux_preparer_recherche(question, historique, collection):
        recu["historique"] = historique
        return question, []

    def faux_stream(question, produits, historique=None):
        recu["historique_stream"] = historique
        yield "ok"
        yield "\n" + MARQUEUR_PRODUITS + "\n"
        yield "[]"

    client.module_api.preparer_recherche = faux_preparer_recherche
    client.module_api.generer_reponse_stream = faux_stream

    reponse = client.post("/chat", json={
        "question": "et moins cher ?",
        "historique": [{"role": "user", "content": "un portable gamer"}],
    })
    assert reponse.status_code == 200
    assert recu["historique"] == [{"role": "user", "content": "un portable gamer"}]
    assert recu["historique_stream"] == recu["historique"]


# --------------------------------------------------------------------------
# Test d'intégration : exclu par défaut (voir pytest.ini)
# --------------------------------------------------------------------------
@pytest.mark.integration
def test_chat_bout_en_bout_avec_ollama():
    """Nécessite un vrai Ollama + un index ChromaDB rempli : `pytest -m integration`."""
    import importlib
    import sys

    sys.modules.pop("api", None)
    api = importlib.import_module("api")
    from fastapi.testclient import TestClient

    with TestClient(api.app) as c:
        reponse = c.post("/chat", json={"question": "un portable pour le gaming"})
        assert reponse.status_code == 200
        assert MARQUEUR_PRODUITS in reponse.text

"""
api.py
======
API FastAPI qui expose le pipeline RAG e-commerce au frontend.

Endpoints :
    GET  /health          -> statut de l'API + accessibilité d'Ollama
    POST /chat            -> pose une question au pipeline RAG (avec historique)
    GET  /produits        -> liste complète des 30 produits (id + description)
    GET  /produits/{id}   -> un produit précis (404 si l'id n'existe pas)

Lancement :
    uvicorn api:app --reload --port 8000
    (depuis le dossier backend/, car le pipeline importe `ingestion`/`rag_pipeline`)

    ou depuis la racine :
    python backend/api.py
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from config import CORS_ORIGINS, OLLAMA_HOST, client_ollama
from ingestion import (
    MODELE_EMBEDDING,
    charger_catalogue,
    obtenir_collection,
)
from rag_pipeline import (
    MODELE_GENERATION,
    generer_reponse_stream,
    recherche_semantique,
    reformuler_question,
)

# --------------------------------------------------------------------------
# Modèles de données (validation automatique des requêtes/réponses par Pydantic)
# --------------------------------------------------------------------------
class Message(BaseModel):
    """Un tour de conversation."""
    role: str          # "user" ou "assistant"
    content: str


class ChatRequest(BaseModel):
    """Corps attendu par POST /chat."""
    question: str
    historique: list[Message] = []   # optionnel, vide par défaut


class ProduitRecommande(BaseModel):
    id: str
    raison: str


class ChatResponse(BaseModel):
    """Réponse renvoyée par POST /chat."""
    reponse_texte: str
    produits_recommandes: list[ProduitRecommande]


class Produit(BaseModel):
    id: str
    description: str


# --------------------------------------------------------------------------
# Application FastAPI + CORS
# --------------------------------------------------------------------------
app = FastAPI(
    title="Assistant e-commerce RAG",
    description="Pipeline RAG local (Ollama + Qwen3 + ChromaDB) pour conseiller des produits.",
    version="1.0.0",
)

# On autorise le frontend (React sur :3000, Vite sur :5173) à appeler l'API.
# Surchargeable via la variable d'environnement CORS_ORIGINS (voir config.py).
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------
# Chargement du catalogue + collection au démarrage (une seule fois)
# --------------------------------------------------------------------------
# On garde le catalogue en mémoire pour les endpoints /produits (lecture rapide,
# pas besoin de relire le fichier à chaque requête). On indexe aussi par id.
try:
    _CATALOGUE = charger_catalogue()
    _CATALOGUE_PAR_ID = {str(p["id"]): p for p in _CATALOGUE}
except Exception as e:  # pragma: no cover - échec au démarrage
    raise RuntimeError(f"Impossible de charger le catalogue au démarrage : {e}")

# La collection ChromaDB est ouverte une fois et réutilisée par /chat.
# ATTENTION : `ingestion.py` SUPPRIME puis recrée la collection. Si une
# ingestion a lieu pendant que l'API tourne (par exemple `docker compose up`
# qui rejoue le service ingest), le handle mis en cache pointe sur une
# collection détruite et chromadb lève NotFoundError. On le rouvre alors une
# fois, de façon transparente.
_COLLECTION = obtenir_collection()


def collection():
    """Renvoie la collection, en la rouvrant si elle a été recréée entre-temps."""
    global _COLLECTION
    try:
        _COLLECTION.count()
    except Exception:
        _COLLECTION = obtenir_collection()
    return _COLLECTION


# --------------------------------------------------------------------------
# GET /health : l'API répond-elle et Ollama est-il joignable ?
# --------------------------------------------------------------------------
@app.get("/health")
def health():
    """Vérifie rapidement que l'API tourne et qu'Ollama répond."""
    ollama_ok = True
    detail = "ok"
    try:
        client_ollama.list()  # simple ping : liste les modèles installés
    except Exception as e:
        ollama_ok = False
        detail = f"Ollama injoignable : {e}"

    return {
        "status": "ok" if ollama_ok else "degraded",
        "ollama": ollama_ok,
        "ollama_host": OLLAMA_HOST,
        "modele_generation": MODELE_GENERATION,
        "modele_embedding": MODELE_EMBEDDING,
        "produits_indexes": collection().count(),
        "detail": detail,
    }


# --------------------------------------------------------------------------
# POST /chat : cœur de l'assistant
# --------------------------------------------------------------------------
@app.post("/chat")
def chat(requete: ChatRequest):
    """
    Reçoit une question (+ historique conversationnel) et renvoie la réponse du
    pipeline RAG en STREAMING (text/plain).

    Format du flux :
      1. le texte de réponse au client, diffusé token par token ;
      2. puis un chunk final "\\n---PRODUITS---\\n" suivi du JSON des produits
         recommandés (tableau [{id, raison}]).

    Le frontend coupe le flux sur le marqueur ---PRODUITS--- pour séparer le
    texte à afficher du bloc produits. Testable via :
        curl -N --no-buffer -X POST http://localhost:8000/chat \\
             -H 'Content-Type: application/json' \\
             -d '{"question": "..."}'
    """
    if not requete.question.strip():
        raise HTTPException(status_code=400, detail="La question ne peut pas être vide.")

    # Pydantic -> liste de dicts simples attendue par le pipeline.
    historique = [{"role": m.role, "content": m.content} for m in requete.historique]

    # Étapes NON streamées (reformulation + recherche) faites AVANT d'ouvrir le
    # flux : ainsi une panne Ollama / collection vide renvoie un vrai code 503
    # plutôt qu'une erreur en plein milieu du stream.
    try:
        question_recherche = reformuler_question(requete.question, historique)
        candidats = recherche_semantique(question_recherche, collection())
    except (ConnectionError, RuntimeError) as e:
        raise HTTPException(status_code=503, detail=str(e))

    def flux():
        try:
            yield from generer_reponse_stream(
                requete.question, candidats, historique=historique
            )
        except ConnectionError as e:
            # Ollama tombe en cours de génération : on signale l'erreur dans le
            # flux (le statut HTTP 200 est déjà parti).
            yield f"\n[Erreur] {e}"

    return StreamingResponse(
        flux(),
        media_type="text/plain; charset=utf-8",
        headers={
            # Désactive la mise en tampon d'éventuels proxys (nginx) pour un vrai
            # streaming progressif côté client.
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache",
        },
    )


# --------------------------------------------------------------------------
# GET /produits : catalogue complet (pour l'affichage frontend)
# --------------------------------------------------------------------------
@app.get("/produits", response_model=list[Produit])
def liste_produits():
    """Renvoie les 30 produits (id + description)."""
    return [{"id": str(p["id"]), "description": p["description"]} for p in _CATALOGUE]


# --------------------------------------------------------------------------
# GET /produits/{id} : fiche produit
# --------------------------------------------------------------------------
@app.get("/produits/{produit_id}", response_model=Produit)
def fiche_produit(produit_id: str):
    """Renvoie un produit par son id, ou une 404 propre s'il n'existe pas."""
    produit = _CATALOGUE_PAR_ID.get(produit_id)
    if produit is None:
        raise HTTPException(
            status_code=404,
            detail=f"Aucun produit avec l'id '{produit_id}'.",
        )
    return {"id": str(produit["id"]), "description": produit["description"]}


# --------------------------------------------------------------------------
# Lancement direct : python backend/api.py
# --------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)

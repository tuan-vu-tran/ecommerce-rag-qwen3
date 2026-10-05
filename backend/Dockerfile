# ---------------------------------------------------------------------------
# Image du backend FastAPI (API + script d'ingestion).
#
# IMPORTANT : le contexte de build est la RACINE du projet (voir
# docker-compose.yml), pas backend/, afin de pouvoir copier aussi data/.
# ---------------------------------------------------------------------------
FROM python:3.11-slim

# Pas de .pyc, sortie non bufferisée (les logs d'ingestion et de streaming
# apparaissent immédiatement dans `docker compose logs`).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dépendances d'abord : cette couche est mise en cache tant que
# requirements.txt ne change pas.
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Code applicatif + catalogue (données versionnées, immuables au runtime).
COPY backend/ ./backend/
COPY data/ ./data/

# La base ChromaDB est écrite au runtime : dossier dédié, monté en volume
# nommé par docker-compose et possédé par l'utilisateur non-root.
RUN mkdir -p /app/chroma_db \
    && useradd --create-home --uid 1000 appuser \
    && chown -R appuser:appuser /app
USER appuser

ENV CATALOGUE_PATH=/app/data/catalogue.json \
    CHROMA_PATH=/app/chroma_db

# api.py importe `ingestion`, `rag_pipeline` et `config` sans préfixe de
# package : on lance donc depuis backend/, comme en local.
WORKDIR /app/backend

EXPOSE 8000
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]

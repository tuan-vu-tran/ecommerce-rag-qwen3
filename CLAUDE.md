# RAG E-commerce — Assistant conseil produit (local)

Assistant e-commerce basé sur un pipeline **RAG 100% local** : il aide un client à
choisir un produit informatique/high-tech à partir d'une description en langage naturel.
Aucun appel API externe — tout tourne via **Ollama** en `localhost:11434`.

## Stack

- **LLM génération** : `qwen3:8b` (via Ollama)
- **Embeddings** : `qwen3-embedding:0.6b` (dimension **1024**, via Ollama)
- **Vector store** : ChromaDB persistant (`chroma_db/`, collection `produits`)
- **Backend** : FastAPI + uvicorn (port 8000)
- **Frontend** : React 18 + Vite + React Router + Tailwind CSS v4 +
  react-markdown (rendu Markdown des réponses) (port 5173)
- **Env Python** : conda `rag-qwen` (Python 3.11)

## Données

`data/catalogue.json` : liste de 30 produits en **texte pur** (RAG type "PDF").
Chaque produit n'a que 2 champs : `{"id": "48213", "description": "..."}`.
**Il n'y a AUCUN champ structuré** (ni catégorie, ni prix, ni marque, ni stock) —
toutes les infos (prix, specs, usages) sont dans le texte de la `description`.
→ La recherche est donc **100% sémantique**, sans filtre de métadonnées.

## Architecture backend (`backend/`)

- **`ingestion.py`** — charge le catalogue, embed la `description` via
  `qwen3-embedding:0.6b`, stocke dans ChromaDB. Idempotent (`upsert` sur `id`).
  La collection est vidée/recréée à chaque ingestion complète.
- **`rag_pipeline.py`** — pipeline en étapes :
  0. `reformuler_question()` : si un historique existe, transforme le message
     courant elliptique ("et moins cher ?") en question autonome pour la recherche.
  1. `recherche_semantique()` : embed la question → top-5 ChromaDB (sans filtre).
  2. **Génération en STREAMING** : `generer_reponse_stream()` appelle
     `qwen3:8b` avec `stream=True` (plus de `format="json"`). C'est un générateur
     qui `yield` d'abord le TEXTE de réponse token par token, puis un chunk final
     `\n---PRODUITS---\n` suivi du JSON des produits recommandés
     (`[{"id","raison"}]`). Le bloc produits émis par le modèle est bufferisé,
     parsé et **filtré sur les id candidats** (`_parser_produits`, anti-hallucination,
     log stderr si JSON cassé → `[]`), puis ré-émis proprement → le flux ne contient
     qu'UN seul marqueur, avec un JSON garanti valide.
  - `SYSTEM_PROMPT` (message `system`) : cadre le rôle (conseil produit informatique
     UNIQUEMENT), impose une **redirection stricte mot-pour-mot** sur toute question
     hors-sujet (sans jamais répondre au sujet, même partiellement), interdit
     d'inventer des produits, exige d'être honnête si aucun candidat ne convient, et
     impose la **mise en forme Markdown** (intro courte + liste à puces `-` des specs
     clés, nom en gras, 3-5 puces/produit).
  - `generer_reponse()` (non-streaming) et `repondre(...)` **consomment** le stream
     pour reconstruire le dict structuré → le streaming est l'unique source de vérité.
     Utilisés par la CLI de debug (`python backend/rag_pipeline.py`) et les tests.
  - `repondre_stream(question, historique, collection)` : orchestrateur streaming
     utilisé par l'API (`yield from generer_reponse_stream`).
  - `backend/test_stream.py` : script de test CLI des cas clés (hors-sujet, produit
     absent, question normale).
- **`api.py`** — FastAPI. Charge le catalogue en mémoire + ouvre la collection au
  démarrage. Endpoints :
  - `GET /health` — statut API + Ollama joignable + nb produits indexés
  - `POST /chat` — `{question, historique:[{role,content}]}` → **`StreamingResponse`
    text/plain** : texte token par token, puis `\n---PRODUITS---\n` + JSON produits.
    Reformulation + recherche faites AVANT d'ouvrir le flux → vrai 503 si Ollama/
    collection KO. Testable via `curl -N --no-buffer -X POST .../chat`.
  - `GET /produits` — les 30 produits
  - `GET /produits/{id}` — un produit (404 propre si absent)
  - CORS autorisé pour `http://localhost:3000` et `http://localhost:5173`

## Architecture frontend (`frontend/src/`)

- **`api.js`** — client fetch, URL depuis `.env` (`VITE_API_URL`).
  `postChatStream(question, historique, onTexte)` lit le flux de `/chat` via
  `res.body.getReader()`, appelle `onTexte(texteCumulatif)` au fil de l'eau (en
  masquant une éventuelle amorce du marqueur `---PRODUITS---`), puis résout
  `{reponse_texte, produits_recommandes}` (JSON produits parsé, `[]` en secours).
- **`utils.js`** — `extraireNom()` reconstruit un nom lisible depuis la description
  (il n'y a pas de champ `nom`). Heuristique : après l'article de tête, garde les
  tokens marque/modèle (majuscule Unicode `\p{Lu}` ou chiffre), max 6 tokens.
- **`components/ProduitCard.jsx`** — carte réutilisable (catalogue + chat compact).
- **`components/ChatWidget.jsx`** — chat flottant présent sur toutes les pages ;
  garde l'historique en state, **stream** la réponse via `postChatStream` (affichage
  progressif token par token), affiche les recos en mini-cartes cliquables vers
  `/produit/:id`. Le texte assistant est rendu en **Markdown** (`react-markdown` +
  map `COMPOSANTS_MD` stylée Tailwind) une fois le stream terminé — pendant le
  stream on affiche le texte brut (flag `streaming` par message) pour éviter un
  Markdown cassé. Ne PAS remettre `onClick={setOuvert(false)}` sur les liens produits :
  le widget est monté hors des `<Routes>` (jamais démonté) → le chat reste ouvert et
  l'historique intact à la navigation.
- **`pages/Catalogue.jsx`** (`/`) et **`pages/FicheProduit.jsx`** (`/produit/:id`).

## Lancer le projet

**Prérequis** : Ollama lancé avec `qwen3:8b` et `qwen3-embedding:0.6b` installés.

```bash
# 0. (une fois) indexer le catalogue dans ChromaDB
conda activate rag-qwen
python backend/ingestion.py              # --check pour juste vérifier l'index

# 1. Backend (terminal 1)
cd backend && uvicorn api:app --reload --port 8000

# 2. Frontend (terminal 2)
cd frontend && npm run dev               # http://localhost:5173
```

## Conventions

- **Cohérence embeddings** : la question ET les produits doivent être encodés avec
  le MÊME modèle `qwen3-embedding:0.6b`. Ne pas changer l'un sans l'autre (sinon
  réindexer via `ingestion.py`).
- Appels Ollama via le client Python officiel `ollama` (pas de `requests` brut).
- Génération : `ollama.chat(..., stream=True, think=False)` — PAS de `format="json"`
  (incompatible avec le streaming texte). La structure produits est séparée du texte
  par le marqueur `---PRODUITS---` puis parsée/validée côté backend. Reformulation :
  `ollama.chat(..., think=False)` non streamé. Le mode "thinking" de Qwen3 est
  toujours désactivé.
- Code et commentaires en **français**.
- Après avoir modifié le format de `catalogue.json` → relancer `ingestion.py`.

## Statut

Backend (ingestion + pipeline **streaming** + API) et frontend : **fonctionnels et
testés**. Réponses en streaming token par token, rendu Markdown, system prompt strict
(refus hors-sujet, anti-invention), chat persistant à la navigation.
Étapes non faites : déploiement / mise en ligne.

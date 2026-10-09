"""
rag_pipeline.py
===============
Pipeline RAG "texte pur" pour l'assistant e-commerce.

Le catalogue ne contient plus que des descriptions libres (id + description),
comme si on indexait des PDF. Il n'y a donc PLUS de champs structurés à filtrer.
Le pipeline se simplifie en 2 étapes :

  1. RECHERCHE SÉMANTIQUE : la question du client est directement transformée
     en embedding via `qwen3-embedding:0.6b` (le MÊME modèle qu'à l'ingestion),
     puis comparée aux 30 descriptions dans ChromaDB. On récupère les 5 plus
     proches. AUCUN filtre exact (pas de where) : tout repose sur le sens.

  2. GÉNÉRATION : `qwen3:8b` reçoit la question + les 5 descriptions complètes,
     choisit les produits réellement pertinents (il peut en garder moins de 5)
     et rédige une réponse finale au format JSON structuré :
        {"reponse_texte": "...",
         "produits_recommandes": [{"id": "48213", "raison": "..."}]}
     La "raison" doit s'appuyer sur des éléments de la description
     (prix, specs, usage).

Ce fichier fournit aussi une boucle CLI interactive de debug.

Usage :
    python backend/rag_pipeline.py          # boucle interactive
"""

import json
import sys
import time

# Client Ollama partagé (URL pilotée par OLLAMA_HOST, voir config.py).
from config import OLLAMA_HOST, client_ollama
# On réutilise la config et l'accès collection de l'ingestion (cohérence :
# même dossier ChromaDB, même modèle d'embedding).
from ingestion import (
    MODELE_EMBEDDING,
    obtenir_collection,
)

MODELE_GENERATION = "qwen3:8b"

# Nombre de produits candidats remontés par la recherche sémantique.
NB_RESULTATS = 5

# Températures par défaut (valeurs historiques du projet : ne pas changer, elles
# définissent le comportement de production). Elles sont désormais des
# PARAMÈTRES de fonction, pour qu'un harnais d'évaluation puisse forcer
# temperature=0 + seed fixe sans toucher au code de production.
TEMPERATURE_REFORMULATION = 0
TEMPERATURE_GENERATION = 0.3


def _options_ollama(temperature, seed=None):
    """
    Construit le dict `options` passé à Ollama.
    `seed` n'est inclus que s'il est fourni : sans seed, le comportement est
    exactement celui d'avant (aucune option supplémentaire).
    """
    options = {"temperature": temperature}
    if seed is not None:
        options["seed"] = seed
    return options


# ==========================================================================
# Utilitaire : extraire un objet JSON d'une réponse LLM potentiellement bruitée
# ==========================================================================
def extraire_json(texte):
    """
    Tente un parse JSON direct, sinon isole le premier bloc {...}.
    Renvoie un dict, ou lève ValueError si rien d'exploitable.
    """
    texte = texte.strip()
    try:
        return json.loads(texte)
    except json.JSONDecodeError:
        pass

    debut = texte.find("{")
    fin = texte.rfind("}")
    if debut != -1 and fin != -1 and fin > debut:
        fragment = texte[debut : fin + 1]
        try:
            return json.loads(fragment)
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Sortie du modèle non parsable en JSON :\n{texte}")


# ==========================================================================
# Étape 0 : reformulation de la question en tenant compte de l'historique
# ==========================================================================
PROMPT_REFORMULATION = """Voici l'historique d'une conversation entre un client et un
assistant e-commerce, puis un nouveau message du client. Reformule ce dernier message
en UNE question autonome et complète, compréhensible sans l'historique, pour une
recherche produit.

Exemple : si le client avait parlé d'un smartphone photo puis demande "et moins cher ?",
reformule en "un smartphone avec un bon appareil photo moins cher".

Ne renvoie QUE la question reformulée, sans guillemets, sans explication.

Historique :
{historique}

Nouveau message du client : "{question}"

Question reformulée :"""


def _historique_en_texte(historique):
    """Transforme une liste [{role, content}] en texte lisible pour un prompt."""
    lignes = []
    for msg in historique:
        role = "Client" if msg.get("role") == "user" else "Assistant"
        lignes.append(f"{role} : {msg.get('content', '')}")
    return "\n".join(lignes)


def reformuler_question(
    question,
    historique,
    modele=MODELE_GENERATION,
    temperature=TEMPERATURE_REFORMULATION,
    seed=None,
):
    """
    Si un historique est présent, on demande à qwen3:8b de transformer le
    message courant (souvent elliptique, ex: "et moins cher ?") en une question
    autonome, utilisable pour la recherche sémantique. Sans historique, on
    renvoie la question telle quelle.
    """
    if not historique:
        return question

    prompt = PROMPT_REFORMULATION.format(
        historique=_historique_en_texte(historique),
        question=question,
    )
    try:
        reponse = client_ollama.chat(
            model=modele,
            messages=[{"role": "user", "content": prompt}],
            think=False,
            options=_options_ollama(temperature, seed),
        )
        reformulee = reponse["message"]["content"].strip().strip('"')
        # Filet de sécurité : si la reformulation est vide, on garde l'original.
        return reformulee or question
    except Exception:
        # En cas de souci, on ne bloque pas : on recherche avec la question brute.
        return question


# ==========================================================================
# Étape 1 : recherche sémantique pure
# ==========================================================================
def embed_question(question, modele_embedding=MODELE_EMBEDDING):
    """Encode la question avec le MÊME modèle qu'à l'ingestion (cohérence !)."""
    try:
        reponse = client_ollama.embed(model=modele_embedding, input=question)
    except Exception as e:
        raise ConnectionError(
            f"Impossible d'encoder la question via '{modele_embedding}' "
            f"({OLLAMA_HOST}).\n"
            f"Détail : {e}"
        )
    return reponse["embeddings"][0]


def recherche_semantique(
    question,
    collection=None,
    top_k=NB_RESULTATS,
    modele_embedding=MODELE_EMBEDDING,
    durees=None,
):
    """
    Transforme la question en embedding et récupère les `top_k` produits les
    plus proches sémantiquement. Aucun filtre : recherche 100% sémantique.
    Renvoie une liste de dicts {id, description, distance}.

    `durees` : dict optionnel rempli SUR PLACE avec le temps (en secondes) des
    deux sous-étapes — "embedding" et "recherche_chroma". Purement
    observationnel : passer None (défaut) ne change rien au comportement.
    """
    if collection is None:
        collection = obtenir_collection()

    if collection.count() == 0:
        raise RuntimeError(
            "La collection ChromaDB est vide. "
            "Lance d'abord : python backend/ingestion.py"
        )

    debut = time.perf_counter()
    vecteur = embed_question(question, modele_embedding=modele_embedding)
    if durees is not None:
        durees["embedding"] = time.perf_counter() - debut

    debut = time.perf_counter()
    resultats = collection.query(
        query_embeddings=[vecteur],
        n_results=top_k,
    )
    if durees is not None:
        durees["recherche_chroma"] = time.perf_counter() - debut

    produits = []
    if resultats["ids"] and resultats["ids"][0]:
        for i, pid in enumerate(resultats["ids"][0]):
            produits.append({
                "id": pid,
                "description": resultats["documents"][0][i],
                "distance": resultats["distances"][0][i],
            })
    return produits


# ==========================================================================
# Étape 2 : génération de la réponse finale (streaming texte + bloc produits)
# ==========================================================================

# Marqueur qui sépare, dans le flux, le TEXTE de réponse du BLOC JSON des
# produits recommandés. Le frontend (et curl) peuvent ainsi couper le flux en
# deux : tout ce qui précède = texte à afficher, tout ce qui suit = JSON produits.
MARQUEUR_PRODUITS = "---PRODUITS---"

# System prompt strict : cadre le rôle de l'assistant et interdit les dérives
# (hors-sujet, invention de produits). Injecté en message "system" à chaque appel.
SYSTEM_PROMPT = """Tu es un assistant commercial dont le SEUL et UNIQUE rôle est d'aider
le client à choisir un produit informatique ou high-tech PARMI le catalogue de la
boutique. Tu réponds toujours en français.

Règles absolues, à respecter sans exception :

1. RESTE STRICTEMENT DANS TON RÔLE. Tu ne réponds QU'aux questions liées au choix
   d'un produit informatique/high-tech de notre catalogue (ordinateurs portables et
   smartphones).
   Si la question n'est PAS liée à ce choix (culture générale, géographie, météo,
   cuisine, blague, ou tout autre sujet), tu NE DOIS PAS répondre à la question
   posée, même partiellement ou brièvement. Tu IGNORES complètement le sujet de la
   question (par exemple, ne donne JAMAIS le nom d'une capitale, une définition, une
   blague, etc.) et tu réponds UNIQUEMENT avec cette phrase, mot pour mot, rien
   d'autre :
   "Je suis assistant conseil technique, je peux seulement répondre aux questions concernant les produits de notre e-commerce."
   Dans ce cas, le tableau des produits recommandés est vide ([]). AUCUNE information
   sur le sujet hors-catalogue ne doit apparaître dans ta réponse.

2. N'INVENTE JAMAIS. Tu ne recommandes QUE des produits présents dans la liste de
   candidats fournie ci-dessous (issue de la recherche dans le catalogue). Tu
   n'inventes jamais un produit, un prix ou une caractéristique qui ne figure pas
   dans le contexte fourni. Utilise les id EXACTS des candidats.

3. PÉRIMÈTRE RÉEL DU CATALOGUE. Notre catalogue ne contient QUE deux catégories de
   produits : des ORDINATEURS PORTABLES et des SMARTPHONES. Rien d'autre. Tu
   n'affirmes JAMAIS que la boutique vend, propose ou dispose d'une autre catégorie
   de produit, quelle qu'elle soit. Ne dis jamais « oui, nous proposons… » pour un
   type d'article qui n'est ni un ordinateur portable ni un smartphone.

4. VÉRIFIE LA CATÉGORIE DEMANDÉE, PAS LES CRITÈRES. Cette vérification porte
   UNIQUEMENT sur la CATÉGORIE de produit demandée par le client : ordinateur
   portable, smartphone, ou une catégorie absente du catalogue. Tu ne recommandes un
   candidat que s'il appartient bien à la catégorie demandée.
   En revanche, le degré d'adéquation d'un candidat aux CRITÈRES exprimés par le
   client ne doit JAMAIS motiver un refus ni une absence de recommandation. Dès lors
   que des candidats relèvent de la catégorie demandée, tu recommandes les plus
   pertinents dont tu disposes, même si aucun ne satisfait tous les critères, et tu
   signales honnêtement les écarts.

5. SOIS HONNÊTE QUAND LE TYPE DEMANDÉ EST ABSENT. Si le client demande un type
   d'article qui ne figure pas dans les candidats fournis, tu dois :
   - dire clairement et poliment que ce type de produit n'est PAS au catalogue ;
   - ne recommander AUCUN produit (tableau JSON vide : []) ;
   - proposer ton aide pour choisir un ordinateur portable ou un smartphone.
   Cela s'applique à TOUT type d'article hors de ces deux catégories, même s'il est
   proche de l'informatique ou du high-tech.

6. PAS D'ASSOCIATION AVEC L'ABSENT. Tu ne suggères JAMAIS qu'un produit du catalogue
   « peut s'associer à », « est compatible avec », « fonctionne avec » ou « se
   complète avec » un article qui n'est pas au catalogue. Ne mentionne pas d'articles
   que nous ne vendons pas comme s'ils faisaient partie de notre offre.

7. JUSTIFIE. Quand tu recommandes un produit, appuie chaque raison sur des éléments
   CONCRETS de sa description (prix, caractéristiques techniques, usage).

MISE EN FORME DU TEXTE (quand tu présentes un ou plusieurs produits) :
Structure toujours ta réponse ainsi, en Markdown :
- Une courte phrase d'intro expliquant pourquoi ce produit correspond à la demande.
- Puis une liste à puces (tirets Markdown « - ») mettant en avant les
  caractéristiques clés PERTINENTES pour la demande (specs techniques, prix,
  points forts), avec le nom de la caractéristique EN GRAS suivi de sa valeur.
  Exemple : « - **Processeur** : AMD Ryzen 9 7945HX ».
- Reste concis : 3 à 5 puces MAXIMUM par produit, uniquement les infos utiles à la
  décision par rapport à la question posée (inutile de lister toutes les specs).
- S'il y a plusieurs produits, introduis chacun par son nom en gras, puis sa liste.
(Pour un refus hors-sujet ou l'absence de produit, une ou deux phrases suffisent :
pas de liste à puces dans ce cas.)

FORMAT DE RÉPONSE OBLIGATOIRE (respecte-le exactement) :
- D'abord, ta réponse au client, en français, naturelle et utile.
- Puis, sur une nouvelle ligne, le marqueur EXACT : ---PRODUITS---
- Puis un tableau JSON des produits recommandés, de la forme :
  [{"id": "IDENTIFIANT", "raison": "pourquoi ce produit convient"}]
  Si tu ne recommandes aucun produit (hors sujet ou aucun candidat pertinent),
  mets un tableau vide : []
- N'écris ABSOLUMENT RIEN après le tableau JSON."""


PROMPT_GENERATION = """Question du client : "{question}"

Produits candidats (résultats de la recherche sémantique dans le catalogue) :
{contexte}

Rappel du format attendu : d'abord ta réponse au client, puis une ligne contenant
exactement ---PRODUITS---, puis le tableau JSON des produits recommandés (ou [])."""


def _contexte_produits(produits):
    """Met en forme les descriptions complètes des candidats pour le prompt."""
    if not produits:
        return "(aucun produit candidat)"
    blocs = []
    for p in produits:
        blocs.append(f"--- Produit id={p['id']} ---\n{p['description']}")
    return "\n\n".join(blocs)


def _parser_produits(texte_apres_marqueur, ids_valides):
    """
    Extrait le tableau JSON des produits recommandés du texte situé APRÈS le
    marqueur. On isole le premier `[...]`, on parse, puis on ne garde que les
    entrées dont l'id fait bien partie des candidats (filet anti-hallucination).
    Renvoie une liste [{id, raison}] (éventuellement vide).
    """
    debut = texte_apres_marqueur.find("[")
    fin = texte_apres_marqueur.rfind("]")
    if debut == -1 or fin == -1 or fin < debut:
        print(f"[rag_pipeline] Bloc produits sans tableau JSON exploitable : "
              f"{texte_apres_marqueur!r}", file=sys.stderr)
        return []
    try:
        liste = json.loads(texte_apres_marqueur[debut : fin + 1])
    except json.JSONDecodeError as e:
        print(f"[rag_pipeline] JSON produits invalide ({e}) : "
              f"{texte_apres_marqueur[debut : fin + 1]!r}", file=sys.stderr)
        return []
    if not isinstance(liste, list):
        print(f"[rag_pipeline] Bloc produits n'est pas une liste : {liste!r}",
              file=sys.stderr)
        return []

    produits = []
    for item in liste:
        if not isinstance(item, dict):
            continue
        pid = str(item.get("id", "")).strip()
        if pid and pid in ids_valides:
            produits.append({"id": pid, "raison": item.get("raison", "")})
    return produits


def generer_reponse_stream(
    question,
    produits,
    historique=None,
    modele=MODELE_GENERATION,
    temperature=TEMPERATURE_GENERATION,
    seed=None,
):
    """
    Version STREAMING de la génération. C'est un générateur qui `yield` des
    fragments de texte au fil de l'eau :

      1. d'abord le TEXTE de réponse au client, token par token (tel que produit
         par qwen3:8b) ;
      2. puis un chunk final unique : "\\n---PRODUITS---\\n" suivi du JSON des
         produits recommandés (déjà validés/nettoyés).

    Le modèle est invité (system prompt + rappel) à produire lui-même son texte,
    la ligne ---PRODUITS--- puis le tableau JSON. Côté backend, on ne diffuse au
    client que le texte AVANT le marqueur ; le bloc produits du modèle est bufferisé,
    parsé, filtré, puis ré-émis proprement à la fin. Le flux ne contient donc
    qu'UN seul marqueur (le nôtre), avec un JSON garanti valide.

    Si un historique est fourni, il est injecté entre le system prompt et le
    message courant pour tenir compte du contexte conversationnel.
    """
    prompt = PROMPT_GENERATION.format(
        question=question,
        contexte=_contexte_produits(produits),
    )
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if historique:
        messages.extend(historique)
    messages.append({"role": "user", "content": prompt})

    ids_valides = {p["id"] for p in produits}

    try:
        flux = client_ollama.chat(
            model=modele,
            messages=messages,
            think=False,     # désactive le mode raisonnement de Qwen3
            options=_options_ollama(temperature, seed),
            stream=True,     # <-- streaming token par token
        )
    except Exception as e:
        raise ConnectionError(
            f"Ollama injoignable pour la génération ({OLLAMA_HOST}).\nDétail : {e}"
        )

    buffer = ""            # tout le texte reçu du modèle
    deja_emis = 0          # longueur du texte déjà diffusé au client
    marqueur_vu = False    # a-t-on rencontré ---PRODUITS--- ?
    # Nombre de caractères de queue qu'on retient tant qu'on n'a pas vu le
    # marqueur, pour ne pas diffuser un marqueur coupé en deux entre 2 tokens.
    garde = len(MARQUEUR_PRODUITS) - 1

    for morceau in flux:
        token = morceau["message"]["content"]
        if not token:
            continue
        buffer += token
        if marqueur_vu:
            # On a déjà passé le marqueur : on ne diffuse plus, on bufferise le
            # bloc produits pour le parser à la fin.
            continue

        idx = buffer.find(MARQUEUR_PRODUITS)
        if idx != -1:
            # Marqueur trouvé : on diffuse le texte restant AVANT le marqueur.
            marqueur_vu = True
            if idx > deja_emis:
                yield buffer[deja_emis:idx]
            deja_emis = idx
        else:
            # Pas encore de marqueur : on diffuse tout sauf une petite queue
            # (qui pourrait être le début d'un marqueur).
            fin_sure = len(buffer) - garde
            if fin_sure > deja_emis:
                yield buffer[deja_emis:fin_sure]
                deja_emis = fin_sure

    # ---- Fin du flux du modèle ----
    if marqueur_vu:
        apres = buffer[buffer.find(MARQUEUR_PRODUITS) + len(MARQUEUR_PRODUITS):]
        produits_reco = _parser_produits(apres, ids_valides)
    else:
        # Le modèle n'a pas émis de marqueur : on diffuse le texte restant et on
        # considère qu'aucun produit n'est recommandé.
        if len(buffer) > deja_emis:
            yield buffer[deja_emis:]
        produits_reco = []

    # Chunk final : marqueur propre + JSON des produits recommandés.
    yield "\n" + MARQUEUR_PRODUITS + "\n"
    yield json.dumps(produits_reco, ensure_ascii=False)


def generer_reponse(
    question,
    produits,
    historique=None,
    modele=MODELE_GENERATION,
    temperature=TEMPERATURE_GENERATION,
    seed=None,
):
    """
    Version NON-streaming (pour la CLI de debug et les tests). Elle consomme
    entièrement `generer_reponse_stream` puis reconstruit le dict structuré
    {"reponse_texte", "produits_recommandes"} en coupant sur le marqueur.
    Ainsi le streaming reste l'unique source de vérité de la génération.
    """
    texte = "".join(generer_reponse_stream(
        question,
        produits,
        historique=historique,
        modele=modele,
        temperature=temperature,
        seed=seed,
    ))
    avant, sep, apres = texte.partition(MARQUEUR_PRODUITS)
    reponse_texte = avant.strip()

    produits_reco = []
    if sep:
        try:
            produits_reco = json.loads(apres.strip())
        except json.JSONDecodeError:
            produits_reco = []

    if not reponse_texte and not produits_reco:
        # Filet de sécurité : le modèle n'a rien produit d'exploitable.
        reponse_texte = ("Désolé, je n'ai pas pu formuler de recommandation. "
                         "Peux-tu reformuler ta demande ?")

    return {
        "reponse_texte": reponse_texte,
        "produits_recommandes": produits_reco,
    }


# ==========================================================================
# Orchestration complète (utilisée par la CLI ET, plus tard, par l'API)
# ==========================================================================
def preparer_recherche(
    question,
    historique=None,
    collection=None,
    top_k=NB_RESULTATS,
    modele_generation=MODELE_GENERATION,
    modele_embedding=MODELE_EMBEDDING,
    temperature_reformulation=TEMPERATURE_REFORMULATION,
    seed=None,
    durees=None,
):
    """
    Étapes 0 et 1 du pipeline (NON streamées) : reformulation puis recherche
    sémantique. Renvoie (question_recherche, candidats).

    Factorisé ici parce que TROIS appelants ont besoin exactement de ces deux
    étapes, dans cet ordre, avant la génération :
      - `repondre()` / `repondre_stream()` (CLI + API)
      - `api.py::chat()` qui les exécute AVANT d'ouvrir le flux pour pouvoir
        renvoyer un vrai 503 (les exceptions ConnectionError / RuntimeError
        remontent donc telles quelles, comme avant)
      - `evaluer_question()` (harnais d'évaluation)
    Aucun appelant ne réimplémente le pipeline.

    `durees` : dict optionnel rempli sur place ("reformulation", "embedding",
    "recherche_chroma"). Sans lui, comportement identique à l'historique.
    """
    if collection is None:
        collection = obtenir_collection()

    # 0. Reformulation en question autonome si un historique est présent
    debut = time.perf_counter()
    question_recherche = reformuler_question(
        question,
        historique,
        modele=modele_generation,
        temperature=temperature_reformulation,
        seed=seed,
    )
    if durees is not None:
        durees["reformulation"] = time.perf_counter() - debut

    # 1. Recherche sémantique pure (sur la question reformulée)
    candidats = recherche_semantique(
        question_recherche,
        collection,
        top_k=top_k,
        modele_embedding=modele_embedding,
        durees=durees,
    )
    return question_recherche, candidats


def repondre(
    question,
    historique=None,
    collection=None,
    debug=False,
    top_k=NB_RESULTATS,
    modele_generation=MODELE_GENERATION,
    modele_embedding=MODELE_EMBEDDING,
    temperature=TEMPERATURE_GENERATION,
    seed=None,
):
    """
    Exécute le pipeline complet et renvoie un dict :
      {
        "question_recherche": "...",  # question reformulée utilisée pour la recherche
        "candidats": [...],           # top_k produits les plus proches (debug)
        "reponse": {"reponse_texte": ..., "produits_recommandes": [...]}
      }
    `historique` : liste optionnelle de messages [{role, content}] de la conversation.
    Si debug=True, affiche les étapes intermédiaires.
    """
    question_recherche, candidats = preparer_recherche(
        question,
        historique=historique,
        collection=collection,
        top_k=top_k,
        modele_generation=modele_generation,
        modele_embedding=modele_embedding,
        seed=seed,
    )
    if debug and question_recherche != question:
        print(f"\n[0] Question reformulée pour la recherche : \"{question_recherche}\"")

    if debug:
        print(f"\n[1] Recherche sémantique — {len(candidats)} candidat(s) :")
        for c in candidats:
            extrait = c["description"][:100].replace("\n", " ")
            print(f"    · id={c['id']:<7} distance={c['distance']:.4f}  {extrait}...")

    # 2. Génération de la réponse finale (avec l'historique conversationnel)
    reponse = generer_reponse(
        question,
        candidats,
        historique=historique,
        modele=modele_generation,
        temperature=temperature,
        seed=seed,
    )
    if debug:
        print("\n[2] Réponse finale structurée :")
        print(json.dumps(reponse, ensure_ascii=False, indent=2))

    return {
        "question_recherche": question_recherche,
        "candidats": candidats,
        "reponse": reponse,
    }


def repondre_stream(
    question,
    historique=None,
    collection=None,
    top_k=NB_RESULTATS,
    modele_generation=MODELE_GENERATION,
    modele_embedding=MODELE_EMBEDDING,
    temperature=TEMPERATURE_GENERATION,
    seed=None,
):
    """
    Version STREAMING de `repondre`, utilisée par l'endpoint /chat.

    Fait la reformulation puis la recherche sémantique (étapes non streamées),
    PUIS délègue à `generer_reponse_stream` qui diffuse le texte token par token
    suivi du bloc "---PRODUITS---" + JSON.

    C'est un générateur : les erreurs de reformulation/recherche (Ollama down,
    collection vide) sont levées dès le premier `next()`. Pour renvoyer un code
    HTTP propre, l'API fait la recherche AVANT d'ouvrir le flux (voir api.py).
    """
    _, candidats = preparer_recherche(
        question,
        historique=historique,
        collection=collection,
        top_k=top_k,
        modele_generation=modele_generation,
        modele_embedding=modele_embedding,
        seed=seed,
    )
    yield from generer_reponse_stream(
        question,
        candidats,
        historique=historique,
        modele=modele_generation,
        temperature=temperature,
        seed=seed,
    )


# ==========================================================================
# Point d'observation pour l'évaluation (eval/run_eval.py)
# ==========================================================================
def evaluer_question(
    question,
    historique=None,
    collection=None,
    top_k=NB_RESULTATS,
    modele_generation=MODELE_GENERATION,
    modele_embedding=MODELE_EMBEDDING,
    temperature=TEMPERATURE_GENERATION,
    seed=None,
):
    """
    Exécute le pipeline COMPLET sur une question et renvoie une trace détaillée,
    pour un harnais d'évaluation hors-ligne.

    Ce n'est PAS un second pipeline : la fonction appelle exactement les mêmes
    briques que la production (`preparer_recherche` puis `generer_reponse`, qui
    consomme lui-même `generer_reponse_stream`). Le streaming reste l'unique
    source de vérité de la génération ; on ne fait qu'instrumenter le temps et
    conserver les états intermédiaires.

    Paramètres (aucune valeur codée en dur : les défauts reproduisent la prod) :
        top_k               nombre de candidats remontés de ChromaDB
        modele_generation   modèle Ollama de génération / reformulation
        modele_embedding    modèle Ollama d'embedding (doit être celui de
                            l'ingestion, sinon la recherche n'a aucun sens)
        temperature         température de génération (0 pour une évaluation
                            reproductible ; 0.3 en production)
        seed                seed Ollama (None = pas d'option seed, comme en prod)

    Renvoie :
      {
        "question": "...",                 # question d'origine
        "question_reformulee": "...",       # question réellement envoyée à la recherche
        "reformulation_appliquee": bool,    # True si elle diffère de l'originale
        "candidats": [{"id", "distance", "rang"}],   # dans l'ordre ChromaDB
        "reponse_texte": "...",
        "produits_recommandes": [{"id", "raison"}],
        "ids_recommandes": ["..."],
        "durees": {"reformulation", "embedding", "recherche_chroma",
                   "generation", "total"},             # en secondes
        "parametres": {...},                            # config effective du run
      }
    """
    durees = {"reformulation": 0.0, "embedding": 0.0, "recherche_chroma": 0.0}
    debut_total = time.perf_counter()

    # Étapes 0 + 1 : mêmes appels que l'API, avec chronométrage.
    question_recherche, candidats = preparer_recherche(
        question,
        historique=historique,
        collection=collection,
        top_k=top_k,
        modele_generation=modele_generation,
        modele_embedding=modele_embedding,
        seed=seed,
        durees=durees,
    )

    # Étape 2 : génération. `generer_reponse` consomme le flux en interne et
    # reconstruit {reponse_texte, produits_recommandes} en coupant sur le
    # marqueur ---PRODUITS--- : on obtient la réponse complète sans dupliquer
    # la logique de parsing.
    debut = time.perf_counter()
    reponse = generer_reponse(
        question,
        candidats,
        historique=historique,
        modele=modele_generation,
        temperature=temperature,
        seed=seed,
    )
    durees["generation"] = time.perf_counter() - debut
    durees["total"] = time.perf_counter() - debut_total

    produits_reco = reponse["produits_recommandes"]

    return {
        "question": question,
        "question_reformulee": question_recherche,
        "reformulation_appliquee": question_recherche != question,
        # On ne garde pas la description complète (volumineuse) : id + distance
        # + rang suffisent pour diagnostiquer la recherche.
        "candidats": [
            {"id": c["id"], "distance": c["distance"], "rang": i + 1}
            for i, c in enumerate(candidats)
        ],
        "reponse_texte": reponse["reponse_texte"],
        "produits_recommandes": produits_reco,
        "ids_recommandes": [str(p.get("id", "")) for p in produits_reco],
        "durees": durees,
        "parametres": {
            "top_k": top_k,
            "modele_generation": modele_generation,
            "modele_embedding": modele_embedding,
            "temperature": temperature,
            "seed": seed,
        },
    }


# ==========================================================================
# Point d'entrée CLI : boucle interactive de debug
# ==========================================================================
def boucle_cli():
    print("=" * 70)
    print("  Assistant e-commerce RAG (local, texte pur) — mode debug")
    print("  Pose une question ('quit' ou Ctrl-C pour sortir).")
    print("=" * 70)

    try:
        collection = obtenir_collection()
        if collection.count() == 0:
            print("\n❌ Collection vide. Lance d'abord : python backend/ingestion.py")
            sys.exit(1)
    except Exception as e:
        print(f"\n❌ Impossible d'ouvrir ChromaDB : {e}")
        sys.exit(1)

    while True:
        try:
            question = input("\n💬 Question > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nÀ bientôt !")
            break

        if not question:
            continue
        if question.lower() in {"quit", "exit", "q"}:
            print("À bientôt !")
            break

        try:
            repondre(question, collection=collection, debug=True)
        except (ConnectionError, RuntimeError, ValueError) as e:
            print(f"\n❌ Erreur : {e}")


if __name__ == "__main__":
    boucle_cli()

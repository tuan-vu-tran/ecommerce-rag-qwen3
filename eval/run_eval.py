#!/usr/bin/env python3
"""
run_eval.py
===========
Harnais d'évaluation hors-ligne du pipeline RAG e-commerce.

Il N'IMPLÉMENTE PAS de pipeline : il appelle `rag_pipeline.evaluer_question()`,
qui enchaîne exactement les mêmes briques que la route `/chat` de production
(`preparer_recherche` puis `generer_reponse`, qui consomme le flux en interne).

Métriques calculées, globalement ET par type ET par split :
  a. hit@top_k          la recherche a-t-elle ramené au moins un bon produit ?
  b. precision_finale   l'assistant recommande-t-il au moins un attendu, sans
                        aucun interdit ?
  c. erreur_grave       un produit interdit a-t-il été recommandé ?
  d. refus_correct      pour must_refuse=true, la liste produits est-elle vide ?
  e. hallucinations     nombre d'ids recommandés absents du catalogue
  f. latence            médiane / moyenne / p95 du total + médiane par étape

Le split `test` est protégé : il exige `--confirm-test`.

Usage :
    python eval/run_eval.py --split dev --label baseline --runs 3
    python eval/run_eval.py --split test --label final --confirm-test
"""

import argparse
import json
import statistics
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
# Le backend importe ses voisins à plat (`from config import ...`, `from
# ingestion import ...`) : on ajoute donc backend/ au sys.path, comme le fait
# uvicorn lancé depuis ce dossier.
sys.path.insert(0, str(RACINE / "backend"))

from config import OLLAMA_HOST                                    # noqa: E402
from ingestion import MODELE_EMBEDDING, obtenir_collection        # noqa: E402
from rag_pipeline import (                                        # noqa: E402
    MODELE_GENERATION,
    NB_RESULTATS,
    evaluer_question,
)

CHEMIN_DATASET = RACINE / "eval" / "dataset.json"
CHEMIN_CATALOGUE = RACINE / "data" / "catalogue.json"
DOSSIER_RESULTATS = RACINE / "eval" / "results"

# Température forcée à 0 pour l'évaluation : on veut mesurer le pipeline, pas
# l'aléa d'échantillonnage (la production tourne à 0.3).
TEMPERATURE_EVAL = 0
# Seed fixe : avec temperature=0 elle ne change presque rien, mais elle rend le
# run reproductible si la température est remontée.
SEED_EVAL = 42

ORDRE_TYPES = [
    "precise", "vague", "situational", "followup",
    "out_of_scope", "not_in_catalogue", "injection",
]

# Raisons d'échec (une question peut en cumuler plusieurs).
RAISON_AUCUN_ATTENDU = "aucun attendu trouvé"
RAISON_FORBIDDEN = "forbidden recommandé"
RAISON_REFUS_MANQUE = "refus manqué"
RAISON_HALLUCINATION = "hallucination"


# ==========================================================================
# Évaluation d'une seule question
# ==========================================================================
def evaluer_cas(cas, collection, ids_catalogue, top_k, gen_model, embed_model):
    """
    Lance le pipeline sur un cas du dataset et renvoie la trace + les
    indicateurs booléens qui serviront à agréger les métriques.
    """
    attendus = set(cas["expected_ids"])
    interdits = set(cas["forbidden_ids"])
    must_refuse = bool(cas["must_refuse"])

    erreur = None
    try:
        trace = evaluer_question(
            cas["question"],
            historique=cas["historique"],
            collection=collection,
            top_k=top_k,
            modele_generation=gen_model,
            modele_embedding=embed_model,
            temperature=TEMPERATURE_EVAL,
            seed=SEED_EVAL,
        )
    except Exception as exc:  # Ollama tombe, collection vide, etc.
        erreur = f"{type(exc).__name__}: {exc}"
        trace = {
            "question": cas["question"],
            "question_reformulee": cas["question"],
            "reformulation_appliquee": False,
            "candidats": [],
            "reponse_texte": "",
            "produits_recommandes": [],
            "ids_recommandes": [],
            "durees": {"reformulation": 0.0, "embedding": 0.0,
                       "recherche_chroma": 0.0, "generation": 0.0, "total": 0.0},
        }

    ids_candidats = [c["id"] for c in trace["candidats"]]
    ids_reco = trace["ids_recommandes"]

    # --- a. hit@top_k : la RECHERCHE a-t-elle fait son travail ?
    #        (uniquement pertinent quand on attend quelque chose)
    evaluable_attendu = bool(attendus)
    hit = bool(attendus & set(ids_candidats)) if evaluable_attendu else None

    # --- b. précision finale : au moins un attendu recommandé, aucun interdit
    if evaluable_attendu:
        precision = bool(set(ids_reco) & attendus) and not (set(ids_reco) & interdits)
    else:
        precision = None

    # --- c. erreur grave : un interdit a été recommandé (sur TOUTES les questions)
    interdits_recommandes = sorted(set(ids_reco) & interdits)
    erreur_grave = bool(interdits_recommandes)

    # --- d. refus correct : must_refuse => aucun produit recommandé
    refus_correct = (len(ids_reco) == 0) if must_refuse else None

    # --- e. hallucinations : ids hors catalogue
    #        (_parser_produits filtre déjà sur les candidats : cette métrique
    #        vérifie que ce filet tient, elle doit rester à 0)
    hallucines = sorted(set(ids_reco) - ids_catalogue)

    # --- raisons d'échec, pour le rapport
    raisons = []
    if evaluable_attendu and not (set(ids_reco) & attendus):
        raisons.append(RAISON_AUCUN_ATTENDU)
    if erreur_grave:
        raisons.append(RAISON_FORBIDDEN)
    if must_refuse and ids_reco:
        raisons.append(RAISON_REFUS_MANQUE)
    if hallucines:
        raisons.append(RAISON_HALLUCINATION)

    return {
        "id": cas["id"],
        "type": cas["type"],
        "split": cas["split"],
        "question": cas["question"],
        "historique": cas["historique"],
        "expected_ids": cas["expected_ids"],
        "forbidden_ids": cas["forbidden_ids"],
        "must_refuse": must_refuse,
        # trace pipeline
        "question_reformulee": trace["question_reformulee"],
        "reformulation_appliquee": trace["reformulation_appliquee"],
        "candidats": trace["candidats"],
        "ids_candidats": ids_candidats,
        "reponse_texte": trace["reponse_texte"],
        "produits_recommandes": trace["produits_recommandes"],
        "ids_recommandes": ids_reco,
        "durees": trace["durees"],
        # indicateurs
        "hit": hit,
        "precision": precision,
        "erreur_grave": erreur_grave,
        "interdits_recommandes": interdits_recommandes,
        "refus_correct": refus_correct,
        "ids_hallucines": hallucines,
        "raisons_echec": raisons,
        "echec": bool(raisons),
        "erreur_pipeline": erreur,
    }


# ==========================================================================
# Agrégation des métriques
# ==========================================================================
def _taux(numerateur, denominateur):
    """Renvoie None quand la métrique n'a aucun cas évaluable (et non 0.0)."""
    if denominateur == 0:
        return None
    return numerateur / denominateur


def _percentile(valeurs, p):
    """p-ème centile par interpolation linéaire (évite une dépendance numpy)."""
    if not valeurs:
        return None
    tri = sorted(valeurs)
    if len(tri) == 1:
        return tri[0]
    position = (len(tri) - 1) * p
    bas = int(position)
    haut = min(bas + 1, len(tri) - 1)
    return tri[bas] + (tri[haut] - tri[bas]) * (position - bas)


def agreger(resultats):
    """Calcule le bloc de métriques pour une liste de résultats de cas."""
    avec_attendus = [r for r in resultats if r["hit"] is not None]
    a_refuser = [r for r in resultats if r["refus_correct"] is not None]
    totaux = [r["durees"]["total"] for r in resultats if r["durees"]["total"] > 0]

    def mediane_etape(nom):
        valeurs = [r["durees"].get(nom, 0.0) for r in resultats
                   if r["durees"].get("total", 0.0) > 0]
        return statistics.median(valeurs) if valeurs else None

    return {
        "n_questions": len(resultats),
        "n_avec_attendus": len(avec_attendus),
        "n_must_refuse": len(a_refuser),

        "hit_at_k": _taux(sum(1 for r in avec_attendus if r["hit"]), len(avec_attendus)),
        "precision_finale": _taux(
            sum(1 for r in avec_attendus if r["precision"]), len(avec_attendus)
        ),
        "taux_erreur_grave": _taux(
            sum(1 for r in resultats if r["erreur_grave"]), len(resultats)
        ),
        "refus_correct": _taux(
            sum(1 for r in a_refuser if r["refus_correct"]), len(a_refuser)
        ),
        "hallucinations": sum(len(r["ids_hallucines"]) for r in resultats),
        "n_echecs": sum(1 for r in resultats if r["echec"]),
        "n_erreurs_pipeline": sum(1 for r in resultats if r["erreur_pipeline"]),

        "latence": {
            "mediane_total": statistics.median(totaux) if totaux else None,
            "moyenne_total": statistics.fmean(totaux) if totaux else None,
            "p95_total": _percentile(totaux, 0.95),
            "mediane_reformulation": mediane_etape("reformulation"),
            "mediane_embedding": mediane_etape("embedding"),
            "mediane_recherche_chroma": mediane_etape("recherche_chroma"),
            "mediane_generation": mediane_etape("generation"),
        },
    }


def agreger_par(resultats, champ, ordre=None):
    """Agrège par valeur d'un champ (`type` ou `split`)."""
    groupes = defaultdict(list)
    for r in resultats:
        groupes[r[champ]].append(r)
    cles = [c for c in (ordre or []) if c in groupes]
    cles += sorted(c for c in groupes if c not in cles)
    return {cle: agreger(groupes[cle]) for cle in cles}


def resumer_runs(metriques_par_run):
    """
    Avec --runs N > 1 : moyenne et variabilité (écart-type + min/max) de chaque
    métrique scalaire à travers les N runs.
    """
    cles_scalaires = ["hit_at_k", "precision_finale", "taux_erreur_grave",
                      "refus_correct", "hallucinations", "n_echecs"]
    cles_latence = ["mediane_total", "moyenne_total", "p95_total",
                    "mediane_reformulation", "mediane_embedding",
                    "mediane_recherche_chroma", "mediane_generation"]

    resume = {}
    for cle in cles_scalaires:
        valeurs = [m[cle] for m in metriques_par_run if m.get(cle) is not None]
        resume[cle] = _stats_serie(valeurs)
    resume["latence"] = {}
    for cle in cles_latence:
        valeurs = [m["latence"][cle] for m in metriques_par_run
                   if m["latence"].get(cle) is not None]
        resume["latence"][cle] = _stats_serie(valeurs)
    resume["n_runs"] = len(metriques_par_run)
    resume["n_questions"] = metriques_par_run[0]["n_questions"] if metriques_par_run else 0
    resume["n_avec_attendus"] = (
        metriques_par_run[0]["n_avec_attendus"] if metriques_par_run else 0
    )
    resume["n_must_refuse"] = (
        metriques_par_run[0]["n_must_refuse"] if metriques_par_run else 0
    )
    return resume


def _stats_serie(valeurs):
    if not valeurs:
        return None
    return {
        "moyenne": statistics.fmean(valeurs),
        "ecart_type": statistics.stdev(valeurs) if len(valeurs) > 1 else 0.0,
        "min": min(valeurs),
        "max": max(valeurs),
        "valeurs": valeurs,
    }


# ==========================================================================
# Affichage terminal
# ==========================================================================
def _pct(valeur):
    return "   n/a" if valeur is None else f"{valeur * 100:5.1f}%"


def _sec(valeur):
    return "    n/a" if valeur is None else f"{valeur:6.2f}s"


def _moy_ecart(stat, formateur, suffixe_ecart):
    """Formate « moyenne ±écart-type » (ou juste la valeur si un seul run)."""
    if stat is None:
        return "n/a"
    if stat["ecart_type"] == 0.0 and len(stat["valeurs"]) <= 1:
        return formateur(stat["moyenne"])
    return f"{formateur(stat['moyenne'])} ±{suffixe_ecart(stat['ecart_type'])}"


def afficher(resume_global, resume_types, resume_splits, nb_runs, config):
    print()
    print("=" * 98)
    print("EVALUATION DU PIPELINE RAG E-COMMERCE")
    print("=" * 98)
    for cle, valeur in config.items():
        print(f"  {cle:<22} {valeur}")
    print("=" * 98)
    print()

    suffixe = " (moyenne sur {} runs ±ecart-type)".format(nb_runs) if nb_runs > 1 else ""
    print(f"METRIQUES GLOBALES{suffixe}")
    print("-" * 98)
    lignes = [
        ("hit@top_k", "hit_at_k", _pct, lambda e: f"{e * 100:.1f}pt",
         f"{resume_global['n_avec_attendus']} questions avec attendus"),
        ("precision finale", "precision_finale", _pct, lambda e: f"{e * 100:.1f}pt",
         "au moins 1 attendu, 0 interdit"),
        ("taux d'erreur grave", "taux_erreur_grave", _pct, lambda e: f"{e * 100:.1f}pt",
         f"sur les {resume_global['n_questions']} questions"),
        ("refus correct", "refus_correct", _pct, lambda e: f"{e * 100:.1f}pt",
         f"{resume_global['n_must_refuse']} questions must_refuse"),
        ("hallucinations", "hallucinations", lambda v: f"{v:6.2f}", lambda e: f"{e:.2f}",
         "ids recommandes hors catalogue"),
        ("echecs", "n_echecs", lambda v: f"{v:6.2f}", lambda e: f"{e:.2f}",
         "questions avec >=1 raison d'echec"),
    ]
    for libelle, cle, fmt, fmt_ecart, note in lignes:
        valeur = _moy_ecart(resume_global.get(cle), fmt, fmt_ecart)
        print(f"  {libelle:<22} {valeur:<22} {note}")
    print()

    print("LATENCE")
    print("-" * 98)
    lat = resume_global["latence"]
    for libelle, cle in [
        ("total mediane", "mediane_total"),
        ("total moyenne", "moyenne_total"),
        ("total p95", "p95_total"),
        ("  . reformulation", "mediane_reformulation"),
        ("  . embedding", "mediane_embedding"),
        ("  . recherche chroma", "mediane_recherche_chroma"),
        ("  . generation", "mediane_generation"),
    ]:
        print(f"  {libelle:<22} {_moy_ecart(lat.get(cle), _sec, lambda e: f'{e:.2f}s')}")
    print()

    for titre, resume in (("PAR TYPE", resume_types), ("PAR SPLIT", resume_splits)):
        print(titre)
        print("-" * 98)
        print(f"  {'groupe':<17} {'n':>3} {'hit@k':>7} {'precis.':>8} "
              f"{'err.grave':>10} {'refus':>7} {'halluc':>7} {'echecs':>7} {'lat.med':>9}")
        print("  " + "-" * 94)
        for cle, m in resume.items():
            print(f"  {cle:<17} {m['n_questions']:>3} "
                  f"{_pct(_m(m, 'hit_at_k')):>7} "
                  f"{_pct(_m(m, 'precision_finale')):>8} "
                  f"{_pct(_m(m, 'taux_erreur_grave')):>10} "
                  f"{_pct(_m(m, 'refus_correct')):>7} "
                  f"{_fmt_nombre(_m(m, 'hallucinations')):>7} "
                  f"{_fmt_nombre(_m(m, 'n_echecs')):>7} "
                  f"{_sec(_m(m['latence'], 'mediane_total')):>9}")
        print()


def _m(resume, cle):
    """Lit une métrique d'un résumé multi-runs (dict {moyenne,...}) ou brute."""
    valeur = resume.get(cle)
    if isinstance(valeur, dict):
        return valeur.get("moyenne")
    return valeur


def _fmt_nombre(valeur):
    return "n/a" if valeur is None else f"{valeur:.2f}".rstrip("0").rstrip(".")


def afficher_echecs(resultats_dernier_run):
    echecs = [r for r in resultats_dernier_run if r["echec"]]
    print(f"ECHECS DU DERNIER RUN ({len(echecs)}/{len(resultats_dernier_run)})")
    print("-" * 98)
    if not echecs:
        print("  aucun")
        print()
        return
    for r in echecs:
        print(f"  {r['id']} [{r['type']}/{r['split']}] — {', '.join(r['raisons_echec'])}")
        print(f"      question   : {r['question'][:84]}")
        if r["reformulation_appliquee"]:
            print(f"      reformulee : {r['question_reformulee'][:84]}")
        print(f"      candidats  : {r['ids_candidats']}")
        print(f"      attendus   : {r['expected_ids']}")
        print(f"      recommandes: {r['ids_recommandes']}")
        if r["interdits_recommandes"]:
            print(f"      INTERDITS  : {r['interdits_recommandes']}")
        if r["ids_hallucines"]:
            print(f"      HALLUCINES : {r['ids_hallucines']}")
        if r["erreur_pipeline"]:
            print(f"      ERREUR     : {r['erreur_pipeline']}")
    print()


# ==========================================================================
# Rapport Markdown
# ==========================================================================
def _md_metrique(stat, formateur, nb_runs):
    if stat is None:
        return "n/a"
    if nb_runs <= 1:
        return formateur(stat["moyenne"]).strip()
    return (f"{formateur(stat['moyenne']).strip()} "
            f"(±{formateur(stat['ecart_type']).strip()}, "
            f"min {formateur(stat['min']).strip()}, max {formateur(stat['max']).strip()})")


def ecrire_markdown(chemin, config, resume_global, resume_types, resume_splits,
                    resultats_dernier_run, nb_runs):
    pct = lambda v: f"{v * 100:.1f}%"      # noqa: E731
    sec = lambda v: f"{v:.2f}s"            # noqa: E731
    num = lambda v: f"{v:.2f}".rstrip("0").rstrip(".")  # noqa: E731

    o = []
    o.append(f"# Évaluation RAG e-commerce — `{config['label']}`")
    o.append("")
    o.append("## Configuration du run")
    o.append("")
    o.append("| paramètre | valeur |")
    o.append("| --- | --- |")
    for cle, valeur in config.items():
        o.append(f"| {cle} | `{valeur}` |")
    o.append("")
    o.append("Le pipeline est appelé via `rag_pipeline.evaluer_question()`, qui enchaîne")
    o.append("les mêmes briques que la route `/chat` (`preparer_recherche` puis")
    o.append("`generer_reponse`, lequel consomme le flux `---PRODUITS---` en interne).")
    o.append("Température forcée à 0 et seed fixe : on mesure le pipeline, pas l'aléa")
    o.append("d'échantillonnage (la production tourne à 0.3).")
    o.append("")

    o.append("## Métriques globales")
    o.append("")
    if nb_runs > 1:
        o.append(f"Moyenne sur **{nb_runs} runs** (± écart-type, min, max).")
        o.append("")
    o.append("| métrique | valeur | dénominateur |")
    o.append("| --- | --- | --- |")
    o.append(f"| hit@top_k | {_md_metrique(resume_global.get('hit_at_k'), pct, nb_runs)} "
             f"| {resume_global['n_avec_attendus']} questions avec `expected_ids` |")
    o.append(f"| précision finale | "
             f"{_md_metrique(resume_global.get('precision_finale'), pct, nb_runs)} "
             f"| {resume_global['n_avec_attendus']} questions avec `expected_ids` |")
    o.append(f"| taux d'erreur grave | "
             f"{_md_metrique(resume_global.get('taux_erreur_grave'), pct, nb_runs)} "
             f"| {resume_global['n_questions']} questions |")
    o.append(f"| refus correct | "
             f"{_md_metrique(resume_global.get('refus_correct'), pct, nb_runs)} "
             f"| {resume_global['n_must_refuse']} questions `must_refuse` |")
    o.append(f"| hallucinations | "
             f"{_md_metrique(resume_global.get('hallucinations'), num, nb_runs)} "
             f"| ids recommandés hors catalogue |")
    o.append(f"| échecs | {_md_metrique(resume_global.get('n_echecs'), num, nb_runs)} "
             f"| questions avec ≥1 raison d'échec |")
    o.append("")

    o.append("## Latence")
    o.append("")
    o.append("| étape | valeur |")
    o.append("| --- | --- |")
    lat = resume_global["latence"]
    for libelle, cle in [
        ("total — médiane", "mediane_total"),
        ("total — moyenne", "moyenne_total"),
        ("total — p95", "p95_total"),
        ("reformulation — médiane", "mediane_reformulation"),
        ("embedding — médiane", "mediane_embedding"),
        ("recherche ChromaDB — médiane", "mediane_recherche_chroma"),
        ("génération — médiane", "mediane_generation"),
    ]:
        o.append(f"| {libelle} | {_md_metrique(lat.get(cle), sec, nb_runs)} |")
    o.append("")

    for titre, resume in (("Par type", resume_types), ("Par split", resume_splits)):
        o.append(f"## {titre}")
        o.append("")
        o.append("| groupe | n | hit@top_k | précision | err. grave | refus | halluc. "
                 "| échecs | latence méd. |")
        o.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
        for cle, m in resume.items():
            f = lambda v: "n/a" if v is None else pct(v)         # noqa: E731
            o.append(
                f"| `{cle}` | {m['n_questions']} "
                f"| {f(_m(m, 'hit_at_k'))} "
                f"| {f(_m(m, 'precision_finale'))} "
                f"| {f(_m(m, 'taux_erreur_grave'))} "
                f"| {f(_m(m, 'refus_correct'))} "
                f"| {_fmt_nombre(_m(m, 'hallucinations'))} "
                f"| {_fmt_nombre(_m(m, 'n_echecs'))} "
                f"| {'n/a' if _m(m['latence'], 'mediane_total') is None else sec(_m(m['latence'], 'mediane_total'))} |"
            )
        o.append("")

    # ---- échecs détaillés
    echecs = [r for r in resultats_dernier_run if r["echec"]]
    o.append(f"## Questions échouées — dernier run ({len(echecs)}/"
             f"{len(resultats_dernier_run)})")
    o.append("")
    o.append("Raisons possibles : *aucun attendu trouvé*, *forbidden recommandé*,")
    o.append("*refus manqué*, *hallucination*.")
    o.append("")
    if not echecs:
        o.append("_Aucun échec sur ce run._")
        o.append("")
    for r in echecs:
        o.append(f"### `{r['id']}` — {r['type']} / {r['split']}")
        o.append("")
        o.append(f"**Raison(s)** : {', '.join(r['raisons_echec'])}")
        o.append("")
        o.append(f"- **Question** : {r['question']}")
        if r["reformulation_appliquee"]:
            o.append(f"- **Reformulée** : {r['question_reformulee']}")
        candidats_md = ", ".join(
            "`{}` ({:.4f})".format(c["id"], c["distance"]) for c in r["candidats"]
        )
        o.append(f"- **Candidats ChromaDB** (ordre) : {candidats_md or '—'}")
        o.append(f"- **Attendus** : {', '.join(f'`{i}`' for i in r['expected_ids']) or '—'}")
        o.append(f"- **Interdits** : {', '.join(f'`{i}`' for i in r['forbidden_ids']) or '—'}")
        o.append(f"- **Recommandés** : "
                 f"{', '.join(f'`{i}`' for i in r['ids_recommandes']) or '—'}")
        if r["interdits_recommandes"]:
            o.append(f"- **⚠️ Interdits recommandés** : "
                     f"{', '.join(f'`{i}`' for i in r['interdits_recommandes'])}")
        if r["ids_hallucines"]:
            o.append(f"- **⚠️ Ids hors catalogue** : "
                     f"{', '.join(f'`{i}`' for i in r['ids_hallucines'])}")
        if r["erreur_pipeline"]:
            o.append(f"- **⚠️ Erreur pipeline** : `{r['erreur_pipeline']}`")
        o.append("")

    # ---- réponses must_refuse, en intégralité
    refus = [r for r in resultats_dernier_run if r["must_refuse"]]
    o.append(f"## Réponses aux questions `must_refuse` — dernier run ({len(refus)})")
    o.append("")
    o.append("Le texte EXACT est reproduit ci-dessous : une liste de produits vide ne")
    o.append("suffit pas, il faut vérifier que l'assistant n'a pas répondu au sujet")
    o.append("hors catalogue (capitale, blague, recette…) dans son texte.")
    o.append("")
    for r in refus:
        statut = "✅ liste vide" if not r["ids_recommandes"] else (
            f"❌ a recommandé {', '.join(f'`{i}`' for i in r['ids_recommandes'])}")
        o.append(f"### `{r['id']}` — {r['type']}")
        o.append("")
        o.append(f"- **Question** : {r['question']}")
        o.append(f"- **Produits recommandés** : {statut}")
        o.append("- **Texte exact de la réponse** :")
        o.append("")
        o.append("```text")
        o.append(r["reponse_texte"] if r["reponse_texte"] else "(réponse vide)")
        o.append("```")
        o.append("")

    chemin.write_text("\n".join(o), encoding="utf-8")


# ==========================================================================
def main():
    parseur = argparse.ArgumentParser(
        description="Évalue le pipeline RAG sur eval/dataset.json.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parseur.add_argument("--split", choices=["dev", "test", "all"], default="dev",
                         help="partition a evaluer (defaut : dev)")
    parseur.add_argument("--top-k", type=int, default=NB_RESULTATS,
                         help=f"candidats remontes de ChromaDB (defaut : {NB_RESULTATS})")
    parseur.add_argument("--gen-model", default=MODELE_GENERATION,
                         help=f"modele de generation (defaut : {MODELE_GENERATION})")
    parseur.add_argument("--embed-model", default=MODELE_EMBEDDING,
                         help=f"modele d'embedding (defaut : {MODELE_EMBEDDING}) — "
                              "doit etre celui de l'ingestion")
    parseur.add_argument("--runs", type=int, default=1,
                         help="nombre de repetitions de chaque question (defaut : 1)")
    parseur.add_argument("--label", default="run",
                         help="nom du run, utilise dans le nom des fichiers de sortie")
    parseur.add_argument("--confirm-test", action="store_true",
                         help="obligatoire pour evaluer le split test")
    args = parseur.parse_args()

    # ---- garde-fou sur le split test
    if args.split in ("test", "all") and not args.confirm_test:
        print(
            "\nREFUS : --split "
            f"{args.split} touche au split `test`, qui est protege.\n\n"
            "Le split test ne doit servir qu'UNE SEULE FOIS, A LA FIN, quand les\n"
            "reglages (prompt, top_k, modeles) sont figes. Chaque coup d'oeil\n"
            "supplementaire le transforme en jeu de dev : on finit par ajuster le\n"
            "pipeline dessus, le score monte, et il ne mesure plus rien.\n\n"
            "Itere sur `--split dev`. Quand tu es vraiment pret :\n"
            f"    python eval/run_eval.py --split {args.split} "
            f"--label <nom> --confirm-test\n",
            file=sys.stderr,
        )
        return 2

    if args.runs < 1:
        print("ERREUR : --runs doit valoir au moins 1", file=sys.stderr)
        return 1
    if args.top_k < 1:
        print("ERREUR : --top-k doit valoir au moins 1", file=sys.stderr)
        return 1
    if args.embed_model != MODELE_EMBEDDING:
        print(f"ATTENTION : --embed-model '{args.embed_model}' differe du modele "
              f"d'ingestion '{MODELE_EMBEDDING}'. La recherche sera incoherente "
              f"tant que `python backend/ingestion.py` n'a pas ete rejoue.\n",
              file=sys.stderr)

    # ---- chargement
    dataset = json.loads(CHEMIN_DATASET.read_text(encoding="utf-8"))
    cas = [c for c in dataset if args.split == "all" or c["split"] == args.split]
    if not cas:
        print(f"ERREUR : aucune question pour --split {args.split}", file=sys.stderr)
        return 1

    produits = json.loads(CHEMIN_CATALOGUE.read_text(encoding="utf-8"))
    ids_catalogue = {str(p["id"]) for p in produits}

    try:
        collection = obtenir_collection()
        nb_indexes = collection.count()
    except Exception as exc:
        print(f"ERREUR : ChromaDB inaccessible : {exc}", file=sys.stderr)
        return 1
    if nb_indexes == 0:
        print("ERREUR : collection ChromaDB vide. Lance d'abord "
              "`python backend/ingestion.py`.", file=sys.stderr)
        return 1

    config = {
        "label": args.label,
        "split": args.split,
        "questions": len(cas),
        "runs": args.runs,
        "top_k": args.top_k,
        "modele_generation": args.gen_model,
        "modele_embedding": args.embed_model,
        "temperature": TEMPERATURE_EVAL,
        "seed": SEED_EVAL,
        "ollama_host": OLLAMA_HOST,
        "produits_indexes": nb_indexes,
        "horodatage": datetime.now().isoformat(timespec="seconds"),
    }

    # ---- exécution
    print(f"\n→ {len(cas)} question(s) × {args.runs} run(s) "
          f"= {len(cas) * args.runs} appels au pipeline. Patience.\n", flush=True)

    runs = []
    debut_global = time.perf_counter()
    for numero in range(1, args.runs + 1):
        print(f"--- run {numero}/{args.runs} ---", flush=True)
        resultats = []
        for index, c in enumerate(cas, 1):
            r = evaluer_cas(c, collection, ids_catalogue, args.top_k,
                            args.gen_model, args.embed_model)
            resultats.append(r)
            etat = "ECHEC" if r["echec"] else "ok   "
            print(f"  [{index:>2}/{len(cas)}] {c['id']} {c['type']:<17} "
                  f"{etat} {r['durees']['total']:5.1f}s "
                  f"reco={r['ids_recommandes']}", flush=True)
        runs.append(resultats)
    duree_totale = time.perf_counter() - debut_global
    config["duree_totale_s"] = round(duree_totale, 1)

    # ---- agrégation
    metriques_globales_par_run = [agreger(r) for r in runs]
    resume_global = resumer_runs(metriques_globales_par_run)

    def resumer_groupes(champ, ordre):
        """Moyenne les métriques de chaque groupe à travers les runs."""
        par_run = [agreger_par(r, champ, ordre) for r in runs]
        groupes = list(par_run[0].keys())
        sortie = {}
        for groupe in groupes:
            metriques = [p[groupe] for p in par_run if groupe in p]
            fusion = resumer_runs(metriques)
            fusion["n_questions"] = metriques[0]["n_questions"]
            sortie[groupe] = fusion
        return sortie

    resume_types = resumer_groupes("type", ORDRE_TYPES)
    resume_splits = resumer_groupes("split", ["dev", "test"])

    afficher(resume_global, resume_types, resume_splits, args.runs, config)
    afficher_echecs(runs[-1])

    # ---- sauvegarde
    DOSSIER_RESULTATS.mkdir(parents=True, exist_ok=True)
    horodatage = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    base = f"{horodatage}_{args.label}"
    chemin_json = DOSSIER_RESULTATS / f"{base}.json"
    chemin_md = DOSSIER_RESULTATS / f"{base}.md"

    chemin_json.write_text(json.dumps({
        "config": config,
        "metriques": {
            "global": resume_global,
            "par_type": resume_types,
            "par_split": resume_splits,
            "par_run": metriques_globales_par_run,
        },
        "runs": runs,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    ecrire_markdown(chemin_md, config, resume_global, resume_types, resume_splits,
                    runs[-1], args.runs)

    print("SORTIES")
    print("-" * 98)
    print(f"  detail  : {chemin_json.relative_to(RACINE)}")
    print(f"  synthese: {chemin_md.relative_to(RACINE)}")
    print(f"  duree   : {duree_totale:.0f}s")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())

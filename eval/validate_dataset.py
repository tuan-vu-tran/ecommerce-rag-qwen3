#!/usr/bin/env python3
"""
validate_dataset.py
===================
Valide `eval/dataset.json` (jeu d'évaluation RÉDIGÉ À LA MAIN) sans jamais
lancer le pipeline RAG : purement structurel.

Contrôles bloquants (ERREUR) :
  - JSON valide, liste d'objets
  - champs obligatoires présents et bien typés
  - `id` uniques et non vides
  - `type` et `split` dans les valeurs autorisées
  - tous les `expected_ids` / `forbidden_ids` existent dans data/catalogue.json
  - `must_refuse: true` => `expected_ids` vide
  - `type: followup` => `historique` non vide
  - `historique` bien formé : [{role: user|assistant, content: "..."}]
  - `expected_ids` et `forbidden_ids` disjoints, sans doublon

Contrôles non bloquants (AVERTISSEMENT) :
  - répartition par type / par split qui s'écarte de la cible
  - question vide ou encore sur un gabarit `<EXEMPLE ...>`
  - out_of_scope / injection sans `must_refuse`
  - not_in_catalogue avec des `expected_ids`

Usage :
    python eval/validate_dataset.py
    python eval/validate_dataset.py --strict   # les avertissements font echouer
Code de sortie : 0 si valide, 1 si au moins une erreur.
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
CHEMIN_DATASET = RACINE / "eval" / "dataset.json"
CHEMIN_CATALOGUE = RACINE / "data" / "catalogue.json"

CHAMPS_OBLIGATOIRES = [
    "id", "type", "split", "question",
    "historique", "expected_ids", "forbidden_ids", "must_refuse",
]

TYPES_AUTORISES = [
    "precise", "vague", "situational", "followup",
    "out_of_scope", "not_in_catalogue", "injection",
]
SPLITS_AUTORISES = ["dev", "test"]
ROLES_AUTORISES = ["user", "assistant"]

# Répartition cible du jeu complet (40 questions, dont 10 en split `test`).
CIBLE_TYPES = {
    "precise": 12,
    "vague": 6,
    "situational": 6,
    "followup": 6,
    "out_of_scope": 5,
    "not_in_catalogue": 3,
    "injection": 2,
}
CIBLE_TEST = 10

# Les types qui, par nature, ne doivent recommander aucun produit du catalogue.
TYPES_SANS_PRODUIT = ["out_of_scope", "not_in_catalogue", "injection"]


class Rapport:
    def __init__(self):
        self.erreurs = []
        self.avertissements = []

    def erreur(self, message):
        self.erreurs.append(message)

    def avertir(self, message):
        self.avertissements.append(message)


# ==========================================================================
# Validation entrée par entrée
# ==========================================================================
def valider_entree(index, entree, ids_catalogue, rap):
    etiquette = f"[{index}]"
    if not isinstance(entree, dict):
        rap.erreur(f"{etiquette} n'est pas un objet JSON")
        return

    identifiant = entree.get("id")
    if isinstance(identifiant, str) and identifiant.strip():
        etiquette = f"[{index}] id={identifiant}"

    # -- champs obligatoires
    manquants = [c for c in CHAMPS_OBLIGATOIRES if c not in entree]
    if manquants:
        rap.erreur(f"{etiquette} champs manquants : {', '.join(manquants)}")

    # -- id
    if not isinstance(identifiant, str) or not identifiant.strip():
        rap.erreur(f"{etiquette} 'id' doit etre une chaine non vide")

    # -- type
    type_q = entree.get("type")
    if type_q not in TYPES_AUTORISES:
        rap.erreur(f"{etiquette} 'type' invalide : {type_q!r} "
                   f"(attendu : {', '.join(TYPES_AUTORISES)})")

    # -- split
    split = entree.get("split")
    if split not in SPLITS_AUTORISES:
        rap.erreur(f"{etiquette} 'split' invalide : {split!r} "
                   f"(attendu : {', '.join(SPLITS_AUTORISES)})")

    # -- question
    question = entree.get("question")
    if not isinstance(question, str) or not question.strip():
        rap.erreur(f"{etiquette} 'question' doit etre une chaine non vide")
    elif question.strip().startswith("<EXEMPLE"):
        rap.avertir(f"{etiquette} question encore sur le gabarit "
                    f"'<EXEMPLE ...>' : a rediger a la main")

    # -- must_refuse
    must_refuse = entree.get("must_refuse")
    if not isinstance(must_refuse, bool):
        rap.erreur(f"{etiquette} 'must_refuse' doit etre un booleen")
        must_refuse = bool(must_refuse)

    # -- historique
    historique = entree.get("historique")
    if not isinstance(historique, list):
        rap.erreur(f"{etiquette} 'historique' doit etre une liste")
        historique = []
    else:
        for j, tour in enumerate(historique):
            if not isinstance(tour, dict):
                rap.erreur(f"{etiquette} historique[{j}] n'est pas un objet")
                continue
            if tour.get("role") not in ROLES_AUTORISES:
                rap.erreur(f"{etiquette} historique[{j}] 'role' invalide : "
                           f"{tour.get('role')!r} (attendu : user|assistant)")
            contenu = tour.get("content")
            if not isinstance(contenu, str) or not contenu.strip():
                rap.erreur(f"{etiquette} historique[{j}] 'content' vide")

    if type_q == "followup" and not historique:
        rap.erreur(f"{etiquette} type 'followup' mais 'historique' vide")
    if type_q != "followup" and historique:
        rap.avertir(f"{etiquette} historique non vide pour un type "
                    f"'{type_q}' (acceptable, mais verifier si ce n'est pas "
                    f"un followup)")

    # -- listes d'ids produits
    listes = {}
    for champ in ("expected_ids", "forbidden_ids"):
        valeur = entree.get(champ)
        if not isinstance(valeur, list):
            rap.erreur(f"{etiquette} '{champ}' doit etre une liste")
            listes[champ] = []
            continue
        for pid in valeur:
            if not isinstance(pid, str):
                rap.erreur(f"{etiquette} '{champ}' contient un id non-chaine : {pid!r}")
            elif pid not in ids_catalogue:
                rap.erreur(f"{etiquette} '{champ}' : id '{pid}' absent du catalogue")
        doublons = [p for p, n in Counter(valeur).items() if n > 1]
        if doublons:
            rap.erreur(f"{etiquette} '{champ}' contient des doublons : {doublons}")
        listes[champ] = valeur

    chevauchement = set(listes.get("expected_ids", [])) & set(listes.get("forbidden_ids", []))
    if chevauchement:
        rap.erreur(f"{etiquette} ids a la fois attendus et interdits : "
                   f"{sorted(chevauchement)}")

    # -- coherence must_refuse / expected_ids
    if must_refuse and listes.get("expected_ids"):
        rap.erreur(f"{etiquette} 'must_refuse' vaut true mais 'expected_ids' "
                   f"n'est pas vide : {listes['expected_ids']}")

    # -- coherence type / refus
    if type_q in ("out_of_scope", "injection") and not must_refuse:
        rap.avertir(f"{etiquette} type '{type_q}' sans 'must_refuse: true' "
                    f"(voulu ?)")
    if type_q == "not_in_catalogue" and listes.get("expected_ids"):
        rap.avertir(f"{etiquette} type 'not_in_catalogue' avec des "
                    f"'expected_ids' : l'assistant est cense dire qu'il n'a rien")
    if type_q in TYPES_SANS_PRODUIT and not listes.get("forbidden_ids") and not must_refuse:
        rap.avertir(f"{etiquette} type '{type_q}' sans 'forbidden_ids' ni refus "
                    f"attendu : le cas n'est pas verifiable")


# ==========================================================================
# Répartition
# ==========================================================================
def afficher_repartition(entrees, rap):
    par_type = Counter(e.get("type") for e in entrees if isinstance(e, dict))
    par_split = Counter(e.get("split") for e in entrees if isinstance(e, dict))
    croise = Counter(
        (e.get("type"), e.get("split")) for e in entrees if isinstance(e, dict)
    )

    total = len(entrees)
    total_cible = sum(CIBLE_TYPES.values())

    print("REPARTITION PAR TYPE")
    print(f"  {'type':<18} {'actuel':>7} {'cible':>7} {'ecart':>7}")
    print("  " + "-" * 42)
    for type_q, cible in CIBLE_TYPES.items():
        actuel = par_type.get(type_q, 0)
        ecart = actuel - cible
        marque = "" if ecart == 0 else ("  <--" if ecart else "")
        print(f"  {type_q:<18} {actuel:>7} {cible:>7} {ecart:>+7}{marque}")
        if ecart != 0:
            rap.avertir(f"repartition : type '{type_q}' = {actuel} "
                        f"(cible {cible}, ecart {ecart:+d})")
    inconnus = [t for t in par_type if t not in CIBLE_TYPES]
    for t in inconnus:
        print(f"  {str(t):<18} {par_type[t]:>7} {'-':>7} {'-':>7}")
    print(f"  {'TOTAL':<18} {total:>7} {total_cible:>7} {total - total_cible:>+7}")
    if total != total_cible:
        rap.avertir(f"repartition : total = {total} (cible {total_cible})")
    print()

    print("REPARTITION PAR SPLIT")
    nb_test = par_split.get("test", 0)
    nb_dev = par_split.get("dev", 0)
    print(f"  dev  : {nb_dev}")
    print(f"  test : {nb_test}   (cible {CIBLE_TEST})")
    if nb_test != CIBLE_TEST:
        rap.avertir(f"repartition : split 'test' = {nb_test} "
                    f"(cible {CIBLE_TEST}, ecart {nb_test - CIBLE_TEST:+d})")
    print()

    print("CROISEMENT TYPE x SPLIT")
    print(f"  {'type':<18} {'dev':>5} {'test':>5}")
    print("  " + "-" * 30)
    for type_q in list(CIBLE_TYPES) + inconnus:
        print(f"  {str(type_q):<18} {croise.get((type_q, 'dev'), 0):>5} "
              f"{croise.get((type_q, 'test'), 0):>5}")
    print()


# ==========================================================================
def main():
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--strict", action="store_true",
                         help="traiter les avertissements comme des erreurs")
    args = parseur.parse_args()

    rap = Rapport()

    # -- catalogue
    if not CHEMIN_CATALOGUE.exists():
        print(f"ERREUR : catalogue introuvable : {CHEMIN_CATALOGUE}", file=sys.stderr)
        return 1
    produits = json.loads(CHEMIN_CATALOGUE.read_text(encoding="utf-8"))
    ids_catalogue = {p["id"] for p in produits}

    # -- dataset
    if not CHEMIN_DATASET.exists():
        print(f"ERREUR : dataset introuvable : {CHEMIN_DATASET}", file=sys.stderr)
        return 1
    brut = CHEMIN_DATASET.read_text(encoding="utf-8")
    try:
        entrees = json.loads(brut)
    except json.JSONDecodeError as exc:
        print(f"ERREUR : JSON invalide dans {CHEMIN_DATASET.name} : "
              f"ligne {exc.lineno}, colonne {exc.colno} — {exc.msg}", file=sys.stderr)
        return 1

    print()
    print("=" * 60)
    print("VALIDATION DU JEU D'EVALUATION")
    print("=" * 60)
    print(f"dataset   : {CHEMIN_DATASET.relative_to(RACINE)}")
    print(f"catalogue : {CHEMIN_CATALOGUE.relative_to(RACINE)} "
          f"({len(ids_catalogue)} produits)")
    print()

    if not isinstance(entrees, list):
        print("ERREUR : la racine du dataset doit etre une liste d'objets.",
              file=sys.stderr)
        return 1

    # -- unicite des ids
    ids = [e.get("id") for e in entrees if isinstance(e, dict)]
    doublons = sorted({i for i, n in Counter(ids).items() if n > 1 and i is not None})
    if doublons:
        rap.erreur(f"'id' en doublon dans le dataset : {doublons}")

    for index, entree in enumerate(entrees):
        valider_entree(index, entree, ids_catalogue, rap)

    afficher_repartition(entrees, rap)

    # -- bilan
    if rap.erreurs:
        print(f"ERREURS ({len(rap.erreurs)}) :")
        for message in rap.erreurs:
            print(f"  x {message}")
        print()
    if rap.avertissements:
        print(f"AVERTISSEMENTS ({len(rap.avertissements)}) :")
        for message in rap.avertissements:
            print(f"  ! {message}")
        print()

    if rap.erreurs:
        print(f"RESULTAT : INVALIDE ({len(rap.erreurs)} erreur(s), "
              f"{len(rap.avertissements)} avertissement(s))")
        print()
        return 1

    if rap.avertissements and args.strict:
        print(f"RESULTAT : INVALIDE en mode --strict "
              f"({len(rap.avertissements)} avertissement(s))")
        print()
        return 1

    print(f"RESULTAT : VALIDE ({len(rap.avertissements)} avertissement(s))")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())

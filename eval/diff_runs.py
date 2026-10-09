#!/usr/bin/env python
"""Compare plusieurs fichiers de résultats d'évaluation, question par question.

Ne touche ni au pipeline, ni au prompt, ni au dataset : lit uniquement les
`.json` produits par `run_eval.py`. Le PREMIER fichier sert de référence ; les
suivants lui sont comparés.

Deux runs  : différences par rapport au premier.
Trois runs ou plus : tableau côte à côte + différences par rapport au premier.

Usage :
    python eval/diff_runs.py <reference>.json <variante>.json [<variante2>.json ...]
"""

import argparse
import json
import sys
from collections import Counter


def charger(chemin):
    with open(chemin, encoding="utf-8") as f:
        return json.load(f)


def par_question(resultats):
    """{id_question: [enregistrement du run 1, du run 2, ...]} (ordre des passages)."""
    index = {}
    for run in resultats["runs"]:
        for q in run:
            index.setdefault(q["id"], []).append(q)
    return index


def signature(q):
    """Ce qui caractérise le RÉSULTAT d'une question sur un passage donné.

    Les ids sont comparés en ENSEMBLE : un simple changement d'ordre des
    recommandations n'est pas un changement de résultat (signalé à part).
    """
    return (
        tuple(sorted(q["ids_recommandes"])),
        bool(q["echec"]),
        tuple(sorted(q["raisons_echec"])),
    )


def signatures(enregs):
    return {signature(q) for q in enregs}


def ordre_seul(enregs_a, enregs_b):
    """Vrai si seul l'ORDRE des recommandations change (mêmes ids, même statut)."""
    ordres_a = {tuple(q["ids_recommandes"]) for q in enregs_a}
    ordres_b = {tuple(q["ids_recommandes"]) for q in enregs_b}
    return ordres_a != ordres_b and signatures(enregs_a) == signatures(enregs_b)


def stabilite(enregs):
    """'stable' si tous les passages donnent le même résultat, sinon 'VARIABLE'."""
    return "stable" if len(signatures(enregs)) == 1 else "VARIABLE"


def statut(q):
    return "ÉCHEC" if q["echec"] else "réussite"


def fmt_ids(ids):
    return ", ".join(ids) if ids else "(aucun)"


def resume_runs(enregs, champ_fmt):
    """Décrit un champ sur l'ensemble des passages, en compactant les doublons."""
    valeurs = [champ_fmt(q) for q in enregs]
    if len(set(valeurs)) == 1:
        return valeurs[0]
    return " | ".join(f"p{i}: {v}" for i, v in enumerate(valeurs, 1))


def pourcent(x):
    return "n/a" if x is None else f"{100 * x:.1f}%"


def cellule(bloc, formateur):
    if bloc is None:
        return "n/a"
    # un écart-type non nul signale un résultat qui bouge d'un passage à l'autre
    marque = "" if bloc["ecart_type"] == 0 else f" (±{formateur(bloc['ecart_type'])})"
    return f"{formateur(bloc['moyenne'])}{marque}"


# (libellé, chemin dans metriques['global'], formateur)
METRIQUES = [
    ("hit@top_k", ("hit_at_k",), pourcent),
    ("précision finale", ("precision_finale",), pourcent),
    ("taux d'erreur grave", ("taux_erreur_grave",), pourcent),
    ("refus correct", ("refus_correct",), pourcent),
    ("hallucinations", ("hallucinations",), lambda x: f"{x:.2f}"),
    ("échecs", ("n_echecs",), lambda x: f"{x:.2f}"),
    ("latence médiane", ("latence", "mediane_total"), lambda x: f"{x:.2f}s"),
]


def creuser(bloc, chemin):
    for cle in chemin:
        bloc = bloc[cle]
    return bloc


def tableau_cote_a_cote(resultats, libelles):
    entetes = " | ".join(libelles)
    lignes = [f"| métrique | {entetes} |",
              "| --- | " + " | ".join("---" for _ in libelles) + " |"]
    for nom, chemin, formateur in METRIQUES:
        cellules = [
            cellule(creuser(r["metriques"]["global"], chemin), formateur)
            for r in resultats
        ]
        lignes.append(f"| {nom} | " + " | ".join(cellules) + " |")
    return "\n".join(lignes)


def tableau_par_type(resultats, libelles):
    """Précision par type, côte à côte — là où les régressions se voient."""
    types = []
    for r in resultats:
        for t in r["metriques"].get("par_type", {}):
            if t not in types:
                types.append(t)
    if not types:
        return None
    entetes = " | ".join(libelles)
    lignes = [f"| type | {entetes} |",
              "| --- | " + " | ".join("---" for _ in libelles) + " |"]
    for t in types:
        cellules = []
        for r in resultats:
            bloc = r["metriques"].get("par_type", {}).get(t, {})
            pf = bloc.get("precision_finale")
            rf = bloc.get("refus_correct")
            # un type must_refuse n'a pas de précision : on affiche le refus
            cellules.append(cellule(pf, pourcent) if pf else
                            (f"refus {cellule(rf, pourcent)}" if rf else "n/a"))
        lignes.append(f"| `{t}` | " + " | ".join(cellules) + " |")
    return "\n".join(lignes)


def main():
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("fichiers", nargs="+",
                   help="json de référence en premier, puis les variantes")
    args = p.parse_args()

    if len(args.fichiers) < 2:
        p.error("il faut au moins deux fichiers à comparer")

    resultats = [charger(f) for f in args.fichiers]
    index = [par_question(r) for r in resultats]
    libelles = [f"`{r['config']['label']}`" for r in resultats]
    n_passages = [len(r["runs"]) for r in resultats]

    if len(set(n_passages)) != 1:
        print(f"⚠️  comparaison à nombre de passages INÉGAL : {n_passages}\n",
              file=sys.stderr)

    print("# Comparaison de runs d'évaluation\n")
    for f, r, n in zip(args.fichiers, resultats, n_passages):
        role = "RÉFÉRENCE" if f == args.fichiers[0] else "variante"
        print(f"- **{role}** : `{r['config']['label']}` — {n} passages, `{f}`")
    print()

    # Toute divergence de configuration invaliderait la comparaison.
    for cle in ("split", "top_k", "modele_generation", "temperature", "seed"):
        valeurs = [r["config"].get(cle) for r in resultats]
        drapeau = "" if len(set(map(str, valeurs))) == 1 else "   ← DIFFÈRE"
        print(f"- `{cle}` : {' / '.join(map(str, valeurs))}{drapeau}")
    print()

    print("## Métriques globales côte à côte\n")
    print(tableau_cote_a_cote(resultats, libelles))
    print("\n`±` = écart-type entre passages ; absent si le résultat est "
          "identique sur tous les passages.\n")

    par_type = tableau_par_type(resultats, libelles)
    if par_type:
        print("## Précision par type côte à côte\n")
        print(par_type)
        print()

    ref_index = index[0]
    ref_label = resultats[0]["config"]["label"]

    for i in range(1, len(resultats)):
        var_index, var_label = index[i], resultats[i]["config"]["label"]
        communs = [q for q in ref_index if q in var_index]
        absents = sorted(set(ref_index) ^ set(var_index))

        differentes = [q for q in sorted(communs)
                       if signatures(ref_index[q]) != signatures(var_index[q])]
        ordre = [q for q in sorted(communs)
                 if ordre_seul(ref_index[q], var_index[q])]

        print(f"## `{var_label}` vs `{ref_label}` — "
              f"{len(differentes)} différence(s) sur {len(communs)}\n")
        if absents:
            print(f"⚠️  questions présentes d'un seul côté : {fmt_ids(absents)}\n")
        if ordre:
            print(f"*(En plus : {len(ordre)} question(s) où seul l'ORDRE des "
                  f"recommandations change, mêmes ids et même statut — "
                  f"{fmt_ids(ordre)}. Non comptées.)*\n")
        if not differentes:
            print("Aucune question ne change de résultat.\n")

        for qid in differentes:
            er, ev = ref_index[qid], var_index[qid]
            ref = er[0]
            print(f"### `{qid}` — {ref['type']}\n")
            print(f"- **Question** : {ref['question']}")
            if ref["historique"]:
                print(f"- **Reformulée** : "
                      f"{resume_runs(ev, lambda q: q['question_reformulee'])}")
            print(f"- **Attendus** : {fmt_ids(ref['expected_ids'])}"
                  f"{'  (must_refuse)' if ref['must_refuse'] else ''}")
            print(f"- **Recommandés `{ref_label}`** : "
                  f"{resume_runs(er, lambda q: fmt_ids(q['ids_recommandes']))}")
            print(f"- **Recommandés `{var_label}`** : "
                  f"{resume_runs(ev, lambda q: fmt_ids(q['ids_recommandes']))}")
            print(f"- **Statut** : {resume_runs(er, statut)} → "
                  f"{resume_runs(ev, statut)}")
            print(f"- **Raison d'échec `{ref_label}`** : "
                  f"{resume_runs(er, lambda q: ', '.join(q['raisons_echec']) or '—')}")
            print(f"- **Raison d'échec `{var_label}`** : "
                  f"{resume_runs(ev, lambda q: ', '.join(q['raisons_echec']) or '—')}")
            print(f"- **Stabilité** : `{ref_label}` = {stabilite(er)}, "
                  f"`{var_label}` = {stabilite(ev)}")
            print()

    # Vue d'ensemble : distingue un vrai effet du changement de l'aléa de tirage.
    print("## Stabilité sur l'ensemble des questions\n")
    for r, idx in zip(resultats, index):
        variables = sorted(q for q in idx if stabilite(idx[q]) == "VARIABLE")
        print(f"- **`{r['config']['label']}`** : {len(variables)} question(s) "
              f"variable(s) sur {len(idx)} — {fmt_ids(variables)}")
    print()

    interessantes = sorted({
        q for idx in index for q in idx if stabilite(idx[q]) == "VARIABLE"
    })
    if interessantes:
        print("### Détail des questions variables (fréquence par id)\n")
        for qid in interessantes:
            for r, idx, n in zip(resultats, index, n_passages):
                if qid not in idx:
                    continue
                compte = Counter()
                for q in idx[qid]:
                    compte.update(q["ids_recommandes"])
                detail = ", ".join(f"{i} ×{c}/{n}" for i, c in compte.most_common())
                marque = "" if stabilite(idx[qid]) == "stable" else "  ← VARIABLE"
                print(f"- `{qid}` `{r['config']['label']}` : "
                      f"{detail or '(aucun)'}{marque}")
            print()


if __name__ == "__main__":
    main()

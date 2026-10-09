# Jeu d'évaluation

dataset.json contient 40 questions étiquetées (7 types : precise, vague, situational,
followup, out_of_scope, not_in_catalogue, injection).

Brouillon rédigé avec l'aide d'un assistant IA, puis relu et retravaillé à la main.
Étiquettes (expected_ids, forbidden_ids) vérifiées contre les prix et caractéristiques du catalogue.
Split : 30 questions dev pour ajuster le système, 10 questions test mesurées une seule fois à la fin.

---

## Outillage

```
eval/
├── catalogue_reference.py    # fiche de référence du catalogue (aide à la rédaction)
├── catalogue_reference.md    # sortie générée — ne pas éditer à la main
├── dataset.json              # le jeu d'évaluation (rédigé à la main)
├── validate_dataset.py       # validateur structurel du dataset
├── run_eval.py               # harnais d'évaluation (appelle le pipeline réel)
└── results/                  # <date>_<label>.json (ignoré) + .md (versionné)
```

```bash
conda activate rag-qwen        # Ollama doit tourner, catalogue indexé

python eval/catalogue_reference.py     # fiche de référence (terminal + .md)
python eval/validate_dataset.py        # 0 = valide, 1 = erreurs
python eval/run_eval.py --split dev --label baseline --runs 3
```

## `run_eval.py`

| argument | défaut | rôle |
| --- | --- | --- |
| `--split` | `dev` | `dev`, `test` ou `all` |
| `--top-k` | `5` (`NB_RESULTATS`) | candidats remontés de ChromaDB |
| `--gen-model` | `qwen3:8b` | modèle de génération / reformulation |
| `--embed-model` | `qwen3-embedding:0.6b` | **doit** être celui de l'ingestion |
| `--runs` | `1` | répétitions de chaque question |
| `--label` | `run` | nom du run (nom des fichiers de sortie) |
| `--confirm-test` | — | obligatoire dès que `test` est touché |

`--split test` et `--split all` **refusent de démarrer** sans `--confirm-test`
(code de sortie 2) : le split test ne doit servir qu'une fois, à la fin, quand
les réglages sont figés.

### Comment le harnais appelle le pipeline

`run_eval.py` ne réimplémente rien. Il appelle
`rag_pipeline.evaluer_question()`, qui enchaîne les mêmes briques que la route
`/chat` de production :

```
preparer_recherche()                 <- partagé par /chat, la CLI et l'éval
  ├── reformuler_question()          étape 0
  └── recherche_semantique()         étape 1 (embedding + query ChromaDB)
generer_reponse()                    étape 2
  └── generer_reponse_stream()       le streaming reste la source de vérité :
                                     la version non-streamée consomme le flux
                                     et coupe sur ---PRODUITS---
```

Paramètres passés en arguments, jamais codés en dur : `top_k`,
`modele_generation`, `modele_embedding`, `temperature`, `seed`. Leurs **défauts
reproduisent exactement la production** (`top_k=5`, `temperature=0.3`,
`seed=None`) ; l'évaluation force `temperature=0` et `seed=42` pour mesurer le
pipeline et non l'aléa d'échantillonnage.

### Métriques

| métrique | définition | dénominateur |
| --- | --- | --- |
| **hit@top_k** | au moins un `expected_id` parmi les candidats ChromaDB | questions avec `expected_ids` non vide |
| **précision finale** | au moins un id recommandé dans `expected_ids` **et** aucun dans `forbidden_ids` | questions avec `expected_ids` non vide |
| **taux d'erreur grave** | un `forbidden_id` figure dans les recommandations | toutes les questions |
| **refus correct** | `produits_recommandes` vide | questions `must_refuse: true` |
| **hallucinations** | nombre d'ids recommandés absents de `data/catalogue.json` | — |
| **latence** | médiane / moyenne / p95 du total, + médiane par étape | questions exécutées |

Chaque métrique est calculée **globalement, par `type` et par `split`**.

Le couple **hit@top_k / précision finale** est le cœur du diagnostic :

- `hit@top_k` bas → problème de **recherche** (embedding, `top_k`, formulation
  des descriptions). Le bon produit n'a jamais atteint le modèle.
- `hit@top_k` haut mais précision basse → problème de **génération** : le bon
  produit était dans le contexte et le modèle ne l'a pas retenu (ou a retenu un
  interdit). C'est le prompt qu'il faut regarder, pas la recherche.

Les **hallucinations** doivent rester à 0 : `_parser_produits()` filtre déjà les
recommandations sur les ids candidats. La métrique vérifie que ce filet tient.

### Sorties

- `eval/results/<date>_<label>.json` — traces complètes (question reformulée,
  candidats + distances, réponse, durées par étape, pour chaque run).
  **Non versionné** : volumineux et régénérable.
- `eval/results/<date>_<label>.md` — synthèse **versionnée** : config, métriques
  globales / par type / par split, questions échouées avec leur raison (*aucun
  attendu trouvé*, *forbidden recommandé*, *refus manqué*, *hallucination*), et
  le **texte exact** de chaque réponse `must_refuse`.

Ce dernier point est volontaire : une liste de produits vide ne prouve pas que le
refus est correct. Il faut lire le texte pour vérifier que l'assistant n'a pas
répondu au sujet hors catalogue (donner la capitale, raconter la blague) tout en
renvoyant `[]`. Aucune métrique automatique ne capture ça.

### `--runs N`

Avec `N > 1`, chaque question est rejouée `N` fois ; le rapport donne la
**moyenne ± écart-type (min, max)** de chaque métrique. Même à `temperature=0`
la génération n'est pas parfaitement déterministe : l'écart-type dit si un écart
de score entre deux configurations est réel ou dans le bruit.

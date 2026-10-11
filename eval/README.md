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

Le nom des fichiers est **le label seul** (pas d'horodatage) : les runs restent
faciles à citer et à passer à `diff_runs.py`. Relancer un label **écrase** son run
précédent ; l'horodatage exact reste tracé dans `config.horodatage`, à l'intérieur
des fichiers.

- `eval/results/<label>.json` — traces complètes (question reformulée,
  candidats + distances, réponse, durées par étape, pour chaque run).
  **Non versionné** : volumineux et régénérable.
- `eval/results/<label>.md` — synthèse **versionnée** : config, métriques
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

## Runs mesurés (split `dev`)

Tous les runs : 30 questions × 3 passages, `qwen3:8b` + `qwen3-embedding:0.6b`,
`temperature=0`, `seed=42`. Les trois premiers ne font varier que le
`SYSTEM_PROMPT` (`top_k=5`) ; les deux derniers reprennent le prompt de
`prompt-v2` et ne font varier que `top_k`.

| métrique | `prompt-v0` | `prompt-v1` | **`prompt-v2`** | `topk-3` | `topk-8` |
| --- | --- | --- | --- | --- | --- |
| `top_k` | 5 | 5 | **5** | 3 | 8 |
| hit@top_k | 91.3% | 91.3% | **91.3%** | 78.3% | 95.7% |
| précision finale | 82.6% | 73.9% | **81.2% (±2.5%)** | 71.0% (±2.5%) | 82.6% |
| taux d'erreur grave | 1.1% (±1.9%) | 2.2% (±1.9%) | **6.7%** | 3.3% | 6.7% |
| refus correct | 85.7% | 100% | **100%** | 100% | 100% |
| hallucinations | 0 | 0 | **0** | 0 | 0 |
| échecs / 30 | 5.00 | 6.00 | **4.33 (±0.58)** | 6.67 (±0.58) | 4.00 |
| latence médiane | 7.10s | 6.85s | **7.43s** | 6.48s | 7.07s |

Précision par type :

| type | `prompt-v0` | `prompt-v1` | **`prompt-v2`** | `topk-3` | `topk-8` |
| --- | --- | --- | --- | --- | --- |
| `precise` | 88.9% | 77.8% | **85.2% (±6.4%)** | 77.8% | 77.8% |
| `vague` | 100% | 100% | **100%** | 80.0% | 100% |
| `situational` | 100% | 80.0% | **100%** | 86.7% (±11.5%) | 100% |
| `followup` | 25.0% | 25.0% | **25.0%** | 25.0% | 50.0% |
| `out_of_scope` | refus 100% | refus 100% | **refus 100%** | refus 100% | refus 100% |
| `not_in_catalogue` | refus 50.0% | refus 100% | **refus 100%** | refus 100% | refus 100% |
| `injection` | refus 100% | refus 100% | **refus 100%** | refus 100% | refus 100% |

### Itérations de prompt (`top_k=5` partout)

- **`prompt-v0`** — état de départ. Seul défaut de refus : `q036` (« écouteurs
  sans fil ») présentait des téléphones (`not_in_catalogue` 50%).
- **`prompt-v1`** — ajout des règles 3 à 6 (périmètre réel du catalogue). Refus
  réparés (100% partout) mais **précision en régression** (82.6% → 73.9%) : la
  règle 4, rédigée trop large, écartait des produits légitimes au motif qu'ils ne
  collaient pas assez aux critères du client.
- **`prompt-v2`** — **un seul changement** : la règle 4 ne porte plus que sur la
  **catégorie** demandée, l'adéquation aux critères ne pouvant plus motiver un
  refus. Précision récupérée (73.9% → 81.2%) en gardant les refus à 100%. Échecs
  restants : `q012`, `q027`, `q029`, `q030` — tous déjà en échec à `prompt-v0`,
  donc aucune question nouvellement cassée.

### `topk-3` vs `prompt-v2` — questions qui changent de résultat

`hit@top_k` tombe à 78.3% : couper à 3 candidats prive le modèle de produits
attendus qu'il recommandait.

| question | type | `prompt-v2` | `topk-3` | effet |
| --- | --- | --- | --- | --- |
| `q007` « laptop avec RTX 4060 » | `precise` | réussite 2/3 (`70185`) | **ÉCHEC** stable | `70185` était 4ᵉ candidat → coupé |
| `q017` « un truc puissant » | `vague` | réussite (`83721`, `50839`) | **ÉCHEC** stable | les 3 candidats sont tous hors-cible |
| `q024` streaming + jeu, 1500 € | `situational` | réussite stable | **ÉCHEC 2/3** | `70185` ne survit qu'1 passage sur 3 |
| `q012` « stylet intégré » | `precise` | ÉCHEC (aucun produit) | ÉCHEC **+ interdit** `43620` | moins de candidats → le modèle se rabat sur un interdit |

Les 8 autres différences ne changent pas le statut (liste tronquée : `q006`,
`q009`, `q013`, `q014`, `q018`, `q020`, `q027`, `q030`). Le taux d'erreur grave
qui baisse (6.7% → 3.3%) est un **artefact** : moins de candidats = moins
d'occasions de recommander un interdit, pas une meilleure qualité. Seul gain
réel : ~1s de latence médiane.

### `topk-8` vs `prompt-v2` — questions qui changent de résultat

| question | type | `prompt-v2` | `topk-8` | effet |
| --- | --- | --- | --- | --- |
| `q029` « je préfère Windows » | `followup` | ÉCHEC (`16053`, `27193`) | **réussite** (`63298`) | `63298` était au-delà du top-5 → `followup` passe de 25% à 50% |
| `q007` « laptop avec RTX 4060 » | `precise` | réussite 2/3 (`70185`) | **ÉCHEC** stable | `70185` est bien candidat (4ᵉ) mais le contexte élargi fait préférer `83721`/`50839` |
| `q012` « stylet intégré » | `precise` | ÉCHEC (aucun produit) | ÉCHEC (aucun produit) | `82461` ne remonte pas, même sur 8 candidats |

Les 8 autres différences ne changent pas le statut (`q001`, `q004`, `q009`,
`q013`, `q014`, `q015`, `q017`, `q020`) : ce sont surtout des recommandations
plus complètes (`q001` passe de 2 à 4 attendus, `q004` de 2 à 3). `topk-8` est
aussi un peu plus stable (1 question variable sur 30 contre 2) mais `q027` et
`q030` restent en erreur grave, d'où un taux d'erreur grave inchangé.

### Décision : on garde `top_k = 5`

Règle fixée **avant** les runs : une autre valeur de `top_k` ne remplace la
valeur par défaut que si elle gagne **au moins 2 questions** en précision finale.
`topk-8` en gagne 1 (`q029`) et en perd 1 (`q007`) → critère non rempli,
`NB_RESULTATS` reste à 5. `topk-3` est écarté sans discussion.

**Conclusion.** `top_k=3` dégrade à la fois le recall (91.3% → 78.3%) et la
précision finale (81.2% → 71.0%) : trop de produits attendus n'atteignent plus le
modèle. `top_k=8` gagne 4 points de recall (95.7%) mais la précision finale
(82.6% vs 81.2% ±2.5%) reste dans le bruit run-à-run, donc ne justifie pas le
changement. `q012` (« stylet intégré ») échoue même à `top_k=8` : c'est un
problème d'**embedding/recherche**, qu'aucun `top_k` ne rattrape. Les questions
de suivi (`followup` : 25% de précision pour 75% de `hit@top_k`, et les deux
erreurs graves `q027`/`q030`) restent le **principal axe d'amélioration**, et il
porte sur la **reformulation**, pas sur `top_k` ni sur le prompt de génération.

## Résultat final (split `test`, 10 questions)

Run unique et définitif : `eval/results/test-final.md`
(`python eval/run_eval.py --split test --confirm-test --top-k 5 --label test-final --runs 3`).
Réglages **figés avant le run** : `SYSTEM_PROMPT` **v2**, **`top_k = 5`**,
`qwen3:8b` + `qwen3-embedding:0.6b`, `temperature=0`, `seed=42`, 3 passages.
Aucun réglage, prompt ni élément du dataset n'a été modifié après ce run.

Les dénominateurs diffèrent par métrique : sur les 10 questions du split, **7**
ont des `expected_ids` (donc comptent pour le recall et la précision) et **3**
sont `must_refuse`. Résultats **identiques sur les 3 passages** (±0.0% partout).

| métrique | comptage | % |
| --- | --- | --- |
| hit@top_k (`top_k=5`) | **7/7** | 100% |
| précision finale | **6/7** | 85.7% |
| refus correct | **3/3** | 100% |
| erreur grave (produit interdit recommandé) | **0/10** | 0% |
| hallucinations (id hors catalogue) | **0** | 0 |
| questions en échec | **1/10** | 10% |

Latence (totale par question) : **médiane 7.21s**, **p95 16.90s** (moyenne
7.62s). La génération est l'essentiel du coût (médiane 6.75s) ; embedding 0.16s,
recherche ChromaDB et reformulation < 0.01s. Les refus sont les plus rapides
(1.3–1.6s, le modèle n'a rien à justifier) ; la question `vague` est la plus
lente (21.6s, 5 produits à détailler).

Par type (n petit, à lire comme des comptages) : `precise` 3/3, `vague` 1/1,
`situational` 1/1, `followup` **1/2**, et les trois refus (`out_of_scope`,
`not_in_catalogue`, `injection`) corrects 1/1 chacun.

### Question en échec (1/10)

| question | type | nature de l'échec | détail |
| --- | --- | --- | --- |
| `q025` « Et en moins cher ? » | `followup` | **génération** | Reformulée en « un smartphone haut de gamme moins cher ». La recherche a réussi : `72046` (attendu) est bien dans les candidats (rang 5, distance 1.0161). Le modèle recommande `43620` et `70294`, aucun attendu, aucun interdit → pas d'erreur grave, mais précision manquée. Échec **stable sur les 3 passages**. |

Aucun échec de **recherche** sur ce split : `hit@top_k = 7/7`, le bon produit a
toujours atteint le modèle. L'unique échec est donc côté **génération**, et
porte — comme sur le split `dev` — sur une question de **suivi**.

Observation hors métrique, relevée en lisant les textes de refus : `q037`
(« imprimante laser », `not_in_catalogue`) reçoit la redirection générique de la
règle 1 et non la formulation prévue par la règle 5 (dire que ce type de produit
n'est pas au catalogue et proposer son aide sur les deux catégories). La liste
produits est vide, donc la métrique le compte correct ; le texte est néanmoins
moins utile qu'il pourrait l'être. **Non corrigé** (réglages figés).

## Axes d'amélioration

Rien de ce qui suit n'a été appliqué : le prompt v2, `top_k = 5` et le dataset
sont figés depuis le run `test-final`.

- **Questions de suivi (`followup`) — point faible principal.** C'est le seul
  type en échec sur le split `test` (1/2) et le plus fragile sur `dev` (25% de
  précision pour 75% de `hit@top_k`, avec les deux erreurs graves `q027` et
  `q030`). Le problème est la **reformulation** (étape 0), pas le prompt de
  génération : elle transforme une demande comparative (« et moins cher ? »,
  « plus haut de gamme ») en demande absolue et perd l'ancrage au produit du tour
  précédent. `q025` en est l'illustration exacte.
- **`q012` « stylet intégré » — problème d'embedding.** Le produit attendu
  (`82461`) ne remonte pas, même avec `top_k = 8` : le bon candidat n'atteint
  jamais le modèle, donc aucun prompt ne peut le rattraper. C'est la recherche
  (modèle d'embedding / texte indexé) qu'il faudrait travailler.
- **Prompt v3 — envisagée, NON testée.** Une règle supplémentaire « ne pas
  reproposer un produit déjà proposé dans la conversation » a été envisagée pour
  les questions de suivi, puis **écartée sans run de mesure** : elle arrivait
  après le gel des réglages, et une règle ajoutée sans évaluation est exactement
  ce qui avait fait régresser `prompt-v1`. Aucun chiffre n'est donc disponible
  pour elle, et ce n'est pas une amélioration démontrée.
- **`top_k`** : exploré et tranché (voir plus haut) — `5` est conservé.

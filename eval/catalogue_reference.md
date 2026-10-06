# Fiche de référence du catalogue

> **Généré par `eval/catalogue_reference.py` — ne pas éditer à la main.**
> Les valeurs ci-dessous sont extraites par regex/heuristiques depuis le
> texte libre des descriptions (le catalogue n'a aucun champ structuré).
> Les lignes marquées **⚠️** doivent être vérifiées manuellement avant
> d'être utilisées pour rédiger `eval/dataset.json`.

- Produits : **30**
- Catégories : **18** laptop · **12** téléphone · **0** indéterminé
- Prix : min **349 €** · max **3899 €** · médiane **1299 €**
- Extractions douteuses : **11**

## Tableau

| ID | Nom | Catégorie | Prix (€) | ⚠️ | Usage (8 premiers mots) |
| --- | --- | --- | ---: | :-: | --- |
| `48213` | MacBook Air M3 | laptop | 1349 |  | parfait pour les professionnels nomades et les étudiants |
| `91847` | Dell XPS 15 | laptop | 2199 |  | s'adresse aux créateurs de contenu et développeurs exigeants |
| `27650` | ASUS ROG Strix G16 | laptop | 1799 |  | pensée pour le gaming compétitif. Sous le capot |
| `63298` | Lenovo ThinkPad X1 Carbon Gen 12 | laptop | 1599 | ⚠️ | est la référence absolue pour les professionnels d'entreprise |
| `15734` | iPhone 16 Pro Max | telephone | 1479 | ⚠️ | L'iPhone 16 Pro Max représente le sommet de |
| `82461` | Samsung Galaxy S25 Ultra | telephone | 1419 | ⚠️ | idéal pour la prise de notes et les |
| `39572` | Google Pixel 9 Pro | telephone | 999 | ⚠️ | Le Google Pixel 9 Pro séduit par la |
| `70185` | MSI Katana 15 | laptop | 1099 |  | s'impose comme une option gaming accessible pour les |
| `54903` | ASUS ZenBook 14 OLED | laptop | 1299 |  | cible les professionnels créatifs qui veulent un écran |
| `16820` | HP Spectre x360 14 | laptop | 1549 |  | parfait pour la prise de notes manuscrites et |
| `60347` | Xiaomi 14T Pro | telephone | 749 | ⚠️ | Le Xiaomi 14T Pro propose un excellent compromis |
| `83721` | Lenovo Legion Pro 7 | laptop | 3499 |  | taillée pour les joueurs les plus exigeants, rivalisant |
| `27193` | Acer Aspire 5 | laptop | 549 |  | pour un usage bureautique quotidien sans prétention. AMD |
| `94582` | iPhone 16 | telephone | 969 | ⚠️ | L'iPhone 16 est le modèle grand public de |
| `41639` | Samsung Galaxy A55 5G | telephone | 489 | ⚠️ | Le Samsung Galaxy A55 5G est le champion |
| `58274` | ASUS ProArt Studiobook 16 | laptop | 3899 |  | s'adresse exclusivement aux créateurs professionnels : monteurs vidéo |
| `72046` | OnePlus 12 | telephone | 899 | ⚠️ | Le OnePlus 12 combine puissance brute et charge |
| `31958` | Dell Inspiron 15 | laptop | 649 |  | pour un usage familial ou étudiant, sans fonctionnalité |
| `85217` | MacBook Pro 14 M4 Pro | laptop | 2549 |  | s'adresse aux développeurs et créateurs professionnels qui ont |
| `43620` | Nothing Phone 2a | telephone | 349 | ⚠️ | pour un usage quotidien standard. Écran AMOLED 6.7 |
| `67304` | MSI Prestige 16 AI Evo | laptop | 1899 |  | cible les professionnels en mobilité qui ont besoin |
| `29465` | Google Pixel 9a | telephone | 549 |  | Le Google Pixel 9a apporte l'expérience Pixel authentique |
| `50839` | Razer Blade 16 | laptop | 3799 |  | pour les joueurs et créateurs qui veulent le |
| `38172` | Samsung Galaxy Z Flip 6 | telephone | 1199 | ⚠️ | pour un usage quotidien et les réseaux sociaux |
| `94718` | HP Omen 16 | laptop | 1449 |  | pour un usage professionnel occasionnel. Poids de 2.4 |
| `16053` | Lenovo IdeaPad Slim 3 | laptop | 429 |  | est le choix économique par excellence pour un |
| `70294` | Xiaomi Redmi Note 13 Pro+ | telephone | 399 |  | Le Xiaomi Redmi Note 13 Pro+ démocratise des |
| `82605` | ASUS Vivobook Pro 15 OLED | laptop | 999 |  | cible les créateurs de contenu débutants et les |
| `45930` | iPhone SE | telephone | 599 | ⚠️ | pour les utilisateurs qui trouvent les iPhone Pro |
| `59416` | Framework Laptop 16 | laptop | 1699 |  | pour les utilisateurs sensibles à la réparabilité, à |

## À vérifier à la main

### `63298` — Lenovo ThinkPad X1 Carbon Gen 12

- nom: 6 tokens atteints : nom peut-etre tronque
- prix: prix HT (hors taxes)

### `15734` — iPhone 16 Pro Max

- prix: prix d'entree de gamme ('a partir de') ; prix lie a une configuration precise

### `82461` — Samsung Galaxy S25 Ultra

- prix: prix lie a une configuration precise

### `39572` — Google Pixel 9 Pro

- prix: prix lie a une configuration precise

### `60347` — Xiaomi 14T Pro

- prix: prix lie a une configuration precise

### `94582` — iPhone 16

- prix: prix d'entree de gamme ('a partir de') ; prix lie a une configuration precise

### `41639` — Samsung Galaxy A55 5G

- prix: prix lie a une configuration precise

### `72046` — OnePlus 12

- prix: prix lie a une configuration precise

### `43620` — Nothing Phone 2a

- prix: prix lie a une configuration precise

### `38172` — Samsung Galaxy Z Flip 6

- prix: prix lie a une configuration precise

### `45930` — iPhone SE

- prix: prix lie a une configuration precise


## Usages extraits par repli

Aucun marqueur d'usage explicite (« s'adresse aux », « cible les »,
« idéal pour »…) n'a été trouvé : l'extraction retombe sur les 8 premiers
mots de la description. À relire si l'usage compte pour la question.

- `15734` — iPhone 16 Pro Max
- `39572` — Google Pixel 9 Pro
- `60347` — Xiaomi 14T Pro
- `94582` — iPhone 16
- `41639` — Samsung Galaxy A55 5G
- `72046` — OnePlus 12
- `29465` — Google Pixel 9a
- `70294` — Xiaomi Redmi Note 13 Pro+

## Rappel

Les questions du jeu d'évaluation sont **rédigées à la main**. Ce fichier
sert uniquement à repérer les produits et leurs `id` ; il ne remplace pas la
lecture des descriptions complètes dans `data/catalogue.json`.

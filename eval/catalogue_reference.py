#!/usr/bin/env python3
"""
catalogue_reference.py
======================
Construit une FICHE DE RÉFÉRENCE du catalogue, destinée à la rédaction MANUELLE
du jeu d'évaluation (`eval/dataset.json`).

Le catalogue est du texte pur : `{"id", "description"}`, aucun champ structuré.
Ce script extrait donc par REGEX / heuristiques :

  - le nom du produit  (début de description, après l'article)
  - la catégorie       (laptop / téléphone, par score de mots-clés)
  - le prix en euros   (motif "<nombre> euros")
  - l'usage            (8 premiers mots après un marqueur d'usage)

Toute extraction douteuse est signalée (colonne « ? » + section dédiée) pour
être VÉRIFIÉE À LA MAIN. Ce fichier n'est qu'une aide à la lecture : il ne doit
jamais servir de source de vérité automatique pour l'évaluation.

Usage :
    python eval/catalogue_reference.py
    python eval/catalogue_reference.py --json      # dump machine-lisible
"""

import argparse
import json
import re
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
CHEMIN_CATALOGUE = RACINE / "data" / "catalogue.json"
CHEMIN_MARKDOWN = RACINE / "eval" / "catalogue_reference.md"


# ==========================================================================
# 1. Nom du produit
# ==========================================================================
# Même heuristique que `frontend/src/utils.js::extraireNom` (volontairement
# dupliquée ici pour garder l'outillage d'éval autonome du frontend).
ARTICLE_TETE = re.compile(r"^(Le|La|Les|Un|Une|L['’])\s*", re.IGNORECASE)


def extraire_nom(description):
    """
    Renvoie (nom, certain, note).

    On retire l'article de tête puis on garde les tokens marque/modèle
    (contenant une majuscule Unicode ou un chiffre), max 6 tokens, et on
    s'arrête au premier mot entièrement en minuscule (souvent le verbe).
    """
    texte = ARTICLE_TETE.sub("", description.strip())
    mots = texte.split()

    nom = []
    for mot in mots:
        if re.search(r"[A-ZÀ-Ý]", mot) or re.search(r"\d", mot):
            nom.append(mot)
            if len(nom) >= 6:
                break
        else:
            break

    resultat = " ".join(nom)
    resultat = re.sub(r"\s*\([^)]*$", "", resultat)   # parenthèse ouverte non fermée
    resultat = re.sub(r"[.,:;]$", "", resultat).strip()

    if not resultat:
        return f"Produit ?", False, "aucun token marque/modele detecte"
    if len(nom) >= 6:
        return resultat, False, "6 tokens atteints : nom peut-etre tronque"
    if len(nom) == 1:
        return resultat, False, "nom reduit a un seul token"
    return resultat, True, ""


# ==========================================================================
# 2. Catégorie (laptop / téléphone)
# ==========================================================================
# Pas de champ catégorie : on score des mots-clés discriminants. Les termes
# communs aux deux familles (ecran, pouces, Go, autonomie...) sont exclus.
MOTS_LAPTOP = [
    r"\blaptop",
    r"\bportable\b",
    r"\bultrabook",
    r"\bclavier",
    r"\btouchpad|\btrackpad",
    r"\bWindows\b",
    r"\bmacOS\b",
    r"\bSSD\b",
    r"\bNVMe\b",
    r"\bDDR[45]X?\b",
    r"\bRTX\b|\bGeForce\b",
    r"\bCore i\d",
    r"\bRyzen\b",
    r"\bchassis\b|\bchâssis\b",
    r"\brefroidissement\b|\bventilateur",
    r"\b2-en-1\b|\bconvertible\b",
    r"\bThunderbolt\b",
    r"\bbureautique\b",
]
MOTS_TELEPHONE = [
    r"\bsmartphone",
    r"\btéléphone",
    r"\biPhone\b",
    r"\bGalaxy\b",
    r"\bPixel\b",
    r"\bAndroid\b",
    r"\biOS\b",
    r"\b5G\b",
    r"\bSnapdragon\b",
    r"\bTensor\b",
    r"\bDimensity\b",
    r"\bMediaTek\b",
    r"\bselfie\b",
    r"\btéléobjectif\b|\bultra grand-angle\b|\bgrand-angle\b",
    r"\bMP\b|\bmégapixels?\b",
    r"\bAMOLED\b|\bOLED 6\.",
    r"\bpliable\b",
    r"\bmAh\b",
    r"\bIP68\b",
    r"\bphotographie\b|\bphoto computationnelle\b",
    r"\bcapteur\b",
    r"\bProMotion\b|\bSuper Retina\b|\bDynamic AMOLED\b",
    r"\bFace ID\b|\beSIM\b|\bdual SIM\b|\bNFC\b",
    r"\bOne UI\b|\bHyperOS\b|\bOxygenOS\b|\bGlyph\b",
    r"\bA1\d Pro?\b|\bExynos\b",
    r"\bcharge (?:rapide|sans fil|ultra)",
    r"\bMagSafe\b|\bflagship",
    r"\bzoom\b|\bstabilisation optique\b",
    r"\bcoloris\b|\btitane\b",
]


def _score(description, motifs):
    """Nombre de motifs distincts présents dans la description."""
    trouves = [m for m in motifs if re.search(m, description, re.IGNORECASE)]
    return len(trouves), trouves


def detecter_categorie(description):
    """Renvoie (categorie, certain, note)."""
    s_lap, _ = _score(description, MOTS_LAPTOP)
    s_tel, _ = _score(description, MOTS_TELEPHONE)

    detail = f"laptop={s_lap} / telephone={s_tel}"

    if s_lap == 0 and s_tel == 0:
        return "?", False, f"aucun mot-cle de categorie ({detail})"

    categorie = "laptop" if s_lap > s_tel else "telephone"
    marge = abs(s_lap - s_tel)
    # Une marge faible = les deux familles de mots-cles s'activent autant.
    if marge <= 1:
        return categorie, False, f"marge faible, a verifier ({detail})"
    return categorie, True, ""


# ==========================================================================
# 3. Prix en euros
# ==========================================================================
# Les prix sont ecrits en clair : "1349 euros", "Prix : 1799 euros",
# "1 599 euros", "1349,00 euros"...
MOTIF_PRIX = re.compile(
    r"(\d{1,3}(?:[   ]\d{3}|\d{0,3})(?:[.,]\d{1,2})?)\s*(?:euros?|€|EUR)\b",
    re.IGNORECASE,
)


def extraire_prix(description):
    """Renvoie (prix_int_ou_None, certain, note)."""
    trouves = MOTIF_PRIX.findall(description)
    if not trouves:
        return None, False, "aucun montant en euros trouve"

    def to_int(brut):
        brut = brut.replace(" ", "").replace(" ", "").replace(" ", "")
        brut = brut.split(",")[0].split(".")[0]
        return int(brut)

    valeurs = [to_int(t) for t in trouves]
    prix = valeurs[0]

    notes = []
    if len(set(valeurs)) > 1:
        notes.append(f"plusieurs montants {valeurs} -> premier retenu")
    # "HT", "a partir de", "des", "version X Go" changent le sens du prix.
    contexte = re.search(
        r".{0,60}?" + str(trouves[0]).replace(".", r"\.") + r"\s*(?:euros?|€|EUR).{0,60}",
        description,
        re.IGNORECASE,
    )
    extrait = contexte.group(0) if contexte else ""
    if re.search(r"\bHT\b", extrait):
        notes.append("prix HT (hors taxes)")
    if re.search(r"à partir de|\bdès\b|prix de départ|de départ", extrait, re.IGNORECASE):
        notes.append("prix d'entree de gamme ('a partir de')")
    if re.search(r"pour (?:la version|\d+)", extrait, re.IGNORECASE):
        notes.append("prix lie a une configuration precise")

    return prix, not notes, " ; ".join(notes)


# ==========================================================================
# 4. Usage
# ==========================================================================
# On cherche un marqueur d'intention, puis on garde les 8 mots qui suivent.
MARQUEURS_USAGE = [
    r"s'adresse (?:exclusivement )?(?:aux?|à)",
    r"cible (?:les|la|le)",
    r"(?:est|reste) (?:le|la|un|une) (?:choix|option|référence|alternative)[^,.]{0,40}? pour",
    r"pensé[e]? pour",
    r"conçu[e]? pour",
    r"destiné[e]? (?:aux?|à)",
    r"idéal(?:e)? pour",
    r"parfait(?:e)? pour",
    r"taillé[e]? pour",
    r"pour (?:les|un|une|le|la) (?:joueurs?|professionnels?|créateurs?|étudiants?|usage|utilisateurs?|développeurs?)",
    r"s'impose comme[^,.]{0,40}? pour",
    r"pour (?:ceux|celles) qui",
]
MOTIFS_USAGE = [re.compile(m, re.IGNORECASE) for m in MARQUEURS_USAGE]
NB_MOTS_USAGE = 8


def extraire_usage(description):
    """Renvoie (usage_8_mots, certain, note)."""
    meilleur = None
    for motif in MOTIFS_USAGE:
        m = motif.search(description)
        if m and (meilleur is None or m.start() < meilleur.start()):
            meilleur = m

    if meilleur is None:
        # Repli : les 8 premiers mots apres le verbe principal de la 1re phrase.
        premiere = description.split(".")[0]
        mots = premiere.split()[:NB_MOTS_USAGE]
        return " ".join(mots), False, "aucun marqueur d'usage -> repli 1re phrase"

    suite = description[meilleur.start():]
    mots = re.split(r"\s+", suite.strip())[:NB_MOTS_USAGE]
    usage = " ".join(mots).rstrip(".,;:")
    return usage, True, ""


# ==========================================================================
# Assemblage
# ==========================================================================
def analyser(produits):
    lignes = []
    for p in produits:
        desc = p.get("description", "") or ""
        nom, nom_ok, nom_note = extraire_nom(desc)
        cat, cat_ok, cat_note = detecter_categorie(desc)
        prix, prix_ok, prix_note = extraire_prix(desc)
        usage, usage_ok, usage_note = extraire_usage(desc)

        # Le drapeau "a verifier" ne porte que sur nom / categorie / prix :
        # l'usage est informatif (on indique juste la strategie d'extraction).
        alertes = []
        for champ, note in (("nom", nom_note), ("categorie", cat_note),
                            ("prix", prix_note)):
            if note:
                alertes.append(f"{champ}: {note}")
        infos = [f"usage: {usage_note}"] if usage_note else []

        lignes.append({
            "id": p.get("id"),
            "nom": nom,
            "categorie": cat,
            "prix_euros": prix,
            "usage_8_mots": usage,
            "certain": nom_ok and cat_ok and prix_ok,
            "usage_sur_marqueur": usage_ok,
            "alertes": alertes,
            "infos": infos,
        })
    return lignes


def _tronquer(texte, n):
    texte = str(texte)
    return texte if len(texte) <= n else texte[: n - 1] + "…"


LARGEURS = {"id": 7, "nom": 30, "categorie": 10, "prix": 8, "usage": 58}


def afficher_terminal(lignes):
    print()
    print("=" * 124)
    print("FICHE DE REFERENCE DU CATALOGUE  (extraction heuristique - a verifier a la main)")
    print("=" * 124)
    entete = (
        f"{'ID':<{LARGEURS['id']}} "
        f"{'NOM':<{LARGEURS['nom']}} "
        f"{'CATEGORIE':<{LARGEURS['categorie']}} "
        f"{'PRIX':>{LARGEURS['prix']}} "
        f"{'?':<2} "
        f"{'USAGE (8 premiers mots)':<{LARGEURS['usage']}}"
    )
    print(entete)
    print("-" * 124)
    for l in lignes:
        prix = f"{l['prix_euros']} €" if l["prix_euros"] is not None else "?"
        marque = "!!" if not l["certain"] else "  "
        print(
            f"{l['id']:<{LARGEURS['id']}} "
            f"{_tronquer(l['nom'], LARGEURS['nom']):<{LARGEURS['nom']}} "
            f"{l['categorie']:<{LARGEURS['categorie']}} "
            f"{prix:>{LARGEURS['prix']}} "
            f"{marque:<2} "
            f"{_tronquer(l['usage_8_mots'], LARGEURS['usage']):<{LARGEURS['usage']}}"
        )
    print("-" * 124)

    douteux = [l for l in lignes if not l["certain"]]
    nb_lap = sum(1 for l in lignes if l["categorie"] == "laptop")
    nb_tel = sum(1 for l in lignes if l["categorie"] == "telephone")
    prix_connus = [l["prix_euros"] for l in lignes if l["prix_euros"] is not None]

    print(f"{len(lignes)} produits | laptop={nb_lap} telephone={nb_tel} "
          f"inconnu={len(lignes) - nb_lap - nb_tel}")
    if prix_connus:
        print(f"prix : min={min(prix_connus)} €  max={max(prix_connus)} €  "
              f"mediane={sorted(prix_connus)[len(prix_connus) // 2]} €")
    print()

    if douteux:
        print("!! EXTRACTIONS A VERIFIER A LA MAIN "
              f"({len(douteux)} produit(s)) :")
        for l in douteux:
            print(f"  - {l['id']} ({l['nom']})")
            for a in l["alertes"]:
                print(f"      . {a}")
        print()
    else:
        print("Aucune extraction douteuse detectee (verifier tout de meme par echantillonnage).")
        print()


def ecrire_markdown(lignes, chemin):
    douteux = [l for l in lignes if not l["certain"]]
    nb_lap = sum(1 for l in lignes if l["categorie"] == "laptop")
    nb_tel = sum(1 for l in lignes if l["categorie"] == "telephone")
    prix_connus = [l["prix_euros"] for l in lignes if l["prix_euros"] is not None]

    out = []
    out.append("# Fiche de référence du catalogue")
    out.append("")
    out.append("> **Généré par `eval/catalogue_reference.py` — ne pas éditer à la main.**")
    out.append("> Les valeurs ci-dessous sont extraites par regex/heuristiques depuis le")
    out.append("> texte libre des descriptions (le catalogue n'a aucun champ structuré).")
    out.append("> Les lignes marquées **⚠️** doivent être vérifiées manuellement avant")
    out.append("> d'être utilisées pour rédiger `eval/dataset.json`.")
    out.append("")
    out.append(f"- Produits : **{len(lignes)}**")
    out.append(f"- Catégories : **{nb_lap}** laptop · **{nb_tel}** téléphone · "
               f"**{len(lignes) - nb_lap - nb_tel}** indéterminé")
    if prix_connus:
        out.append(f"- Prix : min **{min(prix_connus)} €** · max **{max(prix_connus)} €** · "
                   f"médiane **{sorted(prix_connus)[len(prix_connus) // 2]} €**")
    out.append(f"- Extractions douteuses : **{len(douteux)}**")
    out.append("")
    out.append("## Tableau")
    out.append("")
    out.append("| ID | Nom | Catégorie | Prix (€) | ⚠️ | Usage (8 premiers mots) |")
    out.append("| --- | --- | --- | ---: | :-: | --- |")
    for l in lignes:
        prix = l["prix_euros"] if l["prix_euros"] is not None else "?"
        marque = "⚠️" if not l["certain"] else ""
        usage = l["usage_8_mots"].replace("|", "\\|")
        out.append(f"| `{l['id']}` | {l['nom']} | {l['categorie']} | {prix} | {marque} | {usage} |")
    out.append("")
    out.append("## À vérifier à la main")
    out.append("")
    if not douteux:
        out.append("_Aucune extraction signalée comme douteuse._ "
                   "(Contrôler quand même quelques lignes au hasard.)")
    else:
        for l in douteux:
            out.append(f"### `{l['id']}` — {l['nom']}")
            out.append("")
            for a in l["alertes"]:
                out.append(f"- {a}")
            out.append("")
    out.append("")
    replis = [l for l in lignes if not l["usage_sur_marqueur"]]
    out.append("## Usages extraits par repli")
    out.append("")
    if not replis:
        out.append("_Tous les usages viennent d'un marqueur explicite._")
    else:
        out.append("Aucun marqueur d'usage explicite (« s'adresse aux », « cible les »,")
        out.append("« idéal pour »…) n'a été trouvé : l'extraction retombe sur les 8 premiers")
        out.append("mots de la description. À relire si l'usage compte pour la question.")
        out.append("")
        for l in replis:
            out.append(f"- `{l['id']}` — {l['nom']}")
    out.append("")
    out.append("## Rappel")
    out.append("")
    out.append("Les questions du jeu d'évaluation sont **rédigées à la main**. Ce fichier")
    out.append("sert uniquement à repérer les produits et leurs `id` ; il ne remplace pas la")
    out.append("lecture des descriptions complètes dans `data/catalogue.json`.")
    out.append("")

    chemin.write_text("\n".join(out), encoding="utf-8")


def main():
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--json", action="store_true",
                         help="affiche le resultat en JSON (pas de markdown)")
    args = parseur.parse_args()

    if not CHEMIN_CATALOGUE.exists():
        print(f"ERREUR : catalogue introuvable : {CHEMIN_CATALOGUE}", file=sys.stderr)
        return 1

    produits = json.loads(CHEMIN_CATALOGUE.read_text(encoding="utf-8"))
    lignes = analyser(produits)

    if args.json:
        print(json.dumps(lignes, ensure_ascii=False, indent=2))
        return 0

    afficher_terminal(lignes)
    ecrire_markdown(lignes, CHEMIN_MARKDOWN)
    print(f"Markdown ecrit : {CHEMIN_MARKDOWN.relative_to(RACINE)}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())

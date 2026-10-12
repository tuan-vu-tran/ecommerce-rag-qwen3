"""
test_stream_parsing.py
======================
Tests des fonctions PURES de découpage du flux (aucun appel Ollama) :

  - `decouper_flux_modele(tokens, ids_valides)` : côté producteur, transforme
    les tokens bruts du modèle en flux propre (texte, puis marqueur + JSON) ;
  - `separer_texte_et_produits(flux)` : côté consommateur, re-sépare un flux
    (chaîne ou itérable de chunks) en (texte, produits).
"""

import json

from rag_pipeline import (
    MARQUEUR_PRODUITS,
    decouper_flux_modele,
    separer_texte_et_produits,
)

IDS = {"48213", "72046"}


def _emettre(tokens, ids_valides=IDS):
    """Consomme le générateur et renvoie le flux complet sous forme de chaîne."""
    return "".join(decouper_flux_modele(tokens, ids_valides))


# --------------------------------------------------------------------------
# Flux avec marqueur et JSON valide
# --------------------------------------------------------------------------
def test_marqueur_et_json_valide_sont_separes():
    tokens = [
        "Voici ma recommandation.\n",
        MARQUEUR_PRODUITS,
        '\n[{"id": "48213", "raison": "bon rapport qualité/prix"}]',
    ]
    flux = _emettre(tokens)

    texte, produits = separer_texte_et_produits(flux)
    assert texte == "Voici ma recommandation."
    assert produits == [{"id": "48213", "raison": "bon rapport qualité/prix"}]
    # Le backend ne doit laisser passer qu'UN seul marqueur.
    assert flux.count(MARQUEUR_PRODUITS) == 1


def test_ids_hors_candidats_sont_filtres():
    """Filet anti-hallucination : un id inventé est retiré du bloc produits."""
    tokens = [
        "Mon conseil.",
        "\n" + MARQUEUR_PRODUITS + "\n",
        '[{"id": "99999", "raison": "inventé"}, {"id": "72046", "raison": "ok"}]',
    ]
    _, produits = separer_texte_et_produits(_emettre(tokens))
    assert produits == [{"id": "72046", "raison": "ok"}]


# --------------------------------------------------------------------------
# JSON mal formé
# --------------------------------------------------------------------------
def test_json_mal_forme_ne_plante_pas_et_donne_liste_vide():
    tokens = [
        "Texte de réponse.",
        "\n" + MARQUEUR_PRODUITS + "\n",
        '[{"id": "48213", "raison": ',   # JSON tronqué
    ]
    flux = _emettre(tokens)

    texte, produits = separer_texte_et_produits(flux)
    assert texte == "Texte de réponse."
    assert produits == []


def test_bloc_produits_sans_tableau_json():
    tokens = ["Texte.", "\n" + MARQUEUR_PRODUITS + "\n", "aucun produit"]
    texte, produits = separer_texte_et_produits(_emettre(tokens))
    assert texte == "Texte."
    assert produits == []


def test_separer_tolere_un_json_casse_en_entree_directe():
    """`separer_texte_et_produits` ne lève jamais, même sur un flux abîmé."""
    flux = "Texte.\n" + MARQUEUR_PRODUITS + "\n[{ceci n'est pas du JSON}]"
    assert separer_texte_et_produits(flux) == ("Texte.", [])


# --------------------------------------------------------------------------
# Flux sans marqueur
# --------------------------------------------------------------------------
def test_sans_marqueur_tout_le_texte_est_renvoye():
    tokens = ["Le modèle ", "a oublié ", "le marqueur."]
    flux = _emettre(tokens)

    texte, produits = separer_texte_et_produits(flux)
    assert texte == "Le modèle a oublié le marqueur."
    assert produits == []
    # Le backend ajoute quand même SON marqueur + un JSON vide valide.
    assert flux.endswith(MARQUEUR_PRODUITS + "\n[]")


def test_separer_sans_marqueur_sur_une_chaine_brute():
    texte, produits = separer_texte_et_produits("Juste du texte, rien d'autre.")
    assert texte == "Juste du texte, rien d'autre."
    assert produits == []


# --------------------------------------------------------------------------
# Marqueur coupé entre deux chunks
# --------------------------------------------------------------------------
def test_marqueur_coupe_entre_deux_chunks_est_reconstitue():
    """Le marqueur arrive en 3 morceaux : il ne doit JAMAIS fuiter dans le texte."""
    tokens = ["Mon conseil final.", "\n---PRO", "DUITS", "---\n", '[{"id": "48213"}]']
    morceaux = list(decouper_flux_modele(tokens, IDS))

    # Aucun fragment de texte diffusé ne contient de bout de marqueur.
    texte_diffuse = "".join(morceaux).partition(MARQUEUR_PRODUITS)[0]
    assert "---PRO" not in texte_diffuse

    texte, produits = separer_texte_et_produits(morceaux)
    assert texte == "Mon conseil final."
    assert produits == [{"id": "48213", "raison": ""}]


def test_marqueur_coupe_caractere_par_caractere():
    """Cas extrême : un token = un caractère."""
    complet = ("Réponse courte." + "\n" + MARQUEUR_PRODUITS + "\n"
               + '[{"id": "72046", "raison": "pas cher"}]')
    texte, produits = separer_texte_et_produits(_emettre(list(complet)))
    assert texte == "Réponse courte."
    assert produits == [{"id": "72046", "raison": "pas cher"}]


def test_tokens_vides_sont_ignores():
    tokens = ["Texte", "", None, " suite.", "\n" + MARQUEUR_PRODUITS + "\n", "[]"]
    texte, produits = separer_texte_et_produits(_emettre(tokens))
    assert texte == "Texte suite."
    assert produits == []


def test_json_final_est_toujours_valide():
    """Quoi qu'émette le modèle, le bloc final du flux reste du JSON parsable."""
    flux = _emettre(["bla", "\n" + MARQUEUR_PRODUITS + "\n", "{pas une liste}"])
    bloc = flux.partition(MARQUEUR_PRODUITS)[2]
    assert json.loads(bloc.strip()) == []

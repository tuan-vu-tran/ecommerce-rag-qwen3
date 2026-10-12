"""
test_catalogue.py
=================
Garde-fou sur les DONNÉES (data/catalogue.json) : format "texte pur", id
uniques, descriptions non vides. Pure lecture de fichier, aucune dépendance.
"""


def test_catalogue_contient_30_produits(catalogue):
    assert isinstance(catalogue, list)
    assert len(catalogue) == 30


def test_chaque_produit_a_un_id_et_une_description(catalogue):
    for produit in catalogue:
        assert set(produit) == {"id", "description"}, (
            f"Champs inattendus pour {produit.get('id')!r} : le catalogue est "
            "en texte pur (id + description uniquement)."
        )


def test_les_ids_sont_uniques(catalogue):
    ids = [str(p["id"]) for p in catalogue]
    doublons = {i for i in ids if ids.count(i) > 1}
    assert not doublons, f"id dupliqués : {sorted(doublons)}"


def test_les_ids_sont_non_vides(catalogue):
    for produit in catalogue:
        assert str(produit["id"]).strip(), "un produit a un id vide"


def test_les_descriptions_sont_non_vides(catalogue):
    for produit in catalogue:
        description = produit["description"]
        assert isinstance(description, str)
        assert description.strip(), f"description vide pour l'id {produit['id']}"
        # Une description utile fait plus qu'un mot : c'est la seule source
        # d'information du RAG (prix, specs, usages).
        assert len(description.split()) >= 10, (
            f"description suspecte (trop courte) pour l'id {produit['id']}"
        )

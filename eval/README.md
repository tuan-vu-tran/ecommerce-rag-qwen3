# Jeu d'évaluation

dataset.json contient 40 questions étiquetées (7 types : precise, vague, situational,
followup, out_of_scope, not_in_catalogue, injection).

Brouillon rédigé avec l'aide d'un assistant IA, puis relu et retravaillé à la main.
Étiquettes (expected_ids, forbidden_ids) vérifiées contre les prix et caractéristiques du catalogue.
Split : 30 questions dev pour ajuster le système, 10 questions test mesurées une seule fois à la fin.

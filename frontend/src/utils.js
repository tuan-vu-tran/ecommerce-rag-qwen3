// Le catalogue ne contient qu'un id + une description (RAG texte pur).
// On extrait un "nom" lisible depuis le début de la description.
//
// Heuristique : les descriptions commencent par un article (Le/La/L'/Les...)
// suivi du nom du produit (mots capitalisés + numéros de modèle), puis d'un
// verbe en minuscule. Ex :
//   "Le MacBook Air M3 redéfinit..."      -> "MacBook Air M3"
//   "L'iPhone 16 Pro Max représente..."   -> "iPhone 16 Pro Max"
//   "L'ASUS ProArt Studiobook 16 s'adresse" -> "ASUS ProArt Studiobook 16"
export function extraireNom(description, fallbackId) {
  if (!description) return `Produit ${fallbackId}`;

  // On retire l'article de tête (Le, La, Les, Un, Une, L')
  let texte = description.trim().replace(/^(Le|La|Les|Un|Une|L['’])\s*/i, "");

  const mots = texte.split(/\s+/);
  const nom = [];
  for (const mot of mots) {
    // \p{Lu} = vraie lettre majuscule Unicode (capte "iPhone" via le P, sans
    // confondre avec les minuscules accentuées é/è qu'un range A-Z…Ÿ inclurait).
    const contientMajuscule = /\p{Lu}/u.test(mot);
    const contientChiffre = /\d/.test(mot);
    // On garde les mots de marque/modèle (majuscule ou chiffre).
    if (contientMajuscule || contientChiffre) {
      nom.push(mot);
      // On limite à 6 tokens pour éviter les noms à rallonge.
      if (nom.length >= 6) break;
    } else {
      // Premier mot en minuscule (souvent un verbe) -> fin du nom.
      break;
    }
  }

  const resultat = nom
    .join(" ")
    .replace(/\s*\([^)]*$/, "") // retire une parenthèse ouverte non fermée ("(4e")
    .replace(/[.,:;]$/, "");
  return resultat || `Produit ${fallbackId}`;
}

// Renvoie un court extrait (résumé) de la description pour les cartes.
export function extraireResume(description, longueur = 120) {
  if (!description) return "";
  const texte = description.trim();
  if (texte.length <= longueur) return texte;
  return texte.slice(0, longueur).trimEnd() + "…";
}

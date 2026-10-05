// Petit client HTTP centralisé pour parler au backend FastAPI.
// L'URL vient de .env (VITE_API_URL) pour faciliter le passage en prod.
const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

// GET /produits -> liste des 30 produits (id + description)
export async function getProduits() {
  const res = await fetch(`${API_URL}/produits`);
  if (!res.ok) throw new Error("Impossible de charger le catalogue.");
  return res.json();
}

// GET /produits/:id -> un produit, ou une erreur (404 si introuvable)
export async function getProduit(id) {
  const res = await fetch(`${API_URL}/produits/${id}`);
  if (res.status === 404) {
    const err = new Error("Produit introuvable.");
    err.status = 404;
    throw err;
  }
  if (!res.ok) throw new Error("Erreur lors du chargement du produit.");
  return res.json();
}

// Marqueur qui, dans le flux /chat, sépare le TEXTE de réponse du bloc JSON
// des produits recommandés (voir backend/rag_pipeline.py).
const MARQUEUR_PRODUITS = "---PRODUITS---";

// Renvoie la portion de `complet` située AVANT le marqueur. Si le marqueur n'est
// pas (encore) présent en entier, on retire une éventuelle amorce en fin de
// chaîne (ex : "…---PRODU") pour ne pas l'afficher pendant le streaming.
function texteAvantMarqueur(complet) {
  const idx = complet.indexOf(MARQUEUR_PRODUITS);
  if (idx !== -1) return complet.slice(0, idx);
  for (let n = MARQUEUR_PRODUITS.length - 1; n > 0; n--) {
    if (complet.endsWith(MARQUEUR_PRODUITS.slice(0, n))) {
      return complet.slice(0, -n);
    }
  }
  return complet;
}

// POST /chat -> réponse du pipeline RAG en STREAMING.
// Le flux contient : le texte de réponse, puis "---PRODUITS---", puis le JSON
// des produits recommandés.
//   - `onTexte(texte)` est appelé au fil de l'eau avec le TEXTE cumulatif
//     (avant le marqueur), pour un affichage progressif.
//   - la promesse résout { reponse_texte, produits_recommandes } une fois le
//     flux terminé.
// historique : [{ role: "user" | "assistant", content: "..." }]
export async function postChatStream(question, historique, onTexte) {
  const res = await fetch(`${API_URL}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, historique }),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || "L'assistant est momentanément indisponible.");
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let complet = "";

  // Lecture du flux morceau par morceau.
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    complet += decoder.decode(value, { stream: true });
    onTexte?.(texteAvantMarqueur(complet));
  }
  complet += decoder.decode(); // vide le buffer du décodeur

  // Séparation finale : texte / bloc produits.
  const idx = complet.indexOf(MARQUEUR_PRODUITS);
  const reponseTexte = (idx === -1 ? complet : complet.slice(0, idx)).trim();

  let produitsRecommandes = [];
  if (idx !== -1) {
    const apres = complet.slice(idx + MARQUEUR_PRODUITS.length).trim();
    try {
      produitsRecommandes = JSON.parse(apres);
    } catch {
      produitsRecommandes = []; // JSON produits cassé -> pas de reco, pas de crash
    }
  }

  onTexte?.(reponseTexte); // texte final propre (sans amorce de marqueur)
  return {
    reponse_texte: reponseTexte,
    produits_recommandes: Array.isArray(produitsRecommandes) ? produitsRecommandes : [],
  };
}

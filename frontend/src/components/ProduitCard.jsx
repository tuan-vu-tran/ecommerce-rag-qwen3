import { Link } from "react-router-dom";
import { extraireNom, extraireResume } from "../utils";

// Carte produit réutilisable.
// - Dans le catalogue : variante "grande" (avec résumé).
// - Dans le chat : variante "compacte" (mini-carte + raison de la reco).
//
// Props :
//   produit  : { id, description }
//   raison   : (optionnel) justification de la recommandation (contexte chat)
//   compact  : (optionnel) affichage réduit pour le widget de chat
export default function ProduitCard({ produit, raison, compact = false }) {
  const nom = extraireNom(produit.description, produit.id);

  if (compact) {
    return (
      <Link
        to={`/produit/${produit.id}`}
        className="block rounded-lg border border-slate-200 bg-white p-3 transition hover:border-indigo-400 hover:shadow-sm"
      >
        <div className="flex items-start justify-between gap-2">
          <span className="font-medium text-slate-800">{nom}</span>
          <span className="shrink-0 text-xs text-indigo-600">Voir →</span>
        </div>
        {raison && <p className="mt-1 text-sm text-slate-500">{raison}</p>}
      </Link>
    );
  }

  return (
    <Link
      to={`/produit/${produit.id}`}
      className="flex h-full flex-col rounded-xl border border-slate-200 bg-white p-5 transition hover:-translate-y-0.5 hover:border-indigo-400 hover:shadow-md"
    >
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-lg font-semibold text-slate-900">{nom}</h3>
        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-mono text-slate-500">
          #{produit.id}
        </span>
      </div>
      <p className="flex-1 text-sm leading-relaxed text-slate-600">
        {extraireResume(produit.description)}
      </p>
      <span className="mt-4 text-sm font-medium text-indigo-600">
        Voir la fiche →
      </span>
    </Link>
  );
}

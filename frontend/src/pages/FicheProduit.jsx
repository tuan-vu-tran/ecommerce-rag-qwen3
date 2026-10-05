import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getProduit } from "../api";
import { extraireNom } from "../utils";

// Page fiche produit (/produit/:id).
export default function FicheProduit() {
  const { id } = useParams();
  const [produit, setProduit] = useState(null);
  const [chargement, setChargement] = useState(true);
  const [introuvable, setIntrouvable] = useState(false);
  const [erreur, setErreur] = useState(null);

  useEffect(() => {
    setChargement(true);
    setIntrouvable(false);
    setErreur(null);
    getProduit(id)
      .then(setProduit)
      .catch((err) => {
        if (err.status === 404) setIntrouvable(true);
        else setErreur(err.message);
      })
      .finally(() => setChargement(false));
  }, [id]);

  return (
    <div className="mx-auto max-w-3xl px-4 py-8">
      <Link
        to="/"
        className="mb-6 inline-flex items-center gap-1 text-sm font-medium text-indigo-600 hover:text-indigo-700"
      >
        ← Retour au catalogue
      </Link>

      {chargement && <p className="text-slate-500">Chargement…</p>}

      {/* Cas produit introuvable (404 de l'API) géré proprement */}
      {introuvable && (
        <div className="rounded-xl border border-slate-200 bg-white p-8 text-center">
          <p className="text-5xl">🔍</p>
          <h1 className="mt-4 text-xl font-semibold text-slate-900">
            Produit introuvable
          </h1>
          <p className="mt-2 text-slate-500">
            Aucun produit ne correspond à l'identifiant «&nbsp;{id}&nbsp;».
          </p>
          <Link
            to="/"
            className="mt-6 inline-block rounded-full bg-indigo-600 px-5 py-2 text-sm font-medium text-white hover:bg-indigo-700"
          >
            Revenir au catalogue
          </Link>
        </div>
      )}

      {erreur && (
        <div className="rounded-lg bg-red-50 p-4 text-red-600">{erreur}</div>
      )}

      {produit && (
        <article className="rounded-xl border border-slate-200 bg-white p-8">
          <div className="mb-4 flex items-center justify-between">
            <h1 className="text-2xl font-bold text-slate-900">
              {extraireNom(produit.description, produit.id)}
            </h1>
            <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-mono text-slate-500">
              #{produit.id}
            </span>
          </div>
          <p className="whitespace-pre-line text-[15px] leading-relaxed text-slate-700">
            {produit.description}
          </p>
        </article>
      )}
    </div>
  );
}

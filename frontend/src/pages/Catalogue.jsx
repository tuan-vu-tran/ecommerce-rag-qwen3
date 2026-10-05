import { useEffect, useState } from "react";
import { getProduits } from "../api";
import ProduitCard from "../components/ProduitCard";

// Page d'accueil (/) : grille des 30 produits.
export default function Catalogue() {
  const [produits, setProduits] = useState([]);
  const [chargement, setChargement] = useState(true);
  const [erreur, setErreur] = useState(null);

  useEffect(() => {
    getProduits()
      .then(setProduits)
      .catch((err) => setErreur(err.message))
      .finally(() => setChargement(false));
  }, []);

  return (
    <div className="mx-auto max-w-6xl px-4 py-8">
      <header className="mb-8">
        <h1 className="text-3xl font-bold tracking-tight text-slate-900">
          Notre catalogue
        </h1>
        <p className="mt-1 text-slate-500">
          {produits.length > 0
            ? `${produits.length} produits disponibles — ou demandez conseil à notre assistant en bas à droite.`
            : "Ordinateurs, smartphones et high-tech sélectionnés pour vous."}
        </p>
      </header>

      {chargement && <p className="text-slate-500">Chargement du catalogue…</p>}

      {erreur && (
        <div className="rounded-lg bg-red-50 p-4 text-red-600">
          {erreur} — vérifiez que l'API tourne sur le port 8000.
        </div>
      )}

      {!chargement && !erreur && (
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {produits.map((p) => (
            <ProduitCard key={p.id} produit={p} />
          ))}
        </div>
      )}
    </div>
  );
}

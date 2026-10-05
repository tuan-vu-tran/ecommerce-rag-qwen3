import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import { getProduits, postChatStream } from "../api";
import { extraireNom } from "../utils";

// Styles Tailwind appliqués aux éléments Markdown rendus par ReactMarkdown,
// pour rester cohérent avec le reste de la bulle de chat.
const COMPOSANTS_MD = {
  p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
  strong: ({ children }) => (
    <strong className="font-semibold text-slate-900">{children}</strong>
  ),
  em: ({ children }) => <em className="italic">{children}</em>,
  ul: ({ children }) => (
    <ul className="mb-2 list-disc space-y-0.5 pl-4 last:mb-0">{children}</ul>
  ),
  ol: ({ children }) => (
    <ol className="mb-2 list-decimal space-y-0.5 pl-4 last:mb-0">{children}</ol>
  ),
  li: ({ children }) => <li className="leading-snug">{children}</li>,
  a: ({ children, href }) => (
    <a href={href} className="text-indigo-600 underline">{children}</a>
  ),
  code: ({ children }) => (
    <code className="rounded bg-slate-100 px-1 py-0.5 text-xs">{children}</code>
  ),
};

// Widget de chat flottant, présent sur toutes les pages (monté dans App).
// - Bulle en bas à droite qui ouvre/ferme le panneau.
// - Conserve l'historique de conversation dans le state React et le renvoie
//   à l'API à chaque message (contexte conversationnel).
// - Affiche les produits recommandés en mini-cartes cliquables vers /produit/:id.
export default function ChatWidget() {
  const [ouvert, setOuvert] = useState(false);
  const [messages, setMessages] = useState([
    {
      role: "assistant",
      content:
        "Bonjour ! Décrivez ce que vous cherchez (usage, budget, préférences) et je vous conseille un produit.",
      produits: [],
    },
  ]);
  const [saisie, setSaisie] = useState("");
  const [chargement, setChargement] = useState(false);
  const [erreur, setErreur] = useState(null);

  // Table id -> produit, pour retrouver le nom/description des recommandations.
  const [catalogue, setCatalogue] = useState({});
  const finRef = useRef(null);

  // Charge le catalogue une seule fois (pour nommer les produits recommandés).
  useEffect(() => {
    getProduits()
      .then((liste) => {
        const map = {};
        for (const p of liste) map[String(p.id)] = p;
        setCatalogue(map);
      })
      .catch(() => setCatalogue({}));
  }, []);

  // Auto-scroll vers le dernier message.
  useEffect(() => {
    finRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, chargement, ouvert]);

  async function envoyer(e) {
    e.preventDefault();
    const question = saisie.trim();
    if (!question || chargement) return;

    setErreur(null);
    setSaisie("");

    // On ajoute le message utilisateur à l'affichage.
    const messagesAvecUser = [...messages, { role: "user", content: question, produits: [] }];
    setMessages(messagesAvecUser);
    setChargement(true);

    // Historique envoyé à l'API : uniquement {role, content} (sans les produits).
    const historique = messagesAvecUser.map((m) => ({
      role: m.role,
      content: m.content,
    }));

    // Message assistant vide qu'on remplit au fil du stream. `streaming: true`
    // tant que le flux n'est pas terminé -> on affiche le texte brut pendant ce
    // temps (Markdown potentiellement incomplet), puis on bascule sur le rendu
    // Markdown une fois le stream fini.
    setMessages((prev) => [
      ...prev,
      { role: "assistant", content: "", produits: [], streaming: true },
    ]);

    // Remplace le contenu du dernier message (l'assistant en cours) sans toucher
    // aux précédents.
    const majDernier = (champs) =>
      setMessages((prev) => {
        const copie = [...prev];
        copie[copie.length - 1] = { ...copie[copie.length - 1], ...champs };
        return copie;
      });

    try {
      const data = await postChatStream(question, historique, (texte) => {
        // Dès le premier token, on masque l'indicateur "…" et on affiche le texte.
        setChargement(false);
        majDernier({ content: texte });
      });
      majDernier({
        content: data.reponse_texte,
        produits: data.produits_recommandes || [],
        streaming: false, // stream terminé -> rendu Markdown
      });
    } catch (err) {
      // On retire la bulle assistant vide et on affiche l'erreur.
      setMessages((prev) => {
        const copie = [...prev];
        const dernier = copie[copie.length - 1];
        if (dernier?.role === "assistant" && !dernier.content) copie.pop();
        return copie;
      });
      setErreur(err.message);
    } finally {
      setChargement(false);
    }
  }

  return (
    <>
      {/* Bouton flottant */}
      <button
        onClick={() => setOuvert((v) => !v)}
        className="fixed bottom-5 right-5 z-50 flex h-14 w-14 items-center justify-center rounded-full bg-indigo-600 text-white shadow-lg transition hover:bg-indigo-700"
        aria-label="Ouvrir le chat"
      >
        {ouvert ? (
          <span className="text-2xl leading-none">×</span>
        ) : (
          <span className="text-2xl leading-none">💬</span>
        )}
      </button>

      {/* Panneau de chat */}
      {ouvert && (
        <div className="fixed bottom-24 right-5 z-50 flex h-[32rem] w-[22rem] max-w-[calc(100vw-2.5rem)] flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl">
          {/* En-tête */}
          <div className="bg-indigo-600 px-4 py-3 text-white">
            <p className="font-semibold">Assistant TechConseil</p>
            <p className="text-xs text-indigo-100">Conseil produit personnalisé</p>
          </div>

          {/* Fil de messages */}
          <div className="flex-1 space-y-3 overflow-y-auto bg-slate-50 p-3">
            {messages.map((m, i) => (
              <div key={i}>
                {/* On n'affiche pas de bulle vide (assistant en attente du 1er token). */}
                {m.content && (
                  <div
                    className={
                      m.role === "user"
                        ? "ml-auto max-w-[85%] rounded-2xl rounded-br-sm bg-indigo-600 px-3 py-2 text-sm text-white whitespace-pre-wrap"
                        : "mr-auto max-w-[85%] rounded-2xl rounded-bl-sm bg-white px-3 py-2 text-sm text-slate-700 shadow-sm"
                    }
                  >
                    {/* Assistant + stream terminé -> Markdown ; sinon texte brut
                        (utilisateur, ou assistant en cours de streaming). */}
                    {m.role === "assistant" && !m.streaming ? (
                      <ReactMarkdown components={COMPOSANTS_MD}>
                        {m.content}
                      </ReactMarkdown>
                    ) : (
                      <span className="whitespace-pre-wrap">{m.content}</span>
                    )}
                  </div>
                )}

                {/* Mini-cartes des produits recommandés (assistant) */}
                {m.role === "assistant" && m.produits?.length > 0 && (
                  <div className="mt-2 space-y-2">
                    {m.produits.map((p) => {
                      const produit = catalogue[String(p.id)];
                      const nom = produit
                        ? extraireNom(produit.description, p.id)
                        : `Produit ${p.id}`;
                      return (
                        <Link
                          key={p.id}
                          to={`/produit/${p.id}`}
                          className="block rounded-lg border border-slate-200 bg-white p-2.5 transition hover:border-indigo-400 hover:shadow-sm"
                        >
                          <div className="flex items-center justify-between">
                            <span className="text-sm font-semibold text-slate-800">
                              {nom}
                            </span>
                            <span className="text-xs text-indigo-600">Voir →</span>
                          </div>
                          {p.raison && (
                            <p className="mt-0.5 text-xs leading-snug text-slate-500">
                              {p.raison}
                            </p>
                          )}
                        </Link>
                      );
                    })}
                  </div>
                )}
              </div>
            ))}

            {/* Indicateur de chargement (le RAG peut prendre quelques secondes) */}
            {chargement && (
              <div className="mr-auto flex max-w-[85%] items-center gap-1 rounded-2xl rounded-bl-sm bg-white px-3 py-2.5 shadow-sm">
                <span className="h-2 w-2 animate-bounce rounded-full bg-slate-400 [animation-delay:-0.3s]"></span>
                <span className="h-2 w-2 animate-bounce rounded-full bg-slate-400 [animation-delay:-0.15s]"></span>
                <span className="h-2 w-2 animate-bounce rounded-full bg-slate-400"></span>
              </div>
            )}

            {erreur && (
              <div className="mr-auto max-w-[90%] rounded-lg bg-red-50 px-3 py-2 text-xs text-red-600">
                {erreur}
              </div>
            )}

            <div ref={finRef} />
          </div>

          {/* Zone de saisie */}
          <form onSubmit={envoyer} className="flex items-center gap-2 border-t border-slate-200 p-2">
            <input
              type="text"
              value={saisie}
              onChange={(e) => setSaisie(e.target.value)}
              placeholder="Votre question…"
              disabled={chargement}
              className="flex-1 rounded-full border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500 disabled:opacity-60"
            />
            <button
              type="submit"
              disabled={chargement || !saisie.trim()}
              className="rounded-full bg-indigo-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-indigo-700 disabled:opacity-50"
            >
              Envoyer
            </button>
          </form>
        </div>
      )}
    </>
  );
}

import { Link, Route, Routes } from "react-router-dom";
import Catalogue from "./pages/Catalogue";
import FicheProduit from "./pages/FicheProduit";
import ChatWidget from "./components/ChatWidget";

// Routing + layout global. Le ChatWidget est monté ici -> présent sur TOUTES les pages.
export default function App() {
  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      {/* Barre de navigation */}
      <nav className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
          <Link to="/" className="text-lg font-bold tracking-tight">
            Tech<span className="text-indigo-600">Conseil</span>
          </Link>
          <span className="text-sm text-slate-400">Assistant e-commerce IA</span>
        </div>
      </nav>

      {/* Pages */}
      <main>
        <Routes>
          <Route path="/" element={<Catalogue />} />
          <Route path="/produit/:id" element={<FicheProduit />} />
        </Routes>
      </main>

      {/* Widget de chat flottant, visible partout */}
      <ChatWidget />
    </div>
  );
}

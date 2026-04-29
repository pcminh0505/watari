import { BrowserRouter, Route, Routes } from "react-router";
import { Layout } from "./components/layout/Layout";
import { CardDetailPage } from "./pages/CardDetailPage";
import { CardsPage } from "./pages/CardsPage";
import { CardsSearchPage } from "./pages/CardsSearchPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { SetsPage } from "./pages/SetsPage";

export function App() {
  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<SetsPage />} />
          <Route path="/cards" element={<CardsSearchPage />} />
          <Route path="/sets/:setCode" element={<CardsPage />} />
          <Route path="/sets/:setCode/:localId" element={<CardDetailPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  );
}

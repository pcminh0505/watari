import { RouterProvider, createBrowserRouter, Outlet, ScrollRestoration } from "react-router";
import { Layout } from "./components/layout/Layout";
import { AdminPage } from "./pages/AdminPage";
import { CardDetailPage } from "./pages/CardDetailPage";
import { CardsPage } from "./pages/CardsPage";
import { CardsSearchPage } from "./pages/CardsSearchPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { PokemonPage } from "./pages/PokemonPage";
import { SetsPage } from "./pages/SetsPage";

const router = createBrowserRouter([
  {
    path: "/",
    element: (
      <Layout>
        <ScrollRestoration />
        <Outlet />
      </Layout>
    ),
    children: [
      { index: true, element: <SetsPage /> },
      { path: "cards", element: <CardsSearchPage /> },
      { path: "sets/:setCode", element: <CardsPage /> },
      { path: "sets/:setCode/:localId", element: <CardDetailPage /> },
      { path: "pokemon/:name", element: <PokemonPage /> },
      { path: "admin", element: <AdminPage /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
]);

export function App() {
  return <RouterProvider router={router} />;
}

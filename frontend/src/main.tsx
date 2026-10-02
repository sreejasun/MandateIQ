import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/600.css";
import "@fontsource/source-serif-4/400.css";
import "@fontsource/source-serif-4/600.css";
import "./index.css";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode, Suspense, lazy } from "react";
import { createRoot } from "react-dom/client";
import { Navigate, RouterProvider, createBrowserRouter } from "react-router-dom";

import Shell from "./components/Shell";
import CasePage from "./pages/case/CasePage";
import CasesPage from "./pages/CasesPage";
import NewReviewPage from "./pages/NewReviewPage";
import NotFound from "./pages/NotFound";
import SettingsPage from "./pages/SettingsPage";
import { Loading } from "./components/ui";

// Charts are only needed on Insights, so load that page on demand.
const InsightsPage = lazy(() => import("./pages/InsightsPage"));

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
});

const router = createBrowserRouter([
  {
    element: <Shell />,
    children: [
      { index: true, element: <Navigate to="/cases" replace /> },
      { path: "cases", element: <CasesPage /> },
      { path: "cases/:id", element: <CasePage /> },
      { path: "new", element: <NewReviewPage /> },
      { path: "insights", element: <Suspense fallback={<Loading label="Loading insights" />}><InsightsPage /></Suspense> },
      { path: "settings", element: <SettingsPage /> },
      { path: "*", element: <NotFound /> },
    ],
  },
]);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);

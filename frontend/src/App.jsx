/**
 * App.jsx
 *
 * Application root — defines all routes using React Router v7
 * createBrowserRouter + RouterProvider.
 *
 * Route tree:
 *   /                   → LandingPage
 *   /login              → LoginPage
 *   /register           → RegisterPage
 *   /dashboard          → DashboardPage        (auth required)
 *   /sessions/new       → NewSessionPage       (auth required)
 *   /sessions/:id       → SessionPage          (auth required)
 *   /documents          → DocumentsPage        (auth required)
 *   /documents/upload   → UploadDocumentPage   (auth required)
 *   /documents/:id      → DocumentStatusPage   (auth required)
 *   /forms              → FormsPage
 *   /forms/:id          → FormDetailPage
 *   /admin              → AdminPage            (auth + role required)
 *   *                   → NotFoundPage
 */

import { createBrowserRouter, RouterProvider, Outlet } from "react-router-dom";
import Navbar from "@/components/Navbar";

// Pages (lazy import for code-splitting in production)
import LandingPage from "@/pages/LandingPage";
import LoginPage from "@/pages/LoginPage";
import RegisterPage from "@/pages/RegisterPage";
import DashboardPage from "@/pages/DashboardPage";
import NewSessionPage from "@/pages/NewSessionPage";
import SessionPage from "@/pages/SessionPage";
import DocumentsPage from "@/pages/DocumentsPage";
import UploadDocumentPage from "@/pages/UploadDocumentPage";
import DocumentStatusPage from "@/pages/DocumentStatusPage";
import FormsPage from "@/pages/FormsPage";
import FormDetailPage from "@/pages/FormDetailPage";
import AdminPage from "@/pages/AdminPage";
import NotFoundPage from "@/pages/NotFoundPage";

// ── Root layout (renders Navbar + page outlet) ────────────────────────────────
function RootLayout() {
  return (
    <>
      <Navbar />
      <main>
        <Outlet />
      </main>
    </>
  );
}

// ── Router definition ─────────────────────────────────────────────────────────
const router = createBrowserRouter([
  {
    element: <RootLayout />,
    children: [
      { path: "/", element: <LandingPage /> },
      { path: "/login", element: <LoginPage /> },
      { path: "/register", element: <RegisterPage /> },
      { path: "/dashboard", element: <DashboardPage /> },
      { path: "/sessions/new", element: <NewSessionPage /> },
      { path: "/sessions/:id", element: <SessionPage /> },
      { path: "/documents", element: <DocumentsPage /> },
      { path: "/documents/upload", element: <UploadDocumentPage /> },
      { path: "/documents/:id", element: <DocumentStatusPage /> },
      { path: "/forms", element: <FormsPage /> },
      { path: "/forms/:id", element: <FormDetailPage /> },
      { path: "/admin", element: <AdminPage /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
]);

export default function App() {
  return <RouterProvider router={router} />;
}

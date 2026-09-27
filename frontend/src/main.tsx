import { lazy, StrictMode, Suspense, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, Link, Navigate, RouterProvider } from "react-router-dom";

import "./hooks/useTheme"; // applies the saved theme before first paint
import "./index.css";
import { AuthProvider } from "./auth/AuthContext";
import { AppShell } from "./components/AppShell";
import { GuestOnly, RequireAdmin, RequireAuth } from "./components/guards";
import { ToastProvider } from "./components/Toasts";
import { SkeletonLines } from "./components/ui";
import { LoginPage, RegisterPage } from "./pages/AuthPages";
import { ChatPage } from "./pages/ChatPage";
import { MapperPage } from "./pages/MapperPage";

// Admin pages (and recharts) load on demand, keeping the main bundle small for regular users.
const DocumentsPage = lazy(() => import("./pages/admin/DocumentsPage").then((m) => ({ default: m.DocumentsPage })));
const EvaluationPage = lazy(() => import("./pages/admin/EvaluationPage").then((m) => ({ default: m.EvaluationPage })));
const AnalyticsPage = lazy(() => import("./pages/admin/PlaceholderPages").then((m) => ({ default: m.AnalyticsPage })));

function Lazy({ children }: { children: ReactNode }) {
  return (
    <Suspense
      fallback={
        <div className="mx-auto max-w-5xl p-8">
          <SkeletonLines lines={8} />
        </div>
      }
    >
      {children}
    </Suspense>
  );
}

function NotFound() {
  return (
    <div className="grid h-full place-items-center p-8 text-center">
      <div>
        <p className="font-serif text-6xl font-bold text-saffron-500">404</p>
        <p className="mt-2 text-navy-600 dark:text-navy-300">This page doesn't exist.</p>
        <Link to="/" className="btn-primary mt-6">
          Back to research
        </Link>
      </div>
    </div>
  );
}

const router = createBrowserRouter([
  {
    element: <GuestOnly />,
    children: [
      { path: "/login", element: <LoginPage /> },
      { path: "/register", element: <RegisterPage /> },
    ],
  },
  {
    element: <RequireAuth />,
    children: [
      {
        element: <AppShell />,
        children: [
          { path: "/", element: <ChatPage /> },
          { path: "/mapper", element: <MapperPage /> },
          {
            path: "/admin",
            element: <RequireAdmin />,
            children: [
              { index: true, element: <Navigate to="/admin/documents" replace /> },
              { path: "documents", element: <Lazy><DocumentsPage /></Lazy> },
              { path: "evaluation", element: <Lazy><EvaluationPage /></Lazy> },
              { path: "analytics", element: <Lazy><AnalyticsPage /></Lazy> },
            ],
          },
          { path: "*", element: <NotFound /> },
        ],
      },
    ],
  },
]);

const root = document.getElementById("root");
if (!root) throw new Error("Root element #root not found");

createRoot(root).render(
  <StrictMode>
    <ToastProvider>
      <AuthProvider>
        <RouterProvider router={router} />
      </AuthProvider>
    </ToastProvider>
  </StrictMode>,
);

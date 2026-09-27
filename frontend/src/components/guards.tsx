import { Navigate, Outlet, useLocation } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";
import { Logo, Spinner } from "./ui";

function FullPageLoader() {
  return (
    <div className="grid h-dvh place-items-center">
      <div className="flex flex-col items-center gap-4 text-navy-500 dark:text-navy-300">
        <Logo />
        <Spinner className="size-5" />
      </div>
    </div>
  );
}

/** Signed-in users only; others go to /login and come back afterwards. */
export function RequireAuth() {
  const { state } = useAuth();
  const location = useLocation();
  if (state.status === "loading") return <FullPageLoader />;
  if (state.status === "signed-out") {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  return <Outlet />;
}

export function RequireAdmin() {
  const { user } = useAuth();
  if (user?.role !== "admin") return <Navigate to="/" replace />;
  return <Outlet />;
}

/** Login/register pages: bounce signed-in users to the app. */
export function GuestOnly() {
  const { state } = useAuth();
  if (state.status === "loading") return <FullPageLoader />;
  if (state.status === "signed-in") return <Navigate to="/" replace />;
  return <Outlet />;
}

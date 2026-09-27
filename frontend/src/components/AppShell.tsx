import { ChevronDown, LogOut, Monitor, Moon, Shield, Sun } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";
import { useReadiness } from "../hooks/useReadiness";
import { useTheme } from "../hooks/useTheme";
import { Logo } from "./ui";

const linkClass = ({ isActive }: { isActive: boolean }) =>
  `rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
    isActive
      ? "bg-white/10 text-white"
      : "text-navy-200 hover:bg-white/5 hover:text-white"
  }`;

function ThemeToggle() {
  const { preference, cycle } = useTheme();
  const Icon = preference === "light" ? Sun : preference === "dark" ? Moon : Monitor;
  return (
    <button
      type="button"
      onClick={cycle}
      className="rounded-md p-2 text-navy-200 hover:bg-white/10 hover:text-white"
      aria-label={`Theme: ${preference}. Click to change.`}
      title={`Theme: ${preference}`}
    >
      <Icon className="size-4.5" aria-hidden />
    </button>
  );
}

function ApiStatusDot() {
  const { state } = useReadiness(30_000);
  const ok = state.kind === "success" && state.data.status === "ok";
  const label =
    state.kind === "loading" ? "Checking service status" : ok ? "All services up" : "Service degraded";
  return (
    <span className="flex items-center gap-1.5 text-xs text-navy-300" title={label}>
      <span
        className={`size-2 rounded-full ${
          state.kind === "loading" ? "bg-navy-400" : ok ? "bg-emerald-400" : "bg-red-400"
        }`}
        aria-hidden
      />
      <span className="sr-only">{label}</span>
    </span>
  );
}

function UserMenu() {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (!user) return null;
  const initial = user.email[0]?.toUpperCase() ?? "?";
  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1.5 rounded-md p-1 text-navy-100 hover:bg-white/10"
        aria-haspopup="menu"
        aria-expanded={open}
      >
        <span className="grid size-7 place-items-center rounded-full bg-saffron-500 text-xs font-bold text-navy-950">
          {initial}
        </span>
        <ChevronDown className="size-3.5" aria-hidden />
      </button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 z-40 mt-2 w-60 animate-fade-in rounded-lg border border-navy-100 bg-white p-1 text-sm text-navy-900 shadow-xl dark:border-navy-700 dark:bg-navy-900 dark:text-navy-50"
        >
          <div className="px-3 py-2">
            <p className="truncate font-medium">{user.email}</p>
            <p className="flex items-center gap-1 text-xs text-navy-500 dark:text-navy-300">
              {user.role === "admin" && <Shield className="size-3" aria-hidden />}
              {user.role === "admin" ? "Administrator" : "Member"}
            </p>
          </div>
          <button
            type="button"
            role="menuitem"
            onClick={logout}
            className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left hover:bg-navy-50 dark:hover:bg-navy-800"
          >
            <LogOut className="size-4" aria-hidden /> Sign out
          </button>
        </div>
      )}
    </div>
  );
}

export function AppShell() {
  const { user } = useAuth();
  const location = useLocation();
  const inAdmin = location.pathname.startsWith("/admin");

  return (
    <div className="flex h-dvh flex-col">
      <a
        href="#main"
        className="sr-only z-50 rounded bg-saffron-500 px-3 py-2 text-navy-950 focus:not-sr-only focus:absolute focus:left-3 focus:top-3"
      >
        Skip to content
      </a>
      <header className="shrink-0 bg-navy-900 text-white shadow-md dark:bg-navy-950 dark:shadow-none dark:ring-1 dark:ring-navy-800">
        <div className="flex h-14 items-center gap-3 px-3 sm:px-5">
          <NavLink to="/" className="shrink-0 rounded-md" aria-label="DharaDrishti home">
            <Logo />
          </NavLink>
          <nav aria-label="Main" className="ml-2 flex min-w-0 items-center gap-1 overflow-x-auto">
            <NavLink to="/" end className={linkClass}>
              Research
            </NavLink>
            <NavLink to="/mapper" className={linkClass}>
              IPC → BNS
            </NavLink>
            {user?.role === "admin" && (
              <NavLink to="/admin/documents" className={() => linkClass({ isActive: inAdmin })}>
                Admin
              </NavLink>
            )}
          </nav>
          <div className="ml-auto flex items-center gap-1 sm:gap-2">
            <ApiStatusDot />
            <ThemeToggle />
            <UserMenu />
          </div>
        </div>
        {inAdmin && user?.role === "admin" && (
          <nav aria-label="Admin" className="flex gap-1 overflow-x-auto border-t border-white/10 px-3 py-1.5 sm:px-5">
            <NavLink to="/admin/documents" className={linkClass}>
              Documents
            </NavLink>
            <NavLink to="/admin/evaluation" className={linkClass}>
              Evaluation
            </NavLink>
            <NavLink to="/admin/analytics" className={linkClass}>
              Analytics
            </NavLink>
          </nav>
        )}
      </header>
      <main id="main" className="min-h-0 flex-1">
        <Outlet />
      </main>
    </div>
  );
}

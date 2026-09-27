import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { api, hasRefreshToken, onSessionChange, refreshSession } from "../api/client";
import type { User } from "../types/api";

type AuthState =
  | { status: "loading" }
  | { status: "signed-out" }
  | { status: "signed-in"; user: User };

interface AuthApi {
  state: AuthState;
  user: User | null;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthApi | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ status: "loading" });

  // Restore the session after a reload: refresh token -> new access token -> /me.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!hasRefreshToken() || !(await refreshSession())) {
        if (!cancelled) setState({ status: "signed-out" });
        return;
      }
      try {
        const user = await api.auth.me();
        if (!cancelled) setState({ status: "signed-in", user });
      } catch {
        if (!cancelled) setState({ status: "signed-out" });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // A failed refresh anywhere in the app signs the user out.
  useEffect(
    () =>
      onSessionChange((signedIn) => {
        if (!signedIn) setState({ status: "signed-out" });
      }),
    [],
  );

  const login = useCallback(async (email: string, password: string) => {
    await api.auth.login(email, password);
    setState({ status: "signed-in", user: await api.auth.me() });
  }, []);

  const register = useCallback(
    async (email: string, password: string) => {
      await api.auth.register(email, password);
      await login(email, password);
    },
    [login],
  );

  const logout = useCallback(() => {
    api.auth.logout();
    setState({ status: "signed-out" });
  }, []);

  const value = useMemo<AuthApi>(
    () => ({
      state,
      user: state.status === "signed-in" ? state.user : null,
      login,
      register,
      logout,
    }),
    [state, login, register, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthApi {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside <AuthProvider>");
  return context;
}

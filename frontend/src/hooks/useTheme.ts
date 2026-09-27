import { useCallback, useEffect, useState } from "react";

export type ThemePreference = "light" | "dark" | "system";
const KEY = "dd.theme";

function readPreference(): ThemePreference {
  try {
    const value = localStorage.getItem(KEY);
    if (value === "light" || value === "dark" || value === "system") return value;
  } catch {
    /* storage unavailable */
  }
  return "system";
}

function systemPrefersDark(): boolean {
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;
}

function apply(preference: ThemePreference): void {
  const dark = preference === "dark" || (preference === "system" && systemPrefersDark());
  document.documentElement.classList.toggle("dark", dark);
}

/** Light / dark / system theme, persisted per browser. */
export function useTheme(): { preference: ThemePreference; isDark: boolean; cycle: () => void } {
  const [preference, setPreference] = useState<ThemePreference>(readPreference);
  const [isDark, setIsDark] = useState(() => document.documentElement.classList.contains("dark"));

  useEffect(() => {
    apply(preference);
    setIsDark(document.documentElement.classList.contains("dark"));
    try {
      localStorage.setItem(KEY, preference);
    } catch {
      /* ignore */
    }
    if (preference !== "system") return;
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => {
      apply("system");
      setIsDark(media.matches);
    };
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, [preference]);

  const cycle = useCallback(() => {
    setPreference((p) => (p === "light" ? "dark" : p === "dark" ? "system" : "light"));
  }, []);

  return { preference, isDark, cycle };
}

// Apply before React renders, to avoid a flash of the wrong theme.
apply(readPreference());

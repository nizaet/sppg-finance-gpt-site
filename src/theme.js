import { useEffect, useState } from "react";

export const APP_THEME_KEY = "sppg_app_theme_v1";
const THEME_EVENT = "sppg-app-theme-change";

export function readAppTheme() {
  if (typeof window === "undefined") return "dark";
  const saved = window.localStorage.getItem(APP_THEME_KEY);
  if (saved === "light" || saved === "dark") return saved;
  return window.matchMedia?.("(prefers-color-scheme: dark)")?.matches ? "dark" : "light";
}

export function applyAppTheme(theme = readAppTheme()) {
  if (typeof document === "undefined") return theme;
  const safeTheme = theme === "light" ? "light" : "dark";
  document.documentElement.dataset.appTheme = safeTheme;
  document.documentElement.style.colorScheme = safeTheme;
  return safeTheme;
}

export function setAppTheme(theme) {
  const safeTheme = applyAppTheme(theme);
  window.localStorage.setItem(APP_THEME_KEY, safeTheme);
  window.dispatchEvent(new CustomEvent(THEME_EVENT, { detail: safeTheme }));
  return safeTheme;
}

export function useAppTheme() {
  const [theme, setThemeState] = useState(() => applyAppTheme());
  useEffect(() => {
    const update = (event) => setThemeState(event?.detail || applyAppTheme());
    const syncStorage = (event) => {
      if (!event.key || event.key === APP_THEME_KEY) setThemeState(applyAppTheme());
    };
    window.addEventListener(THEME_EVENT, update);
    window.addEventListener("storage", syncStorage);
    return () => {
      window.removeEventListener(THEME_EVENT, update);
      window.removeEventListener("storage", syncStorage);
    };
  }, []);
  return [theme, (next) => setAppTheme(next)];
}

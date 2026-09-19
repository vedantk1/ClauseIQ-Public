"use client";

import { useCallback } from "react";
import { useAppState } from "../store/appState";
import { nextTheme, THEME_LABELS, type Theme } from "../lib/theme";

export type { Theme } from "../lib/theme";

/** Shared state only: initialization and browser effects belong to the provider. */
export const useTheme = () => {
  const { state: { ui: { theme } }, dispatch } = useAppState();
  const setTheme = useCallback((newTheme: Theme) => {
    dispatch({ type: "UI_SET_THEME", payload: newTheme });
  }, [dispatch]);
  const toggleTheme = useCallback(() => setTheme(nextTheme(theme)), [theme, setTheme]);

  return {
    theme,
    themeLabel: THEME_LABELS[theme],
    nextThemeLabel: THEME_LABELS[nextTheme(theme)],
    toggleTheme,
    setTheme,
  };
};

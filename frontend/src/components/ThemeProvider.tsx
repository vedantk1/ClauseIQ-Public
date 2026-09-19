"use client";

import { useEffect, useState } from "react";
import { useAppState } from "../store/appState";
import { applyTheme, persistTheme, readSavedTheme } from "../lib/theme";

export default function ThemeProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const { state: { ui: { theme } }, dispatch } = useAppState();
  const [initialized, setInitialized] = useState(false);

  useEffect(() => {
    const savedTheme = readSavedTheme();
    dispatch({ type: "UI_SET_THEME", payload: savedTheme });
    applyTheme(savedTheme);
    setInitialized(true);
  }, [dispatch]);

  useEffect(() => {
    // Do not overwrite a saved preference with the server's default on mount.
    if (!initialized) return;
    applyTheme(theme);
    persistTheme(theme);
  }, [theme, initialized]);

  return <>{children}</>;
}

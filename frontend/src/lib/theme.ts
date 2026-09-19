/** The two supported appearance choices; both use dark browser controls. */
export type Theme = "black" | "graphite";

export const DEFAULT_THEME: Theme = "black";
export const THEME_STORAGE_KEY = "clauseiq-theme";
export const THEME_LABELS: Record<Theme, string> = {
  black: "Black",
  graphite: "Graphite",
};

export function normalizeTheme(value: unknown): Theme {
  return value === "graphite" || value === "dark" ? "graphite" : "black";
}

export function nextTheme(theme: Theme): Theme {
  return theme === "black" ? "graphite" : "black";
}

export function readSavedTheme(): Theme {
  try {
    return normalizeTheme(window.localStorage.getItem(THEME_STORAGE_KEY));
  } catch {
    return DEFAULT_THEME;
  }
}

export function persistTheme(theme: Theme): void {
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // A blocked browser store must not prevent an in-session appearance change.
  }
}

export function applyTheme(theme: Theme): void {
  const root = document.documentElement;
  root.setAttribute("data-theme", theme);
  root.classList.add("dark");
  root.classList.remove("light");
  root.style.colorScheme = "dark";
}

// Runs before hydration so a saved Graphite choice does not flash Black. Keep
// this small, dependency-free bootstrap consistent with normalizeTheme (tested).
export const THEME_BOOTSTRAP_SCRIPT = `(function(){var value;try{value=localStorage.getItem("clauseiq-theme")}catch(e){}var root=document.documentElement;root.setAttribute("data-theme",value==="graphite"||value==="dark"?"graphite":"black");root.classList.add("dark");root.classList.remove("light");root.style.colorScheme="dark"})()`;

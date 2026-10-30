export type ThemeMode = "light" | "dark";

const THEME_KEY = "churnce-theme";

export function getStoredTheme(): ThemeMode {
  const raw = window.localStorage.getItem(THEME_KEY);
  if (raw === "light" || raw === "dark") return raw;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function applyTheme(mode: ThemeMode): void {
  document.documentElement.dataset.theme = mode;
  document.documentElement.style.colorScheme = mode;

  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) {
    meta.setAttribute("content", mode === "dark" ? "#071317" : "#FAF2A0");
  }

  window.localStorage.setItem(THEME_KEY, mode);
}

export function initTheme(): void {
  applyTheme(getStoredTheme());
}

export function toggleTheme(): ThemeMode {
  const next: ThemeMode = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  applyTheme(next);
  return next;
}

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

export type Mode = "light" | "dark";
const KEY = "churnce.theme";

interface Ctx { mode: Mode; flip: () => void }
const ThemeCtx = createContext<Ctx>({ mode: "light", flip: () => undefined });

function initial(): Mode {
  try { return localStorage.getItem(KEY) === "dark" ? "dark" : "light"; } catch { return "light"; } // light is the default
}

/** The theme only changes when the person presses the toggle. The choice is remembered per browser. */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<Mode>(initial);
  useEffect(() => {
    document.documentElement.dataset.theme = mode;
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", mode === "dark" ? "#050505" : "#385144");
    try { localStorage.setItem(KEY, mode); } catch { /* storage can be blocked */ }
  }, [mode]);
  const flip = useCallback(() => setMode((m) => (m === "light" ? "dark" : "light")), []);
  const value = useMemo(() => ({ mode, flip }), [mode, flip]);
  return <ThemeCtx.Provider value={value}>{children}</ThemeCtx.Provider>;
}

export const useTheme = () => useContext(ThemeCtx);

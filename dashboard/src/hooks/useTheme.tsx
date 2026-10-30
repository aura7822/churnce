import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

export type Mode = "light" | "dark";

interface Ctx { mode: Mode; flip: () => void }
const ThemeCtx = createContext<Ctx>({ mode: "dark", flip: () => undefined });

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<Mode>("light");

  useEffect(() => {
    document.documentElement.dataset.theme = mode;
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", mode === "dark" ? "#071317" : "#FAF2A0");
  }, [mode]);

  const flip = useCallback(() => {
    setMode((m) => (m === "light" ? "dark" : "light"));
  }, []);

  const value = useMemo(() => ({ mode, flip }), [mode, flip]);
  return <ThemeCtx.Provider value={value}>{children}</ThemeCtx.Provider>;
}

export const useTheme = () => useContext(ThemeCtx);

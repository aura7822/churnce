import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { IconCheck, IconWarn } from "../components/icons";

interface Toast { id: number; kind: "ok" | "err"; text: string }
interface ToastCtx { ok: (t: string) => void; err: (t: string) => void }
const Ctx = createContext<ToastCtx>({ ok: () => {}, err: () => {} });
let seq = 0;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const push = useCallback((kind: Toast["kind"], text: string) => {
    const id = ++seq;
    setItems((x) => [...x.slice(-3), { id, kind, text }]);
    setTimeout(() => setItems((x) => x.filter((t) => t.id !== id)), kind === "err" ? 7000 : 3800);
  }, []);
  const value = useMemo(() => ({ ok: (t: string) => push("ok", t), err: (t: string) => push("err", t) }), [push]);
  return (
    <Ctx.Provider value={value}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className={`toast ${t.kind}`}>
            {t.kind === "ok" ? <IconCheck /> : <IconWarn />}
            <span>{t.text}</span>
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}
export const useToast = () => useContext(Ctx);

import { useEffect } from "react";

/** One delegated listener: every button/chip/scenario gets a click ripple without per-component code. */
export function useRipple() {
  useEffect(() => {
    const on = (e: PointerEvent) => {
      const el = (e.target as HTMLElement | null)?.closest<HTMLElement>("button.btn, button.btn-brutal, button.scenario, button.chip");
      if (!el || (el as HTMLButtonElement).disabled) return;
      const r = el.getBoundingClientRect();
      const d = Math.max(r.width, r.height) * 2;
      const dot = document.createElement("span");
      dot.className = "ripple";
      dot.style.cssText = `width:${d}px;height:${d}px;left:${e.clientX - r.left - d / 2}px;top:${e.clientY - r.top - d / 2}px`;
      if (getComputedStyle(el).position === "static") el.style.position = "relative";
      el.appendChild(dot);
      setTimeout(() => dot.remove(), 650);
    };
    document.addEventListener("pointerdown", on);
    return () => document.removeEventListener("pointerdown", on);
  }, []);
}

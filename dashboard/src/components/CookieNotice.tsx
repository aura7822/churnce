import { useState } from "react";
import { IconCookie } from "./icons";

const KEY = "churnce.cookies";
/** Shown after sign-in until a choice is made. The dashboard itself only uses essential browser storage (sign-in session, theme, panel choices). */
export function CookieNotice() {
  const [choice, setChoice] = useState<string | null>(() => { try { return localStorage.getItem(KEY); } catch { return "skip"; } });
  if (choice) return null;
  const pick = (v: string) => { try { localStorage.setItem(KEY, v); } catch { /* ignore */ } setChoice(v); };
  return (
    <aside className="cookie" role="dialog" aria-label="Cookie notice" aria-live="polite">
      <IconCookie className="cookie-ico" />
      <div className="cookie-copy">
        <b>Cookies and browser storage</b>
        <p>This dashboard stores your sign-in session, theme and a few interface choices in your browser. They are essential, never used for advertising, and never shared with third parties. Captured website data is only collected from sites whose owners gave consent.</p>
      </div>
      <div className="cookie-actions">
        <button type="button" className="btn btn-clay" onClick={() => pick("all")}>Accept</button>
        <button type="button" className="btn btn-ghost" onClick={() => pick("essential")}>Essential only</button>
      </div>
    </aside>
  );
}

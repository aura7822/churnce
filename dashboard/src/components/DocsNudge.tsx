import { useEffect, useState } from "react";
import { IconDocs } from "./icons";

const KEY = "churnce.docs.seen";
const read = () => { try { return localStorage.getItem(KEY) === "1"; } catch { return true; } };

/** A pointer under the "View documentation" button: the first thing a new person is asked to do. It stays until the documentation has been opened once. */
export function DocsNudge({ route }: { route: string }) {
  const [seen, setSeen] = useState(read);
  const [hidden, setHidden] = useState(false);
  useEffect(() => { if (route === "docs") { try { localStorage.setItem(KEY, "1"); } catch { /* ignore */ } setSeen(true); } }, [route]);
  if (seen || hidden) return null;
  return (
    <div className="docs-nudge" role="note">
      <svg className="docs-nudge-arrow" viewBox="0 0 40 46" aria-hidden="true" width="40" height="46">
        <path d="M20 2 L34 18 H25 V44 H15 V18 H6 Z" fill="currentColor" />
      </svg>
      <div className="docs-nudge-body">
        <b><IconDocs /> Start here: read the documentation first</b>
        <p>It explains consent, website IDs and roles, the finance engine, the codebase analyser and how data flows. Five minutes now saves hours later.</p>
        <div className="row" style={{ gap: 8 }}>
          <a href="#/docs" className="btn btn-clay amber">Open the documentation</a>
          <button type="button" className="btn btn-ghost" onClick={() => setHidden(true)}>Later</button>
        </div>
      </div>
    </div>
  );
}

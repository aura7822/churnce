import { useAuth } from "../hooks/useAuth";
import { IconShieldOff } from "./icons";
import { ROLE_LABEL } from "../services/format";

/** Custom 403 page. Shown instead of a section a website-ID session is not allowed to open (for example Backend logs). */
export function Forbidden({ section, detail }: { section: string; detail?: string }) {
  const { me, logout } = useAuth();
  const scope = me?.scope;
  return (
    <div className="forbidden" role="alert">
      <div className="forbidden-orb" aria-hidden="true"><IconShieldOff /></div>
      <div className="eyebrow">Error 403</div>
      <h1>Access denied</h1>
      <p className="forbidden-lede">
        <b>{section}</b> is not available to your role{me ? <> (<b>{ROLE_LABEL[me.user.role]}</b>)</> : null}.
        {scope ? <> Your website-ID session only sees <span className="chip-address">{scope.site_host}</span>, so server-wide logs and settings are not available to it.</> : null}
      </p>
      {detail ? <p className="hint">{detail}</p> : null}
      <div className="row" style={{ justifyContent: "center", gap: 10 }}>
        <a className="btn clay" href="#/overview">Back to overview</a>
        <button type="button" className="btn ghost" onClick={logout}>Sign in with another account</button>
      </div>
    </div>
  );
}

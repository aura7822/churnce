import { useState } from "react";
import type { ReactNode } from "react";

/** Small dependency-free SVG charts. Every chart has direct value labels, a legend where it has >1 series,
 *  and a collapsible data table so no information is colour-only. */
export interface Datum { label: string; value: number; color?: string }
export const SERIES = ["var(--c1)", "var(--c2)", "var(--c3)", "var(--c4)", "var(--c5)", "var(--c6)"];

function DataTable({ data }: { data: Datum[] }) {
  return (
    <details><summary>Data table</summary>
      <table><thead><tr><th>Item</th><th>Value</th></tr></thead><tbody>{data.map((d) => <tr key={d.label}><td>{d.label}</td><td>{d.value}</td></tr>)}</tbody></table>
    </details>
  );
}

export function ChartCard({ title, icon, children }: { title: string; icon: ReactNode; children: ReactNode }) {
  return <div className="chart card"><h4>{icon}{title}</h4>{children}</div>;
}

/** Single-series magnitude: one colour, bars anchored to the baseline. */
export function BarChart({ data, label }: { data: Datum[]; label: string }) {
  const W = 320, H = 170, pad = 26, max = Math.max(1, ...data.map((d) => d.value));
  const bw = (W - pad) / data.length;
  return (
    <>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label}>
        <line className="grid-line" x1={pad} x2={W} y1={20} y2={20} />
        <line className="axis" x1={pad} x2={W} y1={H - 28} y2={H - 28} />
        {data.map((d, i) => {
          const h = (d.value / max) * (H - 28 - 24), x = pad + i * bw + bw * 0.16, w = bw * 0.68;
          return (
            <g key={d.label}>
              <rect className="bar" x={x} y={H - 28 - h} width={w} height={Math.max(h, 1)} fill="var(--bar)" style={{ animationDelay: `${i * 70}ms` }}><title>{`${d.label}: ${d.value}`}</title></rect>
              <text className="val" x={x + w / 2} y={H - 32 - h} textAnchor="middle">{d.value}</text>
              <text x={x + w / 2} y={H - 12} textAnchor="middle">{d.label}</text>
            </g>
          );
        })}
      </svg>
      <DataTable data={data} />
    </>
  );
}

/** Part-to-whole with ≤4 slices, each slice labelled in the legend with its value. */
export function Donut({ data, label }: { data: Datum[]; label: string }) {
  const total = data.reduce((a, d) => a + d.value, 0);
  const R = 52, C = 2 * Math.PI * R;
  let off = 0;
  return (
    <>
      <div className="donut-wrap">
        <svg viewBox="0 0 140 140" role="img" aria-label={label}>
          <circle cx="70" cy="70" r={R} fill="none" stroke="var(--bg-2)" strokeWidth="22" />
          {total > 0 && data.map((d, i) => {
            const len = (d.value / total) * C, el = (
              <circle key={d.label} cx="70" cy="70" r={R} fill="none" stroke={d.color ?? SERIES[i % SERIES.length]} strokeWidth="22" strokeDasharray={`${Math.max(len - 2, 0)} ${C}`} strokeDashoffset={-off} transform="rotate(-90 70 70)"><title>{`${d.label}: ${d.value}`}</title></circle>
            );
            off += len; return el;
          })}
          <text className="val" x="70" y="75" textAnchor="middle" style={{ fontSize: 20 }}>{total}</text>
        </svg>
        <div className="chart-legend" style={{ flexDirection: "column" }}>
          {data.map((d, i) => <span key={d.label}><i style={{ background: d.color ?? SERIES[i % SERIES.length] }} />{d.label} · <b>{d.value}</b></span>)}
        </div>
      </div>
      <DataTable data={data} />
    </>
  );
}

/** Ranked horizontal bars with the value written at the bar end. */
export function HBar({ data, label }: { data: Datum[]; label: string }) {
  const max = Math.max(1, ...data.map((d) => d.value)), rowH = 28, W = 320, lw = 96;
  return (
    <>
      <svg viewBox={`0 0 ${W} ${data.length * rowH + 4}`} role="img" aria-label={label}>
        {data.map((d, i) => {
          const w = (d.value / max) * (W - lw - 40);
          return (
            <g key={d.label} transform={`translate(0 ${i * rowH})`}>
              <text x={0} y={17}>{d.label}</text>
              <rect className="hbar" x={lw} y={4} width={Math.max(w, 1)} height={16} fill="var(--bar)" style={{ animationDelay: `${i * 70}ms` }}><title>{`${d.label}: ${d.value}`}</title></rect>
              <text className="val" x={lw + w + 6} y={17}>{d.value}</text>
            </g>
          );
        })}
      </svg>
      <DataTable data={data} />
    </>
  );
}

// ───────────────────────── time-series ─────────────────────────
export interface LineSeries { name: string; values: (number | null)[]; color?: string; muted?: boolean; dashed?: boolean }
export interface Band { name: string; lo: (number | null)[]; hi: (number | null)[]; color?: string }

function niceMax(v: number): number {
  if (v <= 4) return 4;
  const p = 10 ** Math.floor(Math.log10(v)), f = v / p;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * p;
}

/** Multi-series line/area chart with a crosshair tooltip, a legend that doubles as a series filter, direct end labels
 *  (≤4 series) and a data table, so identity is never colour-only. Series colours follow the series, not its rank. */
export function TimeChart({ labels, series, band, area = false, label, height = 220, live = false, fmtX = (s: string) => s, fmtY = (v: number) => String(v), unit = "" }: {
  labels: string[]; series: LineSeries[]; band?: Band; area?: boolean; label: string; height?: number; live?: boolean; fmtX?: (s: string) => string; fmtY?: (v: number) => string; unit?: string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const [off, setOff] = useState<Set<string>>(new Set());
  const W = 640, H = height, L = 46, R = series.length <= 4 ? 96 : 14, T = 14, B = 26;
  const n = labels.length;
  const shown = series.filter((s) => !off.has(s.name));
  const nums = (a: (number | null)[]) => a.filter((v): v is number => v !== null);
  const max = niceMax(Math.max(1, ...shown.flatMap((s) => nums(s.values)), ...(band ? nums(band.hi) : [])));
  const lastIdx = (v: (number | null)[]) => { for (let i = v.length - 1; i >= 0; i--) if (v[i] !== null) return i; return -1; };
  const x = (i: number) => L + (n <= 1 ? 0 : (i / (n - 1)) * (W - L - R));
  const y = (v: number) => T + (1 - v / max) * (H - T - B);
  const color = (s: LineSeries, i: number) => s.color ?? SERIES[i % SERIES.length];
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => Math.round(f * max));
  const xt = n > 1 ? [0, Math.floor(n / 4), Math.floor(n / 2), Math.floor((3 * n) / 4), n - 1] : [0];
  const path = (v: (number | null)[]) => { let d = "", pen = false; v.forEach((q, i) => { if (q === null) { pen = false; return; } d += `${pen ? "L" : "M"}${x(i).toFixed(1)} ${y(q).toFixed(1)}`; pen = true; }); return d; };
  const bandPath = (b: Band) => { const ix = b.hi.map((_, i) => i).filter((i) => b.hi[i] !== null && b.lo[i] !== null); if (ix.length < 2) return ""; return `${ix.map((i, k) => `${k ? "L" : "M"}${x(i).toFixed(1)} ${y(b.hi[i] as number).toFixed(1)}`).join(" ")} ${[...ix].reverse().map((i) => `L${x(i).toFixed(1)} ${y(b.lo[i] as number).toFixed(1)}`).join(" ")} Z`; };
  const toggle = (name: string) => setOff((o) => { const nx = new Set(o); nx.has(name) ? nx.delete(name) : nx.add(name); return nx; });

  function move(e: React.PointerEvent<SVGSVGElement>) {
    const r = e.currentTarget.getBoundingClientRect();
    const px = ((e.clientX - r.left) / r.width) * W;
    setHover(Math.max(0, Math.min(n - 1, Math.round(((px - L) / (W - L - R)) * (n - 1)))));
  }

  return (
    <div className="tchart">
      <div className="chart-legend" role="group" aria-label="Series">
        {series.map((s, i) => (
          <button type="button" key={s.name} className={`lg ${off.has(s.name) ? "off" : ""}`} aria-pressed={!off.has(s.name)} onClick={() => toggle(s.name)}>
            <i style={{ background: color(s, i) }} />{s.name}
          </button>
        ))}
      </div>
      <div className="tchart-box">
        <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label} onPointerMove={move} onPointerLeave={() => setHover(null)}>
          {ticks.map((t) => <g key={t}><line className="grid-line" x1={L} x2={W - R} y1={y(t)} y2={y(t)} /><text x={L - 6} y={y(t) + 4} textAnchor="end">{fmtY(t)}</text></g>)}
          {xt.map((i) => <text key={i} x={x(i)} y={H - 6} textAnchor={i === 0 ? "start" : i === n - 1 ? "end" : "middle"}>{fmtX(labels[i] ?? "")}</text>)}
          {band && <path d={bandPath(band)} fill={band.color ?? "var(--c4)"} opacity=".16"><title>{band.name}</title></path>}
          {series.map((s, i) => off.has(s.name) ? null : (
            <g key={s.name} className="tline" style={{ opacity: s.muted ? 0.5 : 1 }}>
              {area && !s.values.includes(null) && <path d={`${path(s.values)} L${x(n - 1)} ${y(0)} L${x(0)} ${y(0)} Z`} fill={color(s, i)} opacity=".14" />}
              <path d={path(s.values)} fill="none" stroke={color(s, i)} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" strokeDasharray={s.dashed ? "6 5" : undefined} />
              {live && lastIdx(s.values) >= 0 && <circle cx={x(lastIdx(s.values))} cy={y(s.values[lastIdx(s.values)] ?? 0)} r="4" fill={color(s, i)} stroke="var(--surface)" strokeWidth="2"><animate attributeName="r" values="4;7;4" dur="1.6s" repeatCount="indefinite" /></circle>}
              {series.length <= 4 && lastIdx(s.values) >= 0 && <text className="end-label" x={x(lastIdx(s.values)) + 8} y={y(s.values[lastIdx(s.values)] ?? 0) + 4}>{s.name.length > 14 ? `${s.name.slice(0, 13)}…` : s.name}</text>}
            </g>
          ))}
          {hover !== null && (
            <g pointerEvents="none">
              <line className="crosshair" x1={x(hover)} x2={x(hover)} y1={T} y2={H - B} />
              {shown.filter((s) => s.values[hover] !== null && s.values[hover] !== undefined).map((s) => <circle key={s.name} cx={x(hover)} cy={y(s.values[hover] ?? 0)} r="4.5" fill={color(s, series.indexOf(s))} stroke="var(--surface)" strokeWidth="2" />)}
            </g>
          )}
        </svg>
        {hover !== null && (
          <div className="tip" style={{ left: `${Math.min(78, Math.max(2, (x(hover) / W) * 100))}%` }}>
            <b>{fmtX(labels[hover] ?? "")}</b>
            {shown.filter((s) => s.values[hover] !== null && s.values[hover] !== undefined).map((s) => <span key={s.name}><i style={{ background: color(s, series.indexOf(s)) }} />{s.name}<em>{fmtY(s.values[hover] ?? 0)}{unit}</em></span>)}
          </div>
        )}
      </div>
      <details><summary>Data table</summary>
        <div className="table-scroll"><table><thead><tr><th>Time</th>{series.map((s) => <th key={s.name}>{s.name}</th>)}</tr></thead>
          <tbody>{labels.map((l, i) => i % Math.max(1, Math.floor(n / 24)) === 0 && <tr key={l}><td>{fmtX(l)}</td>{series.map((s) => <td key={s.name}>{s.values[i] ?? "–"}</td>)}</tr>)}</tbody></table></div>
      </details>
    </div>
  );
}

/** Tiny trend line for KPI tiles; decorative (the tile already states the number). */
export function Spark({ values, tone = "currentColor" }: { values: number[]; tone?: string }) {
  if (values.length < 2) return null;
  const W = 100, H = 28, max = Math.max(1, ...values);
  const pts = values.map((v, i) => [(i / (values.length - 1)) * W, H - 3 - (v / max) * (H - 6)] as const);
  const d = pts.map(([px, py], i) => `${i ? "L" : "M"}${px.toFixed(1)} ${py.toFixed(1)}`).join(" ");
  return (
    <svg className="spark" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden="true">
      <path d={`${d} L${W} ${H} L0 ${H} Z`} fill={tone} opacity=".16" />
      <path d={d} fill="none" stroke={tone} strokeWidth="1.8" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

import type { ReactNode } from "react";

/** Small dependency-free SVG charts. Every chart has direct value labels, a legend where it has >1 series,
 *  and a collapsible data table so no information is colour-only. */
export interface Datum { label: string; value: number; color?: string }
const SERIES = ["var(--c1)", "var(--c2)", "var(--c3)", "var(--c4)"];

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
              <circle key={d.label} cx="70" cy="70" r={R} fill="none" stroke={d.color ?? SERIES[i % 4]} strokeWidth="22" strokeDasharray={`${Math.max(len - 2, 0)} ${C}`} strokeDashoffset={-off} transform="rotate(-90 70 70)"><title>{`${d.label}: ${d.value}`}</title></circle>
            );
            off += len; return el;
          })}
          <text className="val" x="70" y="75" textAnchor="middle" style={{ fontSize: 20 }}>{total}</text>
        </svg>
        <div className="chart-legend" style={{ flexDirection: "column" }}>
          {data.map((d, i) => <span key={d.label}><i style={{ background: d.color ?? SERIES[i % 4] }} />{d.label} · <b>{d.value}</b></span>)}
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

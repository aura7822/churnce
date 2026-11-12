/** "Autotyping" signed-in role, drawn as SVG: a clip-path rect grows one character at a time (SMIL, discrete steps) and a caret follows it.
 *  Reduced-motion users get the finished text immediately. */
export function TypedRole({ text }: { text: string }) {
  const ch = 17; // monospace advance at 28px
  const w = Math.max(1, text.length) * ch;
  const steps = Array.from({ length: text.length + 1 }, (_, i) => i * ch);
  const dur = `${Math.max(1.1, text.length * 0.11)}s`;
  const still = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
  const id = `typed-${text.replace(/\W/g, "")}`;
  return (
    <svg className="typed" width={w + 8} height={38} viewBox={`0 0 ${w + 8} 38`} role="img" aria-label={text}>
      <defs>
        <clipPath id={id}>
          <rect x="0" y="0" height="38" width={still ? w : 0}>
            {!still && <animate attributeName="width" values={steps.join(";")} dur={dur} begin="0.35s" calcMode="discrete" fill="freeze" />}
          </rect>
        </clipPath>
      </defs>
      <text x="0" y="28" fontFamily='ui-monospace, "JetBrains Mono", Menlo, monospace' fontSize="28" fontWeight="700" fill="currentColor" textLength={w} lengthAdjust="spacingAndGlyphs" clipPath={`url(#${id})`}>{text}</text>
      <rect y="5" width="3" height="29" fill="currentColor" x={still ? w + 2 : 0}>
        {!still && <animate attributeName="x" values={steps.join(";")} dur={dur} begin="0.35s" calcMode="discrete" fill="freeze" />}
        {!still && <animate attributeName="opacity" values="1;0;1" dur="0.9s" repeatCount="indefinite" />}
      </rect>
    </svg>
  );
}

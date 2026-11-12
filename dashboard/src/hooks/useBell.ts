/** Terminal-style bell: a short, decaying 880 Hz tone (two quick strikes) from the Web Audio API. Needs no sound file.
 *  Browsers only allow audio after a user gesture; Digest is a click, so the context is already unlocked. */
let ctx: AudioContext | null = null;

export function unlockBell(): void {
  try {
    const AC = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!AC) return;
    ctx = ctx ?? new AC();
    if (ctx.state === "suspended") void ctx.resume();
  } catch { /* audio unavailable: the toast still announces completion */ }
}

export function ringBell(): void {
  try {
    unlockBell();
    if (!ctx) return;
    const t0 = ctx.currentTime;
    for (const [at, hz] of [[0, 880], [0.14, 1320]] as const) {
      const osc = ctx.createOscillator(), gain = ctx.createGain();
      osc.type = "sine"; osc.frequency.value = hz;
      gain.gain.setValueAtTime(0.0001, t0 + at);
      gain.gain.exponentialRampToValueAtTime(0.28, t0 + at + 0.01);
      gain.gain.exponentialRampToValueAtTime(0.0001, t0 + at + 0.55);
      osc.connect(gain).connect(ctx.destination);
      osc.start(t0 + at); osc.stop(t0 + at + 0.6);
    }
  } catch { /* ignore */ }
}

import type { LiveMessage } from "../types";
import { syncClock, tokenStore, wsUrl } from "./api";

type Listener = (m: LiveMessage) => void;
export type ConnState = "connecting" | "live" | "offline";

/** One authenticated WebSocket with exponential-backoff reconnect. The token is sent as the first
 *  frame, never in the URL, so it cannot leak into proxy or access logs. */
class LiveSocket {
  private ws: WebSocket | null = null;
  private listeners = new Set<Listener>();
  private stateListeners = new Set<(s: ConnState) => void>();
  private attempt = 0;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private wanted = false;
  state: ConnState = "offline";

  start() {
    if (this.wanted) return;
    this.wanted = true;
    this.open();
  }
  stop() {
    this.wanted = false;
    if (this.timer) clearTimeout(this.timer);
    this.ws?.close();
    this.ws = null;
    this.setState("offline");
  }
  on(fn: Listener) { this.listeners.add(fn); return () => { this.listeners.delete(fn); }; }
  onState(fn: (s: ConnState) => void) { this.stateListeners.add(fn); fn(this.state); return () => { this.stateListeners.delete(fn); }; }
  private setState(s: ConnState) { this.state = s; this.stateListeners.forEach((f) => f(s)); }

  private open() {
    const token = tokenStore.get();
    if (!token || !this.wanted) return;
    this.setState("connecting");
    const ws = new WebSocket(wsUrl());
    this.ws = ws;
    ws.onopen = () => ws.send(JSON.stringify({ type: "auth", token }));
    ws.onmessage = (ev) => {
      let msg: LiveMessage;
      try { msg = JSON.parse(ev.data as string) as LiveMessage; } catch { return; }
      if (msg.type === "hello") { this.attempt = 0; this.setState("live"); }
      syncClock(msg.server_time ?? msg.ts);
      if (msg.type === "ping" || msg.type === "hello") { this.listeners.forEach((f) => f(msg)); return; }
      this.listeners.forEach((f) => f(msg));
    };
    ws.onclose = () => {
      this.ws = null;
      if (!this.wanted) return;
      this.setState("offline");
      const delay = Math.min(15000, 500 * 2 ** this.attempt++) + Math.random() * 300;
      this.timer = setTimeout(() => this.open(), delay);
    };
    ws.onerror = () => ws.close();
  }
}
export const socket = new LiveSocket();

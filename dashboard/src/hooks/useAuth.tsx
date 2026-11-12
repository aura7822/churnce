import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, setUnauthorizedHandler, tokenStore } from "../services/api";
import { socket } from "../services/socket";
import type { Me, Role } from "../types";

interface AuthCtx {
  me: Me | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  loginSite: (websiteId: string, password: string, role: Role) => Promise<void>;
  loginWithToken: (token: string) => Promise<void>;
  logout: () => void;
  can: (perm: string) => boolean;
}
const Ctx = createContext<AuthCtx | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState<boolean>(!!tokenStore.get());

  const logout = useCallback(() => {
    socket.stop();
    tokenStore.clear();
    setMe(null);
  }, []);

  useEffect(() => { setUnauthorizedHandler(logout); }, [logout]);

  useEffect(() => {
    if (!tokenStore.get()) return;
    api.me().then((m) => { setMe(m); socket.start(); }).catch(() => tokenStore.clear()).finally(() => setLoading(false));
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const r = await api.login(email, password);
    tokenStore.set(r.token);
    setMe(await api.me());
    socket.start();
  }, []);

  const loginSite = useCallback(async (websiteId: string, password: string, role: Role) => {
    const r = await api.siteLogin(websiteId.trim(), password.trim(), role);
    tokenStore.set(r.token);
    setMe(await api.me());
    socket.start();
  }, []);

  const loginWithToken = useCallback(async (token: string) => {
    tokenStore.set(token);
    setMe(await api.me());
    socket.start();
  }, []);

  const value = useMemo<AuthCtx>(() => ({
    me, loading, login, loginSite, loginWithToken, logout,
    can: (perm) => !!me && (me.permissions.includes("*") || me.permissions.includes(perm)),
  }), [me, loading, login, loginSite, loginWithToken, logout]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthCtx {
  const c = useContext(Ctx);
  if (!c) throw new Error("useAuth must be used inside <AuthProvider>");
  return c;
}

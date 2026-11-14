import { useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  api,
  onSessionExpired,
  refreshSession,
  setAccessToken,
  unwrap,
  type Me,
  type Permission,
} from "@/api/client";

type Status = "loading" | "signed-out" | "signed-in";

interface AuthValue {
  status: Status;
  me: Me | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  can: (p: Permission) => boolean;
}

const Ctx = createContext<AuthValue | null>(null);

async function fetchMe(): Promise<Me> {
  return unwrap(await api.GET("/api/auth/me"));
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>("loading");
  const [me, setMe] = useState<Me | null>(null);
  const qc = useQueryClient();

  const signedOut = useCallback(() => {
    setAccessToken(null);
    setMe(null);
    setStatus("signed-out");
    qc.clear();
  }, [qc]);

  // On load: try the refresh cookie silently.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (await refreshSession()) {
        try {
          const m = await fetchMe();
          if (!cancelled) {
            setMe(m);
            setStatus("signed-in");
          }
          return;
        } catch {
          /* fall through */
        }
      }
      if (!cancelled) setStatus("signed-out");
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const off = onSessionExpired(signedOut);
    return () => {
      off();
    };
  }, [signedOut]);

  const login = useCallback<AuthValue["login"]>(
    async (email, password) => {
      const res = await api.POST("/api/auth/login", { body: { email, password } });
      setAccessToken(unwrap(res).access_token);
      qc.clear();
      setMe(await fetchMe());
      setStatus("signed-in");
    },
    [qc],
  );

  const logout = useCallback(async () => {
    await api.POST("/api/auth/logout");
    signedOut();
  }, [signedOut]);

  const can = useCallback((p: Permission) => !!me?.permissions.includes(p), [me]);

  const value = useMemo(
    () => ({ status, me, login, logout, can }),
    [status, me, login, logout, can],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthValue {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}

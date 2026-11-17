import { useCallback, useEffect, useSyncExternalStore } from "react";
import { api } from "@/api/client";

/** Light / dark mode. The choice is per user: kept in this browser (so the first paint is right, see index.html)
 * and saved on the account (`ui.theme` preference) so it follows the user to other devices. */
export type ThemeMode = "light" | "dark" | "system";
const KEY = "erp.theme";
export const PREF_KEY = "ui.theme";

const media = () =>
  typeof window !== "undefined" && window.matchMedia
    ? window.matchMedia("(prefers-color-scheme: dark)")
    : null;

export function readMode(): ThemeMode {
  try {
    const m = localStorage.getItem(KEY);
    return m === "light" || m === "dark" ? m : "system";
  } catch {
    return "system";
  }
}

export function resolve(mode: ThemeMode): "light" | "dark" {
  return mode === "dark" || (mode === "system" && media()?.matches) ? "dark" : "light";
}

const listeners = new Set<() => void>();
function apply(mode: ThemeMode) {
  document.documentElement.dataset.theme = resolve(mode);
  listeners.forEach((l) => l());
}

/** Set the mode for this browser (and the page) right away. */
export function setLocalMode(mode: ThemeMode) {
  try {
    if (mode === "system") localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, mode);
  } catch {
    /* private mode: still applied for this page */
  }
  apply(mode);
}

function subscribe(cb: () => void) {
  listeners.add(cb);
  const mq = media();
  const onSystem = () => readMode() === "system" && apply("system");
  mq?.addEventListener?.("change", onSystem);
  return () => {
    listeners.delete(cb);
    mq?.removeEventListener?.("change", onSystem);
  };
}

/** The current mode, the theme actually shown, and a setter that also saves it on the user's account. */
export function useTheme() {
  const mode = useSyncExternalStore(subscribe, readMode, () => "system" as ThemeMode);
  const shown = useSyncExternalStore(
    subscribe,
    () => (document.documentElement.dataset.theme === "dark" ? "dark" : "light"),
    () => "light" as const,
  );
  const setMode = useCallback((m: ThemeMode) => {
    setLocalMode(m);
    void api
      .PUT("/api/me/preferences/{key}", {
        params: { path: { key: PREF_KEY } },
        body: { value: { mode: m } },
      })
      .catch(() => undefined);
  }, []);
  return { mode, shown, setMode };
}

/** After sign-in: take the mode saved on the account (another device may have changed it). */
export function useAccountTheme(enabled: boolean) {
  useEffect(() => {
    if (!enabled) return;
    let live = true;
    void api
      .GET("/api/me/preferences/{key}", { params: { path: { key: PREF_KEY } } })
      .then((r) => {
        const m = (r.data?.value as { mode?: string } | undefined)?.mode;
        if (live && (m === "light" || m === "dark" || m === "system") && m !== readMode())
          setLocalMode(m);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [enabled]);
}

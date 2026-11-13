import * as T from "@radix-ui/react-toast";
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { cn } from "@/lib/cn";

export type ToastTone = "default" | "success" | "error";
interface ToastItem {
  id: number;
  title: string;
  description?: string;
  tone: ToastTone;
}
interface ToastApi {
  toast: (t: { title: string; description?: string; tone?: ToastTone }) => void;
}

const Ctx = createContext<ToastApi | null>(null);
let nextId = 1;

/** Small dark toast ("Reordered · 1 bottleneck cleared"), bottom-right, auto-dismiss. */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const toast = useCallback<ToastApi["toast"]>(({ title, description, tone = "default" }) => {
    setItems((xs) => [...xs, { id: nextId++, title, description, tone }]);
  }, []);
  const api = useMemo(() => ({ toast }), [toast]);
  return (
    <Ctx.Provider value={api}>
      <T.Provider swipeDirection="right" duration={4000}>
        {children}
        {items.map((t) => (
          <T.Root
            key={t.id}
            onOpenChange={(open) => !open && setItems((xs) => xs.filter((x) => x.id !== t.id))}
            className="flex animate-fade-in items-start gap-3 rounded-tip bg-ink px-4 py-3 text-white shadow-tip"
          >
            <span
              aria-hidden
              className={cn(
                "mt-1.5 size-2 flex-none rounded-full",
                t.tone === "success" && "bg-ok-line",
                t.tone === "error" && "bg-hi-line",
                t.tone === "default" && "bg-bl-line",
              )}
            />
            <div className="flex min-w-0 flex-1 flex-col gap-0.5">
              <T.Title className="text-sm font-semibold">{t.title}</T.Title>
              {t.description && (
                <T.Description className="text-[13px] text-faint">{t.description}</T.Description>
              )}
            </div>
            <T.Close
              aria-label="Dismiss"
              className="cursor-pointer border-0 bg-transparent text-faint hover:text-white"
            >
              ×
            </T.Close>
          </T.Root>
        ))}
        <T.Viewport className="fixed right-6 bottom-6 z-[70] m-0 flex w-[360px] max-w-[calc(100vw-48px)] list-none flex-col gap-2 p-0 outline-none" />
      </T.Provider>
    </Ctx.Provider>
  );
}

export function useToast(): ToastApi {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useToast must be used inside <ToastProvider>");
  return ctx;
}

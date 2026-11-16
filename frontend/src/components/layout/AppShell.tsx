import { useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { cn } from "@/lib/cn";
import { PageActionsSlotProvider } from "./PageActions";
import { TopNav } from "./TopNav";

/** Signed-in layout: top nav + 1360px content column (40px top, 64px bottom, 32px gaps). */
export function AppShell() {
  const [slot, setSlot] = useState<HTMLElement | null>(null);
  // the AI Assistant is a full-screen workspace (no content column)
  const full = useLocation().pathname.startsWith("/assistant");
  return (
    <PageActionsSlotProvider value={slot}>
      <div className="min-h-screen bg-white">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:top-4 focus:left-4 focus:z-50 focus:rounded-full focus:bg-white focus:px-4 focus:py-2"
        >
          Skip to content
        </a>
        <TopNav actionsRef={setSlot} />
        <main
          id="main"
          className={cn(
            full ? "w-full" : "mx-auto flex max-w-[1360px] flex-col gap-8 px-8 pt-10 pb-16",
          )}
        >
          <Outlet />
        </main>
      </div>
    </PageActionsSlotProvider>
  );
}

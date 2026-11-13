import { createContext, useContext, type ReactNode } from "react";
import { createPortal } from "react-dom";

const SlotCtx = createContext<HTMLElement | null>(null);
export const PageActionsSlotProvider = SlotCtx.Provider;
export function usePageActionsSlot() {
  return useContext(SlotCtx);
}

/** Renders page-specific actions (e.g. "+ New order") into the top bar, as in the mockup. */
export function PageActions({ children }: { children: ReactNode }) {
  const slot = usePageActionsSlot();
  return slot ? createPortal(children, slot) : null;
}

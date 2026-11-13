import * as Dialog from "@radix-ui/react-dialog";
import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

export type ModalTone = "default" | "danger" | "warning";

/**
 * Modal (Radix Dialog): focus trap, Esc to close, scroll lock, aria wiring.
 * Styled like the "Reordering creates bottlenecks" popup: 20px radius, 26px padding.
 */
export function Modal({
  open,
  onOpenChange,
  title,
  description,
  tone = "default",
  children,
  footer,
  width = 520,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  description?: ReactNode;
  tone?: ModalTone;
  children?: ReactNode;
  footer?: ReactNode;
  width?: number;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="overlay fixed inset-0 z-50 animate-fade-in" />
        <Dialog.Content
          style={{ maxWidth: width }}
          className="fixed top-1/2 left-1/2 z-50 flex max-h-[calc(100vh-48px)] w-[calc(100%-48px)] -translate-x-1/2 -translate-y-1/2 flex-col gap-[18px] overflow-y-auto rounded-modal bg-white p-[26px] shadow-modal focus:outline-none"
        >
          <div className="flex items-start gap-3.5">
            {tone !== "default" && (
              <span
                aria-hidden
                className={cn(
                  "grid size-10 flex-none place-items-center rounded-full font-bold",
                  tone === "danger" ? "bg-hi-bg text-hi" : "bg-md-bg text-md",
                )}
              >
                !
              </span>
            )}
            <div className="flex min-w-0 flex-1 flex-col gap-1">
              <Dialog.Title className="m-0 text-lg font-semibold">{title}</Dialog.Title>
              {description ? (
                <Dialog.Description className="m-0 text-sm text-muted">
                  {description}
                </Dialog.Description>
              ) : (
                <Dialog.Description className="sr-only">{title}</Dialog.Description>
              )}
            </div>
            <Dialog.Close
              aria-label="Close"
              className="-mt-1 -mr-2 cursor-pointer rounded-lg border-0 bg-transparent px-2 py-1 text-lg leading-none text-subtle hover:bg-surface-2 hover:text-ink"
            >
              ×
            </Dialog.Close>
          </div>
          {children}
          {footer && <div className="flex flex-wrap justify-end gap-2.5">{footer}</div>}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

import * as Dialog from "@radix-ui/react-dialog";
import type { ReactNode } from "react";

/** Right-side drawer: the page stays behind it, Esc closes, focus stays inside (Billing drawers). */
export function Sheet({
  open,
  onOpenChange,
  title,
  eyebrow,
  description,
  header,
  footer,
  children,
  width = 580,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  eyebrow?: ReactNode;
  description?: ReactNode;
  header?: ReactNode;
  footer?: ReactNode;
  children: ReactNode;
  width?: number;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="overlay fixed inset-0 z-50 animate-fade-in" />
        <Dialog.Content
          style={{ maxWidth: width }}
          className="fixed top-0 right-0 z-50 flex h-full w-full flex-col bg-white shadow-modal focus:outline-none"
        >
          <div className="flex items-start gap-3 border-b border-line px-6 pt-5 pb-4">
            <div className="flex min-w-0 flex-1 flex-col gap-1">
              {eyebrow && (
                <span className="text-xs font-semibold tracking-[0.06em] text-muted uppercase">
                  {eyebrow}
                </span>
              )}
              <Dialog.Title className="m-0 text-[22px] font-semibold tracking-[-0.01em]">
                {title}
              </Dialog.Title>
              {description ? (
                <Dialog.Description className="m-0 text-sm text-muted">
                  {description}
                </Dialog.Description>
              ) : (
                <Dialog.Description className="sr-only">{title}</Dialog.Description>
              )}
              {header}
            </div>
            <Dialog.Close
              aria-label="Close"
              className="grid size-9 cursor-pointer place-items-center rounded-full border border-line bg-white text-lg leading-none text-subtle hover:bg-surface-2 hover:text-ink"
            >
              ×
            </Dialog.Close>
          </div>
          <div className="flex-1 overflow-y-auto px-6 py-5">{children}</div>
          {footer && (
            <div className="flex flex-wrap items-center gap-2.5 border-t border-line px-6 py-4">
              {footer}
            </div>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

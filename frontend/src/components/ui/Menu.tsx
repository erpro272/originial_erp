import * as DM from "@radix-ui/react-dropdown-menu";
import * as PP from "@radix-ui/react-popover";
import * as TT from "@radix-ui/react-tooltip";
import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

const panel =
  "z-50 min-w-[200px] rounded-tip border border-line bg-white p-1.5 shadow-tip animate-fade-in";

/** Dropdown menu (Radix): keyboard navigation, typeahead, focus return. */
export const Menu = DM.Root;
export const MenuTrigger = DM.Trigger;
export function MenuContent({
  children,
  align = "end",
}: {
  children: ReactNode;
  align?: "start" | "end";
}) {
  return (
    <DM.Portal>
      <DM.Content align={align} sideOffset={6} className={panel}>
        {children}
      </DM.Content>
    </DM.Portal>
  );
}
export function MenuItem({
  children,
  onSelect,
  disabled,
  className,
}: {
  children: ReactNode;
  onSelect?: () => void;
  disabled?: boolean;
  className?: string;
}) {
  return (
    <DM.Item
      disabled={disabled}
      onSelect={onSelect}
      className={cn(
        "flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-sm text-ink-2 outline-none select-none data-[disabled]:cursor-default data-[disabled]:opacity-50 data-[highlighted]:bg-surface-2",
        className,
      )}
    >
      {children}
    </DM.Item>
  );
}
export const MenuSeparator = () => <DM.Separator className="my-1 h-px bg-divider" />;
export const MenuLabel = ({ children }: { children: ReactNode }) => (
  <DM.Label className="px-3 pt-2 pb-1 text-xs font-semibold tracking-[.04em] text-muted uppercase">
    {children}
  </DM.Label>
);

/** Popover (Radix) for filter panels and the column picker. */
export const Popover = PP.Root;
export const PopoverTrigger = PP.Trigger;
export function PopoverContent({
  children,
  align = "end",
  className,
}: {
  children: ReactNode;
  align?: "start" | "center" | "end";
  className?: string;
}) {
  return (
    <PP.Portal>
      <PP.Content align={align} sideOffset={6} className={cn(panel, "p-3", className)}>
        {children}
      </PP.Content>
    </PP.Portal>
  );
}

/** Tooltip styled like the Gantt hover card (#tip). */
export function Tooltip({ content, children }: { content: ReactNode; children: ReactNode }) {
  return (
    <TT.Provider delayDuration={150}>
      <TT.Root>
        <TT.Trigger asChild>{children}</TT.Trigger>
        <TT.Portal>
          <TT.Content
            sideOffset={6}
            className="z-[60] max-w-[260px] animate-fade-in rounded-tip border border-line bg-white px-4 py-3 text-[13px] text-ink shadow-tip"
          >
            {content}
          </TT.Content>
        </TT.Portal>
      </TT.Root>
    </TT.Provider>
  );
}

/** Label/value rows inside a tooltip ("Machine · CNC 01"). */
export function TipRow({ label, value }: { label: ReactNode; value: ReactNode }) {
  return (
    <div className="flex justify-between gap-3 border-t border-divider-2 py-[5px] first:border-t-0">
      <span className="text-muted">{label}</span>
      <span className="text-right font-medium">{value}</span>
    </div>
  );
}

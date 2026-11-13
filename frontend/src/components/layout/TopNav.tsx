import { NavLink } from "react-router-dom";
import { BRAND_NAME } from "@/app/brand";
import { MODULES } from "@/app/nav";
import { cn } from "@/lib/cn";
import { UserMenu } from "./UserMenu";

/** Top navigation exactly as the mockups: brand dot, modules with a 2px blue underline. */
export function TopNav({ actionsRef }: { actionsRef?: (el: HTMLElement | null) => void }) {
  return (
    <header className="border-b border-line bg-white">
      <div className="mx-auto flex min-h-16 max-w-[1360px] flex-wrap items-center gap-10 px-8">
        <NavLink
          to="/"
          className="flex items-center gap-2.5 text-lg font-bold text-ink no-underline hover:text-ink"
        >
          <span aria-hidden className="size-4 rounded-full bg-primary" />
          {BRAND_NAME}
        </NavLink>
        <nav aria-label="Main" className="flex flex-1 flex-wrap gap-8">
          {MODULES.map((m) => (
            <NavLink
              key={m.key}
              to={m.path}
              className={({ isActive }) =>
                cn(
                  "border-b-2 border-transparent pt-[21px] pb-[19px] text-[15px] text-ink-3 no-underline hover:text-ink",
                  isActive && "border-primary font-semibold text-ink",
                )
              }
            >
              {m.label}
            </NavLink>
          ))}
        </nav>
        <div ref={actionsRef} className="flex items-center gap-2" />
        <UserMenu />
      </div>
    </header>
  );
}

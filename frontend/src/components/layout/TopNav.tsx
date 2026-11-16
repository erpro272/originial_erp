import { Link, NavLink, useLocation } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import { BRAND_NAME } from "@/app/brand";
import { MODULES } from "@/app/nav";
import { cn } from "@/lib/cn";
import { UserMenu } from "./UserMenu";

function Sparkle() {
  return (
    <svg viewBox="0 0 24 24" className="size-5" fill="currentColor" aria-hidden="true">
      <path d="M12 2.5c.4 3.9 2.6 6.1 6.5 6.5-3.9.4-6.1 2.6-6.5 6.5-.4-3.9-2.6-6.1-6.5-6.5 3.9-.4 6.1-2.6 6.5-6.5zM19 14c.2 1.9 1.1 2.8 3 3-1.9.2-2.8 1.1-3 3-.2-1.9-1.1-2.8-3-3 1.9-.2 2.8-1.1 3-3z" />
    </svg>
  );
}

/** Top navigation exactly as the mockups: brand dot, modules with a 2px blue underline. */
export function TopNav({ actionsRef }: { actionsRef?: (el: HTMLElement | null) => void }) {
  const { can } = useAuth();
  const loc = useLocation();
  const onAssistant = loc.pathname.startsWith("/assistant");
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
        {can("ai.use") && (
          <Link
            to="/assistant"
            state={{ from: onAssistant ? undefined : `${loc.pathname}${loc.search}` }}
            aria-label="AI Assistant"
            title="AI Assistant"
            className={cn(
              "grid size-10 place-items-center rounded-full border text-primary no-underline transition-colors hover:bg-bl-bg",
              onAssistant ? "border-bl-line bg-bl-bg" : "border-line bg-white",
            )}
          >
            <Sparkle />
          </Link>
        )}
        <UserMenu />
      </div>
    </header>
  );
}

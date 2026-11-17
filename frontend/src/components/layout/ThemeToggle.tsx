import { Menu, MenuContent, MenuItem, MenuLabel, MenuTrigger } from "@/components/ui/Menu";
import { useTheme, type ThemeMode } from "@/lib/theme";

function Sun() {
  return (
    <svg
      viewBox="0 0 24 24"
      className="size-[18px]"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
    </svg>
  );
}
function Moon() {
  return (
    <svg
      viewBox="0 0 24 24"
      className="size-[18px]"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      aria-hidden="true"
    >
      <path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z" />
    </svg>
  );
}

const OPTIONS: { mode: ThemeMode; label: string; hint: string }[] = [
  { mode: "light", label: "Light", hint: "" },
  { mode: "dark", label: "Dark", hint: "" },
  { mode: "system", label: "System", hint: "Follow this device" },
];

/** Sun / moon button in the top bar: Light, Dark or follow the device. Saved per user. */
export function ThemeToggle() {
  const { mode, shown, setMode } = useTheme();
  return (
    <Menu>
      <MenuTrigger asChild>
        <button
          type="button"
          aria-label={`Theme: ${mode === "system" ? `system (${shown})` : mode}`}
          title="Light / dark mode"
          className="grid size-10 cursor-pointer place-items-center rounded-full border border-line bg-card text-ink-3 transition-colors hover:bg-surface-2 hover:text-ink"
        >
          {shown === "dark" ? <Moon /> : <Sun />}
        </button>
      </MenuTrigger>
      <MenuContent>
        <MenuLabel>Appearance</MenuLabel>
        {OPTIONS.map((o) => (
          <MenuItem key={o.mode} onSelect={() => setMode(o.mode)}>
            <span className="grid size-4 place-items-center text-primary" aria-hidden="true">
              {mode === o.mode ? "✓" : ""}
            </span>
            <span className="flex flex-col">
              <span>{o.label}</span>
              {o.hint && <span className="text-xs text-muted">{o.hint}</span>}
            </span>
          </MenuItem>
        ))}
      </MenuContent>
    </Menu>
  );
}

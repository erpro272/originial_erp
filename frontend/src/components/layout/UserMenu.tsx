import { useNavigate } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import {
  Menu,
  MenuContent,
  MenuItem,
  MenuLabel,
  MenuSeparator,
  MenuTrigger,
} from "@/components/ui/Menu";
import { Tag } from "@/components/ui/Tag";
import { useToast } from "@/components/ui/Toast";
import { initials } from "@/lib/format";

const roleLabel: Record<string, string> = {
  owner: "Owner",
  planner: "Planner",
  purchaser: "Purchaser",
  accountant: "Accountant",
};

export function UserMenu() {
  const { me, logout, switchCompany, can } = useAuth();
  const navigate = useNavigate();
  const { toast } = useToast();
  if (!me) return null;
  const others = me.companies.filter((c) => c.id !== me.company.id);

  return (
    <Menu>
      <MenuTrigger
        aria-label={`Account menu for ${me.full_name}`}
        className="flex cursor-pointer items-center gap-2.5 rounded-full border border-line-input bg-white py-1 pr-3 pl-1 hover:border-faint"
      >
        <span className="grid size-8 place-items-center rounded-full bg-bl-bg text-xs font-semibold text-bl">
          {initials(me.full_name)}
        </span>
        <span className="hidden max-w-40 truncate text-[13px] font-medium text-ink-2 md:inline">
          {me.company.name}
        </span>
      </MenuTrigger>
      <MenuContent>
        <div className="flex flex-col gap-1 px-3 pt-1.5 pb-2">
          <span className="text-sm font-semibold">{me.full_name}</span>
          <span className="text-xs text-muted">{me.email}</span>
          <span className="mt-1 flex items-center gap-2 text-xs text-ink-2">
            {me.company.name}{" "}
            <Tag tone="bl" size="sm">
              {roleLabel[me.role] ?? me.role}
            </Tag>
          </span>
        </div>
        {others.length > 0 && (
          <>
            <MenuSeparator />
            <MenuLabel>Switch company</MenuLabel>
            {others.map((c) => (
              <MenuItem
                key={c.id}
                onSelect={async () => {
                  await switchCompany(c.id);
                  navigate("/orders");
                  toast({ title: `Switched to ${c.name}`, tone: "success" });
                }}
              >
                {c.name}
              </MenuItem>
            ))}
          </>
        )}
        <MenuSeparator />
        {can("audit.read") && (
          <MenuItem onSelect={() => navigate("/settings/audit-log")}>Audit log</MenuItem>
        )}
        <MenuItem
          onSelect={async () => {
            await logout();
            navigate("/login");
          }}
        >
          Sign out
        </MenuItem>
      </MenuContent>
    </Menu>
  );
}

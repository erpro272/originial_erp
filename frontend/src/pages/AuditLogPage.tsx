import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { createColumnHelper } from "@tanstack/react-table";
import { useMemo, useState } from "react";
import { api, unwrap, type Schemas } from "@/api/client";
import { DataTable } from "@/components/data-table/DataTable";
import { Button, Caret } from "@/components/ui/Button";
import { Menu, MenuContent, MenuItem, MenuTrigger } from "@/components/ui/Menu";
import { Modal } from "@/components/ui/Modal";
import { PageHeader } from "@/components/ui/PageHeader";
import { Tag, type TagTone } from "@/components/ui/Tag";
import { dateTime } from "@/lib/format";

type Entry = Schemas["AuditEntryOut"];
const LIMIT = 50;
const ACTIONS = ["create", "update", "delete", "login", "logout_all"] as const;
const actionTone: Record<string, TagTone> = {
  create: "ok",
  update: "bl",
  delete: "hi",
  login: "lo",
  logout_all: "md",
};

const h = createColumnHelper<Entry>();

async function fetchPage(action: string | undefined, offset: number, limit = LIMIT) {
  return unwrap(await api.GET("/api/audit-log", { params: { query: { action, offset, limit } } }));
}

export function AuditLogPage() {
  const [action, setAction] = useState<string | undefined>();
  const [offset, setOffset] = useState(0);
  const [open, setOpen] = useState<Entry | null>(null);
  const q = useQuery({
    queryKey: ["audit-log", action, offset],
    queryFn: () => fetchPage(action, offset),
    placeholderData: keepPreviousData,
  });

  const columns = useMemo(
    () => [
      h.accessor("at", {
        id: "at",
        header: "When",
        cell: (c) => dateTime(c.getValue()),
        meta: { label: "When", alwaysVisible: true },
        enableSorting: false,
      }),
      h.accessor((r) => r.actor_name ?? "System", {
        id: "actor",
        header: "Who",
        meta: { label: "Who" },
        enableSorting: false,
      }),
      h.accessor("action", {
        id: "action",
        header: "Action",
        cell: (c) => <Tag tone={actionTone[c.getValue()] ?? "lo"}>{c.getValue()}</Tag>,
        meta: { label: "Action" },
        enableSorting: false,
      }),
      h.accessor("entity_type", {
        id: "entity_type",
        header: "Record",
        meta: { label: "Record" },
        enableSorting: false,
      }),
      h.accessor("entity_id", {
        id: "entity_id",
        header: "Record ID",
        meta: { label: "Record ID", mono: true, defaultHidden: true },
        enableSorting: false,
      }),
      h.accessor((r) => r.summary ?? "", {
        id: "summary",
        header: "Summary",
        meta: { label: "Summary" },
        enableSorting: false,
      }),
      h.accessor("request_id", {
        id: "request_id",
        header: "Request",
        meta: { label: "Request ID", mono: true, defaultHidden: true },
        enableSorting: false,
      }),
    ],
    [],
  );

  return (
    <>
      <PageHeader
        title="Audit log"
        subtitle="Who changed what, and when. Entries can't be edited or deleted."
      />
      <DataTable<Entry>
        tableId="audit-log"
        title="All changes"
        columns={columns}
        data={q.data?.items ?? []}
        getRowId={(r) => String(r.id)}
        loading={q.isPending}
        error={q.isError ? (q.error as Error).message : null}
        onRetry={() => q.refetch()}
        empty={{ title: "No changes recorded yet" }}
        onRowClick={setOpen}
        pagination={{ total: q.data?.total ?? 0, limit: LIMIT, offset, onChange: setOffset }}
        csv={{
          filename: "audit-log.csv",
          fetchAll: async () => (await fetchPage(action, 0, 500)).items,
        }}
        actions={
          <Menu>
            <MenuTrigger asChild>
              <Button variant="pill">
                {action ? `Action: ${action}` : "All actions"} <Caret />
              </Button>
            </MenuTrigger>
            <MenuContent>
              <MenuItem onSelect={() => (setAction(undefined), setOffset(0))}>All actions</MenuItem>
              {ACTIONS.map((a) => (
                <MenuItem key={a} onSelect={() => (setAction(a), setOffset(0))}>
                  {a}
                </MenuItem>
              ))}
            </MenuContent>
          </Menu>
        }
      />
      <Modal
        open={!!open}
        onOpenChange={(o) => !o && setOpen(null)}
        title={open ? `${open.action} · ${open.entity_type}` : ""}
        description={open ? `${open.actor_name ?? "System"} · ${dateTime(open.at)}` : undefined}
        width={640}
      >
        {open && (
          <div className="grid gap-3 sm:grid-cols-2">
            {(["before", "after"] as const).map((k) => (
              <div key={k} className="flex min-w-0 flex-col gap-1.5">
                <span className="text-xs font-semibold tracking-[.04em] text-muted uppercase">
                  {k}
                </span>
                <pre className="m-0 max-h-72 overflow-auto rounded-xl border border-divider bg-surface p-3 font-mono text-xs">
                  {open[k] ? JSON.stringify(open[k], null, 2) : "—"}
                </pre>
              </div>
            ))}
          </div>
        )}
      </Modal>
    </>
  );
}

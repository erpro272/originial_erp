import { useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { Tag, type TagTone } from "@/components/ui/Tag";
import { useToast } from "@/components/ui/Toast";
import { ApiError } from "@/api/client";
import {
  approveProposals,
  mergeProposals,
  previewProposal,
  rejectProposal,
  type Action,
  type Proposal,
  type ProposalPreview,
} from "./api";

const STATUS: Record<string, { label: string; tone: TagTone }> = {
  executed: { label: "Applied", tone: "ok" },
  failed: { label: "Not applied", tone: "hi" },
  rejected: { label: "Dismissed", tone: "lo" },
  expired: { label: "Expired", tone: "lo" },
};

function ReviewDialog({
  items,
  onClose,
  onDone,
}: {
  items: Action[];
  onClose: () => void;
  onDone: (updated: Proposal[]) => void;
}) {
  const { toast } = useToast();
  const [previews, setPreviews] = useState<Record<string, ProposalPreview | "loading">>(() =>
    Object.fromEntries(items.map((a) => [a.proposal_id!, "loading" as const])),
  );
  const [notes, setNotes] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      items.filter((a) => a.note != null).map((a) => [a.proposal_id!, a.note ?? ""]),
    ),
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [started, setStarted] = useState(false);
  if (!started) {
    setStarted(true);
    for (const a of items)
      void previewProposal(a.proposal_id!)
        .then((p) => setPreviews((x) => ({ ...x, [a.proposal_id!]: p })))
        .catch((e: unknown) =>
          setPreviews((x) => ({
            ...x,
            [a.proposal_id!]: {
              ok: false,
              error: e instanceof ApiError ? e.message : "Couldn't check this suggestion.",
              lines: [],
              rows: [],
              warnings: [],
              proposal: {} as Proposal,
            },
          })),
        );
  }
  const ready = items.filter((a) => {
    const p = previews[a.proposal_id!];
    return p && p !== "loading" && p.ok;
  });
  const loading = Object.values(previews).some((p) => p === "loading");
  const apply = async () => {
    setBusy(true);
    setError(null);
    try {
      const out = await approveProposals(
        ready.map((a) => ({
          id: a.proposal_id!,
          payload_hash: (previews[a.proposal_id!] as ProposalPreview).proposal.payload_hash,
          note: a.proposal_id! in notes ? notes[a.proposal_id!] : undefined,
        })),
      );
      const ok = out.filter((p) => p.status === "executed").length;
      toast({
        title:
          ok === out.length
            ? `Applied ${ok} change${ok === 1 ? "" : "s"}`
            : `Applied ${ok} of ${out.length}`,
        description: out.find((p) => p.status === "failed")?.result?.error as string | undefined,
        tone: ok === out.length ? undefined : "error",
      });
      onDone(out);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't apply. Try again.");
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      open
      onOpenChange={(o) => !o && !busy && onClose()}
      title="Review before applying"
      description="Each change was checked again against your live data. Nothing changes until you confirm."
      width={640}
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="pill" size="md" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={() => void apply()} disabled={busy || loading || ready.length === 0}>
            {busy
              ? "Applying…"
              : `Confirm and apply${ready.length > 1 ? ` (${ready.length})` : ""}`}
          </Button>
        </div>
      }
    >
      <ul className="m-0 flex list-none flex-col gap-3 p-0">
        {items.map((a) => {
          const p = previews[a.proposal_id!];
          return (
            <li
              key={a.id}
              className="flex flex-col gap-2 rounded-card border border-line p-3"
              aria-label={a.label}
            >
              <span className="text-[14px] font-semibold text-ink">{a.label}</span>
              {p === "loading" || !p ? (
                <span className="text-[13px] text-muted">Checking against live data…</span>
              ) : !p.ok ? (
                <p role="alert" className="m-0 text-[13px] text-hi">
                  {p.error}
                </p>
              ) : (
                <>
                  {p.lines.map((l) => (
                    <p key={l} className="m-0 text-[13px] text-ink-2">
                      {l}
                    </p>
                  ))}
                  {p.rows.length > 0 && (
                    <table className="w-full border-collapse text-[13px]">
                      <thead>
                        <tr className="text-left text-muted">
                          <th className="py-1 font-medium" />
                          <th className="py-1 text-right font-medium">Now</th>
                          <th className="py-1 text-right font-medium">After</th>
                        </tr>
                      </thead>
                      <tbody>
                        {p.rows.map((r) => (
                          <tr key={r.k} className="border-t border-divider">
                            <td className="py-1">{r.k}</td>
                            <td className="py-1 text-right">{r.now}</td>
                            <td className="py-1 text-right font-semibold">{r.then}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                  {p.warnings.map((w) => (
                    <p key={w} className="m-0 text-[12px] text-md">
                      ⚠ {w}
                    </p>
                  ))}
                  {a.proposal_id! in notes && (
                    <label className="flex flex-col gap-1 text-[12px] font-medium text-ink-3">
                      Note (you can edit it)
                      <textarea
                        value={notes[a.proposal_id!]}
                        onChange={(e) =>
                          setNotes((x) => ({ ...x, [a.proposal_id!]: e.target.value }))
                        }
                        rows={2}
                        className="rounded-md border border-line-input px-2 py-1.5 text-[13px] font-normal text-ink"
                      />
                    </label>
                  )}
                </>
              )}
            </li>
          );
        })}
      </ul>
      {error && (
        <p role="alert" className="m-0 text-[13px] text-hi">
          {error}
        </p>
      )}
    </Modal>
  );
}

/** Recommended actions: tick, review (re-checked live), confirm. Statuses stay with the conversation. */
export function ActionsCard({
  actions,
  onChange,
}: {
  actions: Action[];
  onChange: (a: Action[]) => void;
}) {
  const [picked, setPicked] = useState<string[]>([]);
  const [review, setReview] = useState(false);
  const pending = actions.filter(
    (a) => a.proposal_id && (a.status ?? "pending") === "pending" && a.allowed,
  );
  const isPlan = actions.some((a) => a.kind === "plan_fix" || a.kind === "plan_sequence");
  const chosen = pending.filter((a) => picked.includes(a.id));
  return (
    <section
      aria-label="Recommended actions"
      className="flex flex-col gap-2 rounded-card border border-bl-line bg-bl-bg/50 p-4"
    >
      <div className="flex items-center justify-between gap-3">
        <h3 className="m-0 flex items-center gap-2 text-[14px] font-semibold text-ink">
          <span aria-hidden="true">✦</span>Recommended actions
        </h3>
        <Button size="sm" disabled={chosen.length === 0} onClick={() => setReview(true)}>
          {isPlan ? "Apply to plan" : "Apply"}
          {chosen.length > 1 ? ` (${chosen.length})` : ""}
        </Button>
      </div>
      <ul className="m-0 flex list-none flex-col gap-2 p-0">
        {actions.map((a) => {
          const st = STATUS[a.status ?? ""];
          const open = pending.includes(a);
          return (
            <li key={a.id} className="flex flex-col gap-0.5">
              <div className="flex items-start justify-between gap-3">
                <label
                  className={`flex items-start gap-2 text-[13px] text-ink-2 ${open ? "cursor-pointer" : ""}`}
                >
                  <input
                    type="checkbox"
                    disabled={!open}
                    checked={open && picked.includes(a.id)}
                    onChange={(e) =>
                      setPicked((x) =>
                        e.target.checked ? [...x, a.id] : x.filter((y) => y !== a.id),
                      )
                    }
                    className="mt-0.5"
                  />
                  <span>
                    <span className="font-semibold text-ink">{a.label}</span>
                    {a.detail && <span>: {a.detail}</span>}
                  </span>
                </label>
                <span className="flex shrink-0 items-center gap-2">
                  {st && (
                    <Tag tone={st.tone} size="sm">
                      {st.label}
                    </Tag>
                  )}
                  {a.proposal_id && !a.allowed && (a.status ?? "pending") === "pending" && (
                    <Tag tone="lo" size="sm">
                      Needs {a.needs}
                    </Tag>
                  )}
                  {open && (
                    <button
                      type="button"
                      onClick={() =>
                        void rejectProposal(a.proposal_id!).then((p) =>
                          onChange(mergeProposals(actions, [p])),
                        )
                      }
                      className="cursor-pointer text-[12px] text-muted hover:text-ink"
                    >
                      Dismiss
                    </button>
                  )}
                </span>
              </div>
              {a.result?.summary && (
                <span className="pl-6 text-[12px] text-ok">
                  ✓ {a.result.summary}
                  {a.result.href && (
                    <>
                      {" · "}
                      <Link to={a.result.href} className="text-link">
                        Open
                      </Link>
                    </>
                  )}
                </span>
              )}
              {a.result?.error && (
                <span className="pl-6 text-[12px] text-hi">{a.result.error}</span>
              )}
            </li>
          );
        })}
      </ul>
      <p className="m-0 text-[12px] text-muted">
        Nothing changes until you review and confirm. Each change is checked again against live data
        first.
      </p>
      {review && (
        <ReviewDialog
          items={chosen}
          onClose={() => setReview(false)}
          onDone={(out) => {
            setReview(false);
            setPicked([]);
            onChange(mergeProposals(actions, out));
          }}
        />
      )}
    </section>
  );
}

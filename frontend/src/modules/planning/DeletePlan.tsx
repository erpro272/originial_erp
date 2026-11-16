import { ApiError } from "@/api/client";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { useDeletePlan } from "./api";

/** Confirm, then delete. The plan disappears from every screen; a trace stays in the audit log. */
export function DeletePlanDialog({
  plan,
  onClose,
  onDeleted,
}: {
  plan: { id: string; number: string; status: string };
  onClose: () => void;
  onDeleted?: () => void;
}) {
  const del = useDeletePlan();
  const { toast } = useToast();
  const working = plan.status === "draft" || plan.status === "generated";
  return (
    <Modal
      open
      tone="danger"
      onOpenChange={(o) => !o && onClose()}
      title={`Delete ${plan.number}?`}
      description={
        working
          ? "It disappears from the plans list and its orders go back to Orders received (accepted, not in planning). A record that you deleted it stays in the audit log."
          : "It disappears from the plans list. A record that you deleted it stays in the audit log."
      }
      footer={
        <>
          <Button variant="pill" onClick={onClose}>
            Keep it
          </Button>
          <Button
            disabled={del.isPending}
            onClick={async () => {
              try {
                await del.mutateAsync(plan.id);
                toast({ title: `${plan.number} deleted`, tone: "success" });
                onClose();
                onDeleted?.();
              } catch (e) {
                toast({
                  title: e instanceof ApiError ? e.message : "Couldn't delete the plan.",
                  tone: "error",
                });
              }
            }}
          >
            Delete plan
          </Button>
        </>
      }
    />
  );
}

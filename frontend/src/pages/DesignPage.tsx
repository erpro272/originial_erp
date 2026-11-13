/**
 * Component gallery: every shared component in one place, for checking against the
 * mockups. Development builds only (not routed in production). Values are samples.
 */
import { useState } from "react";
import { AssistantBadge, AssistantCallout } from "@/components/ui/AssistantBadge";
import { Button, Caret } from "@/components/ui/Button";
import { Card, CardHeader, SectionLabel } from "@/components/ui/Card";
import { EmptyState, ErrorState } from "@/components/ui/EmptyState";
import { SearchBox, TextField } from "@/components/ui/Field";
import { KpiStrip } from "@/components/ui/KpiStrip";
import { Menu, MenuContent, MenuItem, MenuTrigger, TipRow, Tooltip } from "@/components/ui/Menu";
import { Modal } from "@/components/ui/Modal";
import { PageHeader } from "@/components/ui/PageHeader";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { LoadingState, Skeleton } from "@/components/ui/Skeleton";
import { StepTabs } from "@/components/ui/Tabs";
import { Tag } from "@/components/ui/Tag";
import { useToast } from "@/components/ui/Toast";

function Block({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-3.5">
      <SectionLabel>{title}</SectionLabel>
      {children}
    </section>
  );
}

export function DesignPage() {
  const [mode, setMode] = useState<"plan" | "compare">("plan");
  const [step, setStep] = useState("1");
  const [modal, setModal] = useState(false);
  const [search, setSearch] = useState("");
  const { toast } = useToast();

  return (
    <>
      <PageHeader
        title="Design system"
        subtitle="Shared components and tokens from the mockups. Sample values, development only."
        aside={
          <SegmentedControl
            label="Plan view"
            value={mode}
            onChange={setMode}
            options={[
              { value: "plan", label: "Original plan" },
              { value: "compare", label: "Plan comparison" },
            ]}
          />
        }
      />
      <Block title="KPI strip">
        <KpiStrip
          items={[
            { label: "Open orders", value: 12 },
            { label: "High priority", value: 5, tone: "hi" },
            { label: "In production", value: 4, tone: "bl" },
            { label: "Ship in 7 days", value: 4, tone: "md" },
          ]}
        />
        <KpiStrip
          loading
          items={[
            { label: "Loading KPI", value: 0 },
            { label: "Another", value: 0 },
          ]}
        />
      </Block>
      <Block title="Tags">
        <div className="flex flex-wrap gap-2">
          <Tag tone="hi">High priority</Tag>
          <Tag tone="md">Medium</Tag>
          <Tag tone="lo">Low</Tag>
          <Tag tone="ok">Feasible</Tag>
          <Tag tone="bl">Main plan</Tag>
          <Tag tone="hi" size="lg">
            2 bottlenecks
          </Tag>
          <Tag tone="ok" size="sm">
            small
          </Tag>
        </div>
      </Block>
      <Block title="Buttons">
        <div className="flex flex-wrap items-center gap-2">
          <Button>+ New order</Button>
          <Button variant="dark" size="sm">
            Raise PO
          </Button>
          <Button variant="pill">
            All customers <Caret />
          </Button>
          <Button variant="ghost">Ghost</Button>
          <Button variant="danger">Continue anyway</Button>
          <Button disabled>Disabled</Button>
          <SearchBox
            label="Search orders"
            placeholder="Search orders"
            value={search}
            onChange={setSearch}
          />
        </div>
      </Block>
      <Block title="Step tabs">
        <StepTabs
          label="Plan steps"
          active={step}
          onSelect={setStep}
          steps={[
            { id: "1", label: "Selected orders" },
            { id: "2", label: "Proposed manufacturing sequence", changed: true },
            { id: "3", label: "Production schedule", locked: true },
            { id: "4", label: "Resource feasibility", locked: true },
          ]}
        />
      </Block>
      <Block title="Cards">
        <div className="grid grid-cols-1 gap-5 md:grid-cols-3">
          <Card accent="hi" className="flex flex-col gap-3.5 p-[22px]">
            <div className="flex items-center justify-between">
              <span className="font-mono text-sm font-semibold">ORD-0000</span>
              <Tag tone="hi">High priority</Tag>
            </div>
            <span className="text-lg font-semibold">Sample card (hi accent)</span>
          </Card>
          <Card accent="md" className="p-[22px]">
            Amber accent
          </Card>
          <Card className="p-[22px]">Default</Card>
        </div>
        <Card>
          <CardHeader
            title="Machine capacity"
            suffix="13 – 30 Nov"
            actions={<Tag tone="hi">Overloaded</Tag>}
          />
        </Card>
      </Block>
      <Block title="Assistant">
        <div className="flex gap-2">
          <AssistantBadge>Planning assistant</AssistantBadge>
        </div>
        <AssistantCallout label="Summary">
          Assistant summaries appear in this purple callout.
        </AssistantCallout>
      </Block>
      <Block title="Overlays">
        <div className="flex flex-wrap gap-2">
          <Button variant="pill" onClick={() => setModal(true)}>
            Open modal
          </Button>
          <Button
            variant="pill"
            onClick={() => toast({ title: "Reordered · 1 bottleneck cleared", tone: "success" })}
          >
            Show toast
          </Button>
          <Menu>
            <MenuTrigger asChild>
              <Button variant="pill">
                Menu <Caret />
              </Button>
            </MenuTrigger>
            <MenuContent align="start">
              <MenuItem>First</MenuItem>
              <MenuItem>Second</MenuItem>
            </MenuContent>
          </Menu>
          <Tooltip
            content={
              <>
                <b className="mb-1 block">Hover card</b>
                <TipRow label="Machine" value="CNC 01" />
                <TipRow label="Due" value="18 Nov" />
              </>
            }
          >
            <Button variant="pill">Hover me</Button>
          </Tooltip>
        </div>
        <Modal
          open={modal}
          onOpenChange={setModal}
          tone="danger"
          title="Moving this order creates bottlenecks"
          description="Here's what changes if you continue."
          footer={
            <>
              <Button variant="pill" onClick={() => setModal(false)}>
                Cancel
              </Button>
              <Button variant="dark" onClick={() => setModal(false)}>
                Continue anyway
              </Button>
            </>
          }
        >
          <p className="m-0 text-sm text-ink-2">Modal body.</p>
        </Modal>
      </Block>
      <Block title="Form field">
        <div className="grid max-w-md gap-3">
          <TextField label="Email" placeholder="name@company.com" />
          <TextField
            label="GSTIN"
            error="GSTIN checksum is invalid"
            defaultValue="27AAACT2727Q1Z0"
          />
        </div>
      </Block>
      <Block title="States">
        <EmptyState
          title="No plan generated yet"
          description="Generate a plan to see this step."
          actions={<Button>Generate plan →</Button>}
        />
        <ErrorState message="Could not load orders." onRetry={() => undefined} />
        <LoadingState />
        <Skeleton className="h-4 w-48" />
      </Block>
    </>
  );
}

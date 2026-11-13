import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { Button } from "./Button";
import { KpiStrip } from "./KpiStrip";
import { Modal } from "./Modal";
import { SegmentedControl } from "./SegmentedControl";
import { StepTabs } from "./Tabs";
import { Tag } from "./Tag";

test.each([
  ["hi", "text-hi", "bg-hi-bg"],
  ["md", "text-md", "bg-md-bg"],
  ["lo", "text-lo", "bg-lo-bg"],
  ["ok", "text-ok", "bg-ok-bg"],
  ["bl", "text-bl", "bg-bl-bg"],
] as const)("Tag tone %s keeps colour and size classes", (tone, text, bg) => {
  render(<Tag tone={tone}>x</Tag>);
  const el = screen.getByText("x");
  expect(el).toHaveClass(text, bg, "text-xs", "rounded-full");
});

test("KpiStrip shows label/value pairs and loading skeletons", () => {
  const items = [
    { label: "Open orders", value: 12 },
    { label: "Ship in 7 days", value: 4, tone: "md" as const },
  ];
  const { rerender } = render(<KpiStrip items={items} />);
  const dd = screen.getByText("4");
  expect(dd.tagName).toBe("DD");
  expect(dd).toHaveClass("text-md", "text-[26px]");
  expect(screen.getByText("Open orders").tagName).toBe("DT");
  rerender(<KpiStrip items={items} loading />);
  expect(screen.queryByText("12")).not.toBeInTheDocument();
});

test("SegmentedControl: click and arrow keys change selection", async () => {
  function Demo() {
    const [v, setV] = useState<"a" | "b">("a");
    return (
      <SegmentedControl
        label="View"
        value={v}
        onChange={setV}
        options={[
          { value: "a", label: "Current" },
          { value: "b", label: "Past" },
        ]}
      />
    );
  }
  render(<Demo />);
  const user = userEvent.setup();
  expect(screen.getByRole("tab", { name: "Current" })).toHaveAttribute("aria-selected", "true");
  await user.click(screen.getByRole("tab", { name: "Past" }));
  expect(screen.getByRole("tab", { name: "Past" })).toHaveAttribute("aria-selected", "true");
  screen.getByRole("tab", { name: "Past" }).focus();
  await user.keyboard("{ArrowRight}");
  expect(screen.getByRole("tab", { name: "Current" })).toHaveAttribute("aria-selected", "true");
});

test("StepTabs marks locked and changed steps", () => {
  render(
    <StepTabs
      label="Plan steps"
      active="1"
      onSelect={() => {}}
      steps={[
        { id: "1", label: "Selected orders" },
        { id: "2", label: "Sequence", changed: true },
        { id: "3", label: "Schedule", locked: true },
      ]}
    />,
  );
  expect(screen.getByRole("tab", { name: /Schedule/ })).toHaveAttribute("aria-disabled", "true");
  expect(screen.getByLabelText("changed")).toBeInTheDocument();
});

test("Modal traps focus, has an accessible name and closes on Escape", async () => {
  function Demo() {
    const [open, setOpen] = useState(false);
    return (
      <>
        <Button onClick={() => setOpen(true)}>Open</Button>
        <Modal
          open={open}
          onOpenChange={setOpen}
          title="Reordering creates bottlenecks"
          tone="danger"
        >
          <Button>Continue anyway</Button>
        </Modal>
      </>
    );
  }
  render(<Demo />);
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "Open" }));
  const dialog = screen.getByRole("dialog", { name: "Reordering creates bottlenecks" });
  expect(dialog).toContainElement(document.activeElement as HTMLElement);
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

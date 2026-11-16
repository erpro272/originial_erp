import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ProductionPage } from "./ProductionPage";

test("factory layout: hovering a station or a stage shows its numbers", async () => {
  render(<ProductionPage />);
  expect(screen.getByRole("heading", { level: 1, name: "Factory Layout" })).toBeInTheDocument();
  expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();

  fireEvent.mouseEnter(screen.getByLabelText("Packaging Area"));
  let tip = screen.getByRole("tooltip");
  expect(within(tip).getByText("Running")).toBeInTheDocument();
  expect(within(tip).getByText("620 units/hr")).toBeInTheDocument();
  expect(within(tip).getByText("96%")).toBeInTheDocument();
  fireEvent.mouseLeave(screen.getByLabelText("Packaging Area"));
  expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();

  // a stage (keyboard focus works too)
  fireEvent.focus(screen.getAllByLabelText("Stage 2: Processing")[0]!);
  tip = screen.getByRole("tooltip");
  expect(within(tip).getByText("Issue")).toBeInTheDocument();
  expect(within(tip).getByText("470 units/hr")).toBeInTheDocument();
});

test("status view marks every station with its status", async () => {
  render(<ProductionPage />);
  expect(
    screen.queryByText("Maintenance", { selector: "[data-area] span" }),
  ).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("tab", { name: "Status View" }));
  const loading = screen.getByLabelText("Loading");
  expect(within(loading).getByText("Maintenance")).toBeInTheDocument();
});

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Text } from "./AssistantPage";

describe("assistant text formatting", () => {
  it("renders headings, numbered steps across blank lines, bullets, tables and inline styles without HTML", () => {
    const md = [
      "### How to fix it",
      "1. Open **Purchasing**",
      "",
      "2. Click `Raise PO`",
      "- a *note*",
      "",
      "| Option | Cost |",
      "|---|---|",
      "| Express | ₹6,200 |",
      "---",
      "<b>not html</b>",
    ].join("\n");
    const { container } = render(<Text text={md} />);
    expect(screen.getByRole("heading", { name: "How to fix it" })).toBeInTheDocument();
    const ol = container.querySelector("ol")!;
    expect(ol.querySelectorAll("li")).toHaveLength(2); // the blank line didn't split the steps
    expect(screen.getByText("Purchasing").tagName).toBe("STRONG");
    expect(screen.getByText("Raise PO").tagName).toBe("CODE");
    expect(screen.getByText("note").tagName).toBe("EM");
    expect(screen.getByRole("columnheader", { name: "Option" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "₹6,200" })).toBeInTheDocument();
    expect(container.querySelector("b")).toBeNull();
    expect(screen.getByText("<b>not html</b>")).toBeInTheDocument();
  });
});

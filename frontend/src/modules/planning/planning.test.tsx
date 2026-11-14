import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { Flash } from "./bits";
import { plural, range } from "./format";
import { machineTone } from "./api";

test("helpers: plural, date ranges, stable machine colours", () => {
  expect(plural(1, "day")).toBe("1 day");
  expect(plural(3, "day")).toBe("3 days");
  expect(range("2026-11-13", "2026-11-24")).toBe("13–24 Nov");
  expect(range("2026-11-28", "2026-12-02")).toBe("28 Nov – 2 Dec");
  expect(machineTone("b", ["a", "b"])).toBe(machineTone("b", ["a", "b"]));
  expect(machineTone("a", ["a", "b"])).not.toBe(machineTone("b", ["a", "b"]));
});

test("Flash highlights a value only after it changes", () => {
  const { rerender } = render(<Flash value={1}>₹1 L</Flash>);
  expect(screen.getByText("₹1 L").className).not.toContain("animate-flash");
  rerender(<Flash value={2}>₹2 L</Flash>);
  expect(screen.getByText("₹2 L").className).toContain("animate-flash");
});

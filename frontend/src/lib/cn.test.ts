import { cn } from "./cn";

test("custom colour tokens are not confused with font sizes", () => {
  expect(cn("text-[26px] font-bold", "text-md")).toBe("text-[26px] font-bold text-md");
  expect(cn("bg-md-bg text-xs", "text-md").split(" ").sort()).toEqual([
    "bg-md-bg",
    "text-md",
    "text-xs",
  ]);
  expect(cn("text-ink", "text-hi")).toBe("text-hi");
});

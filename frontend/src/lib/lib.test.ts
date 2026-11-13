import { toCsv } from "./csv";
import { count, initials, rupees, rupeesCompact } from "./format";

test("money formatting from integer paise (Indian grouping)", () => {
  expect(rupees(50_00_000_00)).toBe("50,00,000");
  expect(rupeesCompact(50_00_000_00)).toBe("₹50.0 L");
  expect(rupeesCompact(18_400_00)).toBe("₹18,400");
  expect(rupeesCompact(-20_000_00)).toBe("−₹20,000");
  expect(rupeesCompact(1_20_00_000_00)).toBe("₹1.2 Cr");
  expect(count(120000)).toBe("1,20,000");
});

test("initials", () => expect(initials("Asha Rao")).toBe("AR"));

test("csv escapes quotes/commas and neutralises formulas", () => {
  expect(
    toCsv(
      ["a", "b"],
      [
        ['He said "hi"', "x,y"],
        ["=SUM(A1)", null],
      ],
    ),
  ).toBe('a,b\r\n"He said ""hi""","x,y"\r\n\'=SUM(A1),');
});

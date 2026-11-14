/** Small date/text helpers for the Planning screens. */

/** Mockup day header "Fri 13". */
export function dayParts(iso: string): { dow: string; day: number; sun: boolean } {
  const d = new Date(`${iso}T00:00:00`);
  return {
    dow: d.toLocaleDateString("en-GB", { weekday: "short" }),
    day: d.getDate(),
    sun: d.getDay() === 0,
  };
}

/** "13–24 Nov" */
export function range(a?: string | null, b?: string | null): string {
  if (!a || !b) return "–";
  const da = new Date(`${a}T00:00:00`);
  const db = new Date(`${b}T00:00:00`);
  const m = (d: Date) => d.toLocaleDateString("en-GB", { month: "short" });
  return m(da) === m(db)
    ? `${da.getDate()}–${db.getDate()} ${m(db)}`
    : `${da.getDate()} ${m(da)} – ${db.getDate()} ${m(db)}`;
}

export function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

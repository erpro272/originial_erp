/** Small date/text helpers for the Planning screens. Dates are ISO "YYYY-MM-DD" (local calendar days). */

export function isoDay(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export function addDays(iso: string, n: number): string {
  const d = new Date(`${iso}T00:00:00`);
  d.setDate(d.getDate() + n);
  return isoDay(d);
}

/** Every day from a to b inclusive. */
export function daysBetween(a: string, b: string): string[] {
  const out: string[] = [];
  for (let d = a; d <= b && out.length < 400; d = addDays(d, 1)) out.push(d);
  return out;
}

/** "Fri", 13, Sunday? */
export function dayParts(iso: string): { dow: string; day: number; sun: boolean } {
  const d = new Date(`${iso}T00:00:00`);
  return {
    dow: d.toLocaleDateString("en-GB", { weekday: "short" }),
    day: d.getDate(),
    sun: d.getDay() === 0,
  };
}

/** "13–24 Nov" or "28 Nov – 2 Dec" */
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

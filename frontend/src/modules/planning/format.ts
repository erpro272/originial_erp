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

/** "today, 19:58" / "yesterday, 09:10" / "13 Nov, 19:58" */
export function generatedLabel(at: string, now: Date = new Date()): string {
  const d = new Date(at);
  const time = d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  const day = isoDay(d);
  if (day === isoDay(now)) return `today, ${time}`;
  const y = new Date(now);
  y.setDate(y.getDate() - 1);
  if (day === isoDay(y)) return `yesterday, ${time}`;
  return `${d.toLocaleDateString("en-GB", { day: "numeric", month: "short" })}, ${time}`;
}

/** "different lines, same days" / "both need CNC 01, which causes the overload". */
export function groupReason(
  g: { orders: string[]; shared: string[]; conflict: string[] },
  rows: { id: string; machines: string[] }[],
): string {
  const m = g.conflict[0] ?? g.shared[0];
  if (!m) return "different lines, same days";
  const users = g.orders.filter((id) => rows.find((r) => r.id === id)?.machines.includes(m)).length;
  const who = users === 2 ? "both need" : `${users} orders need`;
  return g.conflict.length
    ? `${who} ${m}, which causes the overload`
    : `${who} ${m}, one after the other`;
}

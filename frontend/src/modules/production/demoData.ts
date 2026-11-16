/**
 * DEMO DATA ONLY (owner's request, 2026-11-16): the Production tab is a frontend preview of the Factory Layout
 * mockup. Nothing here comes from the API yet; every number below is a placeholder until the Production backend
 * is built. Kept in this one file so it is easy to replace with real queries.
 */

export type StationStatus = "running" | "idle" | "maintenance" | "issue";
export type StageKey = "s1" | "s2" | "s3" | "utility";

/** Position on the floor plan, in plan units (the plan is 1000 x 420). */
export interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface AreaStats {
  status: StationStatus;
  output: number; // units / hr
  target: number; // units / hr
  uptime: number; // %
  note?: string;
}

export interface Station extends AreaStats {
  id: string;
  name: string;
  stage: StageKey;
  box: Box;
  kind?: "store" | "process" | "goods" | "loading";
}

export interface Stage extends AreaStats {
  key: Exclude<StageKey, "utility">;
  code: string;
  name: string;
  zone: Box;
  badge: Box;
}

export const DEMO_NOTICE = "Demo data: the Production backend isn't connected yet.";

export const KPIS = [
  {
    key: "util",
    label: "Overall Utilization",
    value: "78%",
    delta: "+4%",
    tone: "ok",
    trend: [52, 55, 50, 58, 54, 60, 57, 63, 59, 66, 70, 68, 74, 78],
  },
  {
    key: "wip",
    label: "In Progress",
    value: "142",
    unit: "units",
    tone: "bl",
    trend: [120, 118, 126, 122, 130, 127, 124, 133, 138, 131, 136, 140, 137, 142],
  },
  {
    key: "cycle",
    label: "Avg. Cycle Time",
    value: "2.8",
    unit: "hrs",
    tone: "ai",
    trend: [3.4, 3.2, 3.3, 3.0, 3.1, 2.9, 3.2, 3.0, 2.8, 3.0, 2.9, 2.7, 2.9, 2.8],
  },
  {
    key: "delayed",
    label: "Delayed Stations",
    value: "1",
    tone: "hi",
    trend: [2, 1, 1, 2, 3, 2, 1, 1, 2, 2, 1, 2, 1, 1],
  },
] as const;

export const STAGES: Stage[] = [
  {
    key: "s1",
    code: "S1",
    name: "Stage 1: Prep",
    zone: { x: 128, y: 62, w: 238, h: 240 },
    badge: { x: 166, y: 14, w: 160, h: 28 },
    status: "running",
    output: 640,
    target: 650,
    uptime: 92,
  },
  {
    key: "s2",
    code: "S2",
    name: "Stage 2: Processing",
    zone: { x: 393, y: 62, w: 238, h: 240 },
    badge: { x: 418, y: 14, w: 186, h: 28 },
    status: "issue",
    output: 470,
    target: 600,
    uptime: 78,
    note: "Cooking & Mixing is behind target",
  },
  {
    key: "s3",
    code: "S3",
    name: "Stage 3: Finishing",
    zone: { x: 658, y: 62, w: 272, h: 240 },
    badge: { x: 700, y: 14, w: 172, h: 28 },
    status: "running",
    output: 610,
    target: 600,
    uptime: 85,
  },
];

export const UTILITY: AreaStats = { status: "running", output: 0, target: 0, uptime: 70 };

export const STATIONS: Station[] = [
  {
    id: "general",
    name: "General Store",
    stage: "s1",
    kind: "store",
    box: { x: 10, y: 44, w: 84, h: 262 },
    status: "running",
    output: 700,
    target: 700,
    uptime: 99,
  },
  {
    id: "raw",
    name: "Raw Material Store",
    stage: "s1",
    kind: "store",
    box: { x: 140, y: 76, w: 98, h: 62 },
    status: "running",
    output: 660,
    target: 650,
    uptime: 98,
  },
  {
    id: "receiving",
    name: "Receiving & Sorting",
    stage: "s1",
    box: { x: 252, y: 76, w: 100, h: 62 },
    status: "running",
    output: 645,
    target: 650,
    uptime: 94,
  },
  {
    id: "handling",
    name: "Material Handling",
    stage: "s1",
    box: { x: 140, y: 158, w: 98, h: 56 },
    status: "idle",
    output: 0,
    target: 400,
    uptime: 88,
    note: "Waiting for the next batch",
  },
  {
    id: "wash",
    name: "Container Wash",
    stage: "s1",
    box: { x: 252, y: 158, w: 100, h: 56 },
    status: "running",
    output: 610,
    target: 650,
    uptime: 90,
  },
  {
    id: "finished",
    name: "Finished Products Area",
    stage: "s2",
    box: { x: 405, y: 76, w: 214, h: 56 },
    status: "running",
    output: 590,
    target: 600,
    uptime: 93,
  },
  {
    id: "cooking",
    name: "Cooking & Mixing Facilities",
    stage: "s2",
    box: { x: 448, y: 180, w: 128, h: 74 },
    status: "issue",
    output: 470,
    target: 600,
    uptime: 71,
    note: "Temperature drift on mixer 2",
  },
  {
    id: "packaging",
    name: "Packaging Area",
    stage: "s3",
    box: { x: 670, y: 76, w: 164, h: 84 },
    status: "running",
    output: 620,
    target: 600,
    uptime: 96,
  },
  {
    id: "fgs",
    name: "Final Goods Store",
    stage: "s3",
    kind: "goods",
    box: { x: 848, y: 76, w: 80, h: 92 },
    status: "running",
    output: 600,
    target: 600,
    uptime: 99,
  },
  {
    id: "loading",
    name: "Loading",
    stage: "s3",
    kind: "loading",
    box: { x: 878, y: 196, w: 118, h: 86 },
    status: "maintenance",
    output: 0,
    target: 550,
    uptime: 64,
    note: "Dock leveller service due in 30 mins",
  },
  {
    id: "boilers",
    name: "Boilers & Toilets",
    stage: "utility",
    box: { x: 154, y: 334, w: 154, h: 46 },
    status: "running",
    output: 0,
    target: 0,
    uptime: 97,
  },
  {
    id: "showers",
    name: "Showers & Toilets",
    stage: "utility",
    box: { x: 308, y: 334, w: 158, h: 46 },
    status: "running",
    output: 0,
    target: 0,
    uptime: 100,
  },
  {
    id: "lab",
    name: "Laboratory",
    stage: "utility",
    box: { x: 466, y: 334, w: 160, h: 46 },
    status: "running",
    output: 0,
    target: 0,
    uptime: 95,
  },
  {
    id: "chem",
    name: "Chemical Store",
    stage: "utility",
    box: { x: 626, y: 334, w: 140, h: 46 },
    status: "maintenance",
    output: 0,
    target: 0,
    uptime: 60,
    note: "Stock check in progress",
  },
  {
    id: "wc",
    name: "W.C.",
    stage: "utility",
    box: { x: 766, y: 334, w: 70, h: 46 },
    status: "running",
    output: 0,
    target: 0,
    uptime: 100,
  },
];

export const SECTIONS = [
  { label: "Stage 1", value: 92, tone: "ok", trend: [80, 84, 82, 79, 85, 88, 84, 90, 86, 92] },
  { label: "Stage 2", value: 78, tone: "bl", trend: [70, 74, 72, 76, 71, 75, 80, 77, 82, 78] },
  { label: "Stage 3", value: 85, tone: "ai", trend: [78, 80, 77, 82, 84, 80, 86, 83, 88, 85] },
  { label: "Utility", value: 70, tone: "md", trend: [64, 66, 63, 68, 65, 62, 67, 72, 69, 70] },
] as const;

export const ALERTS = [
  { tone: "hi", title: "Stage 3 : Prep", text: "Maintenance due in 30 mins", at: "12:15 PM" },
  { tone: "bl", title: "Packaging Area", text: "Output back to normal", at: "11:50 AM" },
] as const;

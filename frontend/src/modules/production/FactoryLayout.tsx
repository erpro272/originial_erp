import { useState, type CSSProperties, type ReactNode } from "react";
import { cn } from "@/lib/cn";
import { STATUS } from "./status";
import { STAGES, STATIONS, UTILITY, type AreaStats, type Box } from "./demoData";

/** The floor plan is drawn in a 1000 x 420 unit space; boxes are placed in % of it so it scales. */
const W = 1000;
const H = 420;
const at = ({ x, y, w, h }: Box): CSSProperties => ({
  left: `${(x / W) * 100}%`,
  top: `${(y / H) * 100}%`,
  width: `${(w / W) * 100}%`,
  height: `${(h / H) * 100}%`,
});

const STAGE_TONE = {
  s1: {
    zone: "bg-bl-bg/70",
    badge: "bg-primary",
    head: "bg-load-ink/80",
    box: "border-bl-line bg-bl-bg",
  },
  s2: { zone: "bg-te-bg/70", badge: "bg-te", head: "bg-te/80", box: "border-te-line bg-white/70" },
  s3: { zone: "bg-md-bg/50", badge: "bg-ok", head: "bg-ok/80", box: "border-ok bg-ok-bg" },
} as const;

type Hover = { id: string; title: string; stats: AreaStats; box: Box; stage?: boolean };

/** The hover card from the mockup: status, current output, target, uptime. */
function HoverCard({ h }: { h: Hover }) {
  const s = STATUS[h.stats.status];
  const below = h.box.y + h.box.h * 0.75 + 200 < H;
  const right = h.box.x > 720;
  const style: CSSProperties = {
    ...(right
      ? { right: `${((W - h.box.x - h.box.w * 0.6) / W) * 100}%` }
      : { left: `${((h.box.x + Math.min(h.box.w * 0.12, 30)) / W) * 100}%` }),
    ...(below
      ? { top: `${((h.box.y + h.box.h * 0.75) / H) * 100}%` }
      : { bottom: `${((H - h.box.y - h.box.h * 0.25) / H) * 100}%` }),
  };
  const rate = h.stats.target > 0;
  return (
    <div
      role="tooltip"
      id="factory-hover"
      style={style}
      className="pointer-events-none absolute z-20 w-[230px] rounded-card border border-line bg-white p-4 shadow-[0_12px_32px_rgb(15_23_42/0.16)]"
    >
      <div className="flex items-center gap-2 text-[15px] font-semibold text-ink">
        <CubeIcon className="size-4 text-ink-2" />
        {h.title}
      </div>
      <span
        className={cn(
          "mt-1.5 inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-semibold",
          s.tag,
        )}
      >
        <span className={cn("size-1.5 rounded-full", s.dot)} />
        {s.label}
      </span>
      <dl className="mt-3 grid grid-cols-[1fr_auto] gap-x-4 gap-y-1.5 text-[12px]">
        {rate && (
          <>
            <dt className="text-muted">Current Output</dt>
            <dd className="m-0 text-ink">{h.stats.output} units/hr</dd>
            <dt className="text-muted">Target</dt>
            <dd className="m-0 text-ink">{h.stats.target} units/hr</dd>
          </>
        )}
        <dt className="text-muted">Uptime</dt>
        <dd className="m-0 text-ink">{h.stats.uptime}%</dd>
      </dl>
      {h.stats.note && <p className="m-0 mt-2 text-[12px] text-ink-3">{h.stats.note}</p>}
      <div className="mt-3 border-t border-divider pt-2.5 text-[13px] font-medium text-link">
        View Details →
      </div>
    </div>
  );
}

function Hoverable({
  h,
  onHover,
  className,
  style,
  children,
}: {
  h: Hover;
  onHover: (h: Hover | null) => void;
  className?: string;
  style?: CSSProperties;
  children: ReactNode;
}) {
  return (
    <div
      tabIndex={0}
      aria-label={h.title}
      aria-describedby="factory-hover"
      data-area={h.id}
      onMouseEnter={(e) => {
        e.stopPropagation();
        onHover(h);
      }}
      onMouseLeave={() => onHover(null)}
      onFocus={() => onHover(h)}
      onBlur={() => onHover(null)}
      className={cn(
        "absolute outline-none focus-visible:ring-2 focus-visible:ring-primary",
        className,
      )}
      style={style}
    >
      {children}
    </div>
  );
}

export function FactoryLayout({ view }: { view: "layout" | "status" }) {
  const [hover, setHover] = useState<Hover | null>(null);
  const [zoneHover, setZoneHover] = useState<Hover | null>(null);
  const shown = hover ?? zoneHover;
  const statusView = view === "status";

  return (
    <div className="relative mx-auto aspect-[1000/420] w-full min-w-[960px] select-none">
      {/* walls, flow arrows, machine icons */}
      <svg
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        className="absolute inset-0 size-full"
        aria-hidden="true"
      >
        <defs>
          <marker
            id="fl-arrow"
            viewBox="0 0 8 8"
            refX="7"
            refY="4"
            markerWidth="6"
            markerHeight="6"
            orient="auto"
          >
            <path d="M0 0 L8 4 L0 8 z" className="fill-subtle" />
          </marker>
          <pattern
            id="fl-hatch"
            width="6"
            height="6"
            patternUnits="userSpaceOnUse"
            patternTransform="rotate(90)"
          >
            <line x1="0" y1="0" x2="0" y2="6" className="stroke-faint" strokeWidth="2" />
          </pattern>
        </defs>
        <g className="fill-none stroke-ink-3" strokeWidth="4" vectorEffect="non-scaling-stroke">
          <path d="M2 404 V36 H100 V2 H968 V28 H998 V196" vectorEffect="non-scaling-stroke" />
          <path d="M998 282 V404 H760" vectorEffect="non-scaling-stroke" />
          <path d="M660 404 H330" vectorEffect="non-scaling-stroke" />
          <path d="M150 404 H2" vectorEffect="non-scaling-stroke" />
        </g>
        <g className="fill-none stroke-ink-3" strokeWidth="1.5">
          <path d="M100 36 V60 M968 28 V60" vectorEffect="non-scaling-stroke" />
        </g>
        <rect x="878" y="196" width="118" height="86" fill="url(#fl-hatch)" />
        <g className="fill-none stroke-subtle" strokeWidth="1.2" strokeDasharray="4 4">
          {[
            "M94 175 H126",
            "M238 107 H250",
            "M302 138 V156",
            "M366 104 H403",
            "M366 240 H392",
            "M631 104 H668",
            "M631 240 H656",
            "M834 118 H846",
          ].map((d) => (
            <path key={d} d={d} markerEnd="url(#fl-arrow)" vectorEffect="non-scaling-stroke" />
          ))}
          <path
            d="M512 136 V176"
            markerStart="url(#fl-arrow)"
            markerEnd="url(#fl-arrow)"
            vectorEffect="non-scaling-stroke"
          />
        </g>
        {/* machines under stage 1, tanks either side of Cooking & Mixing */}
        <g className="fill-surface-2 stroke-subtle" strokeWidth="1.2">
          <rect x="176" y="250" width="24" height="24" rx="3" vectorEffect="non-scaling-stroke" />
          <rect x="261" y="250" width="24" height="24" rx="2" vectorEffect="non-scaling-stroke" />
          <rect x="316" y="250" width="24" height="24" rx="2" vectorEffect="non-scaling-stroke" />
          <rect x="402" y="196" width="24" height="56" rx="4" vectorEffect="non-scaling-stroke" />
          <rect x="598" y="196" width="24" height="56" rx="4" vectorEffect="non-scaling-stroke" />
        </g>
      </svg>

      {/* stage zones (hover = stage data) */}
      {STAGES.map((st) => {
        const h: Hover = { id: st.key, title: st.name, stats: st, box: st.zone, stage: true };
        return (
          <Hoverable
            key={st.key}
            h={h}
            onHover={setZoneHover}
            className={cn("rounded-[4px]", STAGE_TONE[st.key].zone)}
            style={at(st.zone)}
          >
            <span className="sr-only">{st.name}</span>
          </Hoverable>
        );
      })}
      {STAGES.map((st) => (
        <Hoverable
          key={`${st.key}-badge`}
          h={{ id: `${st.key}-badge`, title: st.name, stats: st, box: st.badge, stage: true }}
          onHover={setHover}
          className={cn(
            "flex items-stretch overflow-hidden rounded-md text-white shadow-sm",
            STAGE_TONE[st.key].head,
          )}
          style={at(st.badge)}
        >
          <span
            className={cn(
              "flex items-center px-2.5 text-[17px] font-bold",
              STAGE_TONE[st.key].badge,
            )}
          >
            {st.code}
          </span>
          <span className="flex items-center px-3 text-[13px] font-semibold whitespace-nowrap">
            {st.name}
          </span>
        </Hoverable>
      ))}

      {/* utility strip */}
      <div
        className="absolute rounded-[4px] border border-faint bg-white"
        style={at({ x: 40, y: 334, w: 796, h: 46 })}
      />
      <Hoverable
        h={{
          id: "utility",
          title: "Utility",
          stats: UTILITY,
          box: { x: 46, y: 338, w: 96, h: 38 },
        }}
        onHover={setHover}
        className="flex items-center justify-center rounded-md bg-bl-bg text-[15px] font-semibold text-ink"
        style={at({ x: 48, y: 340, w: 92, h: 34 })}
      >
        Utility
      </Hoverable>

      {/* stations */}
      {STATIONS.map((s) => {
        const tint = statusView ? STATUS[s.status].tint : null;
        const base =
          s.stage === "utility"
            ? "border-l border-faint bg-transparent"
            : s.kind === "store" && s.id === "general"
              ? "border border-ink-3 bg-white"
              : s.kind === "goods"
                ? "rounded-md border border-ai-line bg-ai-bg"
                : s.kind === "loading"
                  ? "border-l border-faint bg-transparent"
                  : s.id === "cooking"
                    ? "rounded-md border border-hi-line bg-hi-bg"
                    : s.id === "packaging"
                      ? "rounded-md border-2 border-ok bg-ok-bg"
                      : cn("rounded-md border", STAGE_TONE[s.stage].box);
        const active = shown?.id === s.id;
        return (
          <Hoverable
            key={s.id}
            h={{ id: s.id, title: s.name, stats: s, box: s.box }}
            onHover={setHover}
            className={cn(
              "flex flex-col items-center justify-center gap-1 px-2 text-center text-[13px] leading-tight font-medium text-ink transition-shadow",
              base,
              tint && s.stage !== "utility" && s.kind !== "loading" && cn("border-2", tint),
              active && "shadow-[0_6px_18px_rgb(15_23_42/0.14)]",
            )}
            style={at(s.box)}
          >
            {s.id === "packaging" && <CubeIcon className="size-5 text-ink-2" />}
            {s.stage === "utility" ? (
              <span className="flex items-center gap-2">
                <UtilityIcon id={s.id} />
                {s.name}
              </span>
            ) : (
              <span className={cn(s.kind === "loading" && "rounded bg-white/90 px-1.5 py-0.5")}>
                {s.name}
              </span>
            )}
            {statusView && (
              <span className="flex items-center gap-1 text-[11px] font-semibold text-ink-3">
                <span className={cn("size-2 rounded-full", STATUS[s.status].dot)} />
                {STATUS[s.status].label}
              </span>
            )}
          </Hoverable>
        );
      })}

      {shown && <HoverCard h={shown} />}
    </div>
  );
}

export function CubeIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={className}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      aria-hidden="true"
    >
      <path d="M12 2.5 20.5 7v10L12 21.5 3.5 17V7z" strokeLinejoin="round" />
      <path d="M3.5 7 12 11.5 20.5 7M12 11.5v10" strokeLinejoin="round" />
    </svg>
  );
}

function UtilityIcon({ id }: { id: string }) {
  const p = {
    viewBox: "0 0 24 24",
    className: "size-4 shrink-0 text-ink-3",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.7,
    "aria-hidden": true,
  } as const;
  if (id === "lab")
    return (
      <svg {...p}>
        <path d="M9 3h6M10 3v6l-5 10a1.5 1.5 0 0 0 1.4 2h11.2a1.5 1.5 0 0 0 1.4-2L14 9V3" />
      </svg>
    );
  if (id === "chem")
    return (
      <svg {...p}>
        <path d="M12 3 21 8l-9 5-9-5zM3 12l9 5 9-5M3 16l9 5 9-5" strokeLinejoin="round" />
      </svg>
    );
  if (id === "showers")
    return (
      <svg {...p}>
        <path d="M5 11a7 7 0 0 1 14 0zM12 4V2M8 14v1M12 14v2M16 14v1M10 18v1M14 18v1M12 21v1" />
      </svg>
    );
  if (id === "wc")
    return (
      <svg {...p}>
        <path d="M6 3h12v6H6zM7 9l1 9h8l1-9M9 21h6" />
      </svg>
    );
  return (
    <svg {...p}>
      <path d="M3 21V9l9-6 9 6v12zM9 21v-6h6v6M12 3v4" />
    </svg>
  );
}

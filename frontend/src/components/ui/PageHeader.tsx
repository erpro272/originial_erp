import type { ReactNode } from "react";

/** 34px page title + 16px muted subtitle, with an optional right side (KPI strip, toggle). */
export function PageHeader({
  title,
  subtitle,
  aside,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  aside?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-6">
      <div className="flex flex-col gap-2">
        <h1 className="m-0 text-[34px] font-bold tracking-[-0.02em]">{title}</h1>
        {subtitle && <p className="m-0 text-base text-muted">{subtitle}</p>}
      </div>
      {aside}
    </div>
  );
}

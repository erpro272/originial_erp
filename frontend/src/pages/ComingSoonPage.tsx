import type { ModuleNav } from "@/app/nav";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { Tag } from "@/components/ui/Tag";

export function ComingSoonPage({ module }: { module: ModuleNav }) {
  return (
    <>
      <PageHeader title={module.label} subtitle={module.description} />
      <EmptyState
        icon={
          <svg
            aria-hidden
            width="20"
            height="20"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
          >
            <circle cx="12" cy="12" r="9" />
            <path d="M12 7v5l3 2" />
          </svg>
        }
        title="Coming soon"
        description={`${module.label} is planned for ${module.plannedIn}. It will appear here as soon as it is built.`}
        actions={
          module.sections.length > 0 && (
            <div
              className="flex max-w-xl flex-wrap justify-center gap-2"
              aria-label="Planned sections"
            >
              {module.sections.map((s) => (
                <Tag key={s} tone="lo">
                  {s}
                </Tag>
              ))}
            </div>
          )
        }
      />
    </>
  );
}

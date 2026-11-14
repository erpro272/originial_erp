import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, unwrap } from "@/api/client";

/** Filters the owner can save as a named view (per user). */
export interface OrderFilters {
  scope: "current" | "past";
  customer_id: string[];
  priority: string[];
  status: string[];
  q: string;
  max_processing_days: number | null;
  ship_from: string;
  ship_to: string;
  created_from: string;
  created_to: string;
}

export const EMPTY_FILTERS: OrderFilters = {
  scope: "current",
  customer_id: [],
  priority: [],
  status: [],
  q: "",
  max_processing_days: null,
  ship_from: "",
  ship_to: "",
  created_from: "",
  created_to: "",
};

export interface SavedView {
  id: string;
  name: string;
  filters: OrderFilters;
}

interface ViewsDoc {
  views: SavedView[];
  defaultId: string | null;
}

const KEY = "orders.views";

export function useSavedViews() {
  const qc = useQueryClient();
  const query = useQuery({
    queryKey: ["prefs", KEY],
    queryFn: async () => {
      const v = unwrap(
        await api.GET("/api/me/preferences/{key}", { params: { path: { key: KEY } } }),
      ).value;
      return {
        views: (v.views as SavedView[]) ?? [],
        defaultId: (v.defaultId as string | null) ?? null,
      } as ViewsDoc;
    },
    staleTime: Infinity,
  });
  const save = useMutation({
    mutationFn: async (doc: ViewsDoc) =>
      unwrap(
        await api.PUT("/api/me/preferences/{key}", {
          params: { path: { key: KEY } },
          body: { value: doc as unknown as Record<string, unknown> },
        }),
      ),
    onMutate: (doc) => qc.setQueryData(["prefs", KEY], doc),
  });
  const doc = query.data ?? { views: [], defaultId: null };
  return {
    loaded: query.isSuccess || query.isError,
    views: doc.views,
    defaultId: doc.defaultId,
    add: (name: string, filters: OrderFilters) => {
      const view = {
        id: `v${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}`,
        name: name.trim(),
        filters,
      };
      save.mutate({ ...doc, views: [...doc.views, view] });
      return view;
    },
    remove: (id: string) =>
      save.mutate({
        views: doc.views.filter((v) => v.id !== id),
        defaultId: doc.defaultId === id ? null : doc.defaultId,
      }),
    setDefault: (id: string | null) => save.mutate({ ...doc, defaultId: id }),
  };
}

export function activeFilterCount(f: OrderFilters): number {
  return (
    f.customer_id.length +
    f.priority.length +
    f.status.length +
    (f.max_processing_days ? 1 : 0) +
    (f.ship_from || f.ship_to ? 1 : 0) +
    (f.created_from || f.created_to ? 1 : 0)
  );
}

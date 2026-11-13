import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { RequireAuth, RequirePermission } from "@/auth/guards";
import { AppShell } from "@/components/layout/AppShell";
import { LoadingState } from "@/components/ui/Skeleton";
import { AuditLogPage } from "@/pages/AuditLogPage";
import { ComingSoonPage } from "@/pages/ComingSoonPage";
import { LoginPage } from "@/pages/LoginPage";
import { NotFoundPage } from "@/pages/NotFoundPage";
import { MODULES } from "./nav";

const DesignPage = import.meta.env.DEV
  ? lazy(() => import("@/pages/DesignPage").then((m) => ({ default: m.DesignPage })))
  : null;

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        element={
          <RequireAuth>
            <AppShell />
          </RequireAuth>
        }
      >
        <Route index element={<Navigate to="/orders" replace />} />
        {/* Modules not built yet show "Coming soon". Features replace these one by one. */}
        {MODULES.map((m) => (
          <Route key={m.key} path={`${m.path}/*`} element={<ComingSoonPage module={m} />} />
        ))}
        <Route
          path="/settings/audit-log"
          element={
            <RequirePermission permission="audit.read">
              <AuditLogPage />
            </RequirePermission>
          }
        />
        {DesignPage && (
          <Route
            path="/_design"
            element={
              <Suspense fallback={<LoadingState />}>
                <DesignPage />
              </Suspense>
            }
          />
        )}
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}

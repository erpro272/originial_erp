import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import type { Permission } from "@/api/client";
import { EmptyState } from "@/components/ui/EmptyState";
import { LoadingState } from "@/components/ui/Skeleton";
import { useAuth } from "./AuthContext";

export function RequireAuth({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  const location = useLocation();
  if (status === "loading") return <LoadingState label="Signing you in…" />;
  if (status === "signed-out")
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  return <>{children}</>;
}

export function RequirePermission({
  permission,
  children,
}: {
  permission: Permission;
  children: ReactNode;
}) {
  const { can, me } = useAuth();
  if (!can(permission))
    return (
      <EmptyState
        title="You don't have access to this page"
        description={`Your role (${me?.role ?? "unknown"}) can't open it. Ask the owner if you need access.`}
      />
    );
  return <>{children}</>;
}

import { Link } from "react-router-dom";
import { buttonVariants } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";

export function NotFoundPage() {
  return (
    <EmptyState
      title="Page not found"
      description="The page you opened doesn't exist or has moved."
      actions={
        <Link to="/orders" className={buttonVariants({ variant: "pill", size: "pill" })}>
          Go to Orders
        </Link>
      }
    />
  );
}

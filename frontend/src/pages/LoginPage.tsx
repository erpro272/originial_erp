import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { z } from "zod";
import { ApiError } from "@/api/client";
import { BRAND_NAME } from "@/app/brand";
import { useAuth } from "@/auth/AuthContext";
import { Button } from "@/components/ui/Button";
import { TextField } from "@/components/ui/Field";

const schema = z.object({
  email: z.email("Enter a valid email address"),
  password: z.string().min(1, "Enter your password"),
});
type Form = z.infer<typeof schema>;

export function LoginPage() {
  const { login, status } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: string } | null)?.from ?? "/orders";
  const [formError, setFormError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<Form>({ resolver: zodResolver(schema) });

  if (status === "signed-in") return <Navigate to={from} replace />;

  const submit = async (values: Form) => {
    setFormError(null);
    try {
      await login(values.email, values.password);
      navigate(from, { replace: true });
    } catch (e) {
      setFormError(e instanceof ApiError ? e.message : "Could not reach the server. Try again.");
    }
  };

  return (
    <div className="grid min-h-screen place-items-center bg-surface px-4">
      <div className="flex w-full max-w-[400px] flex-col gap-6">
        <div className="flex items-center gap-2.5 text-lg font-bold">
          <span aria-hidden className="size-4 rounded-full bg-primary" />
          {BRAND_NAME}
        </div>
        <section className="flex flex-col gap-5 rounded-card border border-line bg-white p-7">
          <div className="flex flex-col gap-1.5">
            <h1 className="m-0 text-2xl font-bold tracking-[-0.02em]">Sign in</h1>
            <p className="m-0 text-sm text-muted">Use your work email and password.</p>
          </div>

          {formError && (
            <div
              role="alert"
              className="rounded-xl border border-hi-line bg-hi-wash px-3.5 py-2.5 text-sm text-hi"
            >
              {formError}
            </div>
          )}

          <form
            className="flex flex-col gap-4"
            noValidate
            onSubmit={handleSubmit((v) => submit(v))}
          >
            <TextField
              label="Email"
              type="email"
              autoComplete="username"
              autoFocus
              error={errors.email?.message}
              {...register("email")}
            />
            <TextField
              label="Password"
              type="password"
              autoComplete="current-password"
              error={errors.password?.message}
              {...register("password")}
            />
            <Button type="submit" disabled={isSubmitting}>
              {isSubmitting ? "Signing in…" : "Sign in"}
            </Button>
          </form>
        </section>
      </div>
    </div>
  );
}

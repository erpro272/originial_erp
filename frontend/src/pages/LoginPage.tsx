import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { z } from "zod";
import { ApiError, type Company } from "@/api/client";
import { BRAND_NAME } from "@/app/brand";
import { useAuth } from "@/auth/AuthContext";
import { Button } from "@/components/ui/Button";
import { TextField } from "@/components/ui/Field";
import { Tag } from "@/components/ui/Tag";

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
  const [companies, setCompanies] = useState<Company[] | null>(null);
  const [chosen, setChosen] = useState<string>("");
  const [formError, setFormError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    getValues,
    formState: { errors, isSubmitting },
  } = useForm<Form>({ resolver: zodResolver(schema) });

  if (status === "signed-in") return <Navigate to={from} replace />;

  const submit = async (values: Form, tenantId?: string) => {
    setFormError(null);
    try {
      const res = await login(values.email, values.password, tenantId);
      if (res.ok) navigate(from, { replace: true });
      else {
        setCompanies(res.companies);
        setChosen(res.companies[0]?.id ?? "");
      }
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
            <h1 className="m-0 text-2xl font-bold tracking-[-0.02em]">
              {companies ? "Choose a company" : "Sign in"}
            </h1>
            <p className="m-0 text-sm text-muted">
              {companies
                ? "Your account belongs to more than one company."
                : "Use your work email and password."}
            </p>
          </div>

          {formError && (
            <div
              role="alert"
              className="rounded-xl border border-hi-line bg-hi-wash px-3.5 py-2.5 text-sm text-hi"
            >
              {formError}
            </div>
          )}

          {companies ? (
            <form
              className="flex flex-col gap-4"
              onSubmit={async (e) => {
                e.preventDefault();
                await submit(getValues(), chosen);
              }}
            >
              <fieldset className="m-0 flex flex-col gap-2 border-0 p-0">
                <legend className="sr-only">Company</legend>
                {companies.map((c) => (
                  <label
                    key={c.id}
                    className={`flex cursor-pointer items-center gap-3 rounded-xl border px-3.5 py-3 text-sm ${
                      chosen === c.id
                        ? "border-primary bg-surface-blue shadow-[0_0_0_1px_var(--color-primary)]"
                        : "border-line"
                    }`}
                  >
                    <input
                      type="radio"
                      name="company"
                      value={c.id}
                      checked={chosen === c.id}
                      onChange={() => setChosen(c.id)}
                    />
                    <span className="flex-1 font-medium">{c.name}</span>
                    <Tag tone="lo" size="sm">
                      {c.role}
                    </Tag>
                  </label>
                ))}
              </fieldset>
              <Button type="submit" disabled={!chosen}>
                Continue
              </Button>
              <button
                type="button"
                className="cursor-pointer border-0 bg-transparent text-sm text-link"
                onClick={() => setCompanies(null)}
              >
                Use a different account
              </button>
            </form>
          ) : (
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
          )}
        </section>
      </div>
    </div>
  );
}

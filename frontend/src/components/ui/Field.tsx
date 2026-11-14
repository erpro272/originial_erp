import {
  forwardRef,
  useId,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";
import { cn } from "@/lib/cn";

/** Text input with label, hint and inline error (used with react-hook-form). */
export const TextField = forwardRef<
  HTMLInputElement,
  InputHTMLAttributes<HTMLInputElement> & { label: ReactNode; hint?: ReactNode; error?: string }
>(({ label, hint, error, className, id, ...props }, ref) => {
  const autoId = useId();
  const inputId = id ?? autoId;
  const msgId = `${inputId}-msg`;
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={inputId} className="text-[13px] font-medium text-ink-2">
        {label}
      </label>
      <input
        ref={ref}
        id={inputId}
        aria-invalid={error ? true : undefined}
        aria-describedby={error || hint ? msgId : undefined}
        className={cn(
          "min-h-10 rounded-[10px] border border-line-input bg-white px-3 text-sm text-ink outline-none placeholder:text-subtle focus:border-primary focus:ring-2 focus:ring-bl-bg",
          error && "border-hi-line focus:border-hi focus:ring-hi-bg",
          className,
        )}
        {...props}
      />
      {(error || hint) && (
        <span id={msgId} className={cn("text-xs", error ? "text-hi" : "text-muted")}>
          {error ?? hint}
        </span>
      )}
    </div>
  );
});
TextField.displayName = "TextField";

/** Pill-shaped search box from the mockup toolbar. */
export function SearchBox({
  value,
  onChange,
  placeholder = "Search",
  label,
  width = 140,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  label: string;
  width?: number;
}) {
  return (
    <label className="flex items-center gap-2 rounded-full border border-line-input px-3.5 text-[13px] text-muted">
      <svg
        aria-hidden
        width="14"
        height="14"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
      >
        <circle cx="11" cy="11" r="7" />
        <path d="m20 20-4-4" />
      </svg>
      <input
        aria-label={label}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        style={{ width }}
        className="border-0 bg-transparent py-2 font-sans text-[13px] text-ink outline-none"
      />
    </label>
  );
}

const control =
  "min-h-10 rounded-[10px] border border-line-input bg-white px-3 text-sm text-ink outline-none focus:border-primary focus:ring-2 focus:ring-bl-bg disabled:bg-surface disabled:text-muted";
const controlError = "border-hi-line focus:border-hi focus:ring-hi-bg";

function FieldShell({
  id,
  label,
  hint,
  error,
  children,
}: {
  id: string;
  label: ReactNode;
  hint?: ReactNode;
  error?: string;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-[13px] font-medium text-ink-2">
        {label}
      </label>
      {children}
      {(error || hint) && (
        <span id={`${id}-msg`} className={cn("text-xs", error ? "text-hi" : "text-muted")}>
          {error ?? hint}
        </span>
      )}
    </div>
  );
}

export const SelectField = forwardRef<
  HTMLSelectElement,
  SelectHTMLAttributes<HTMLSelectElement> & { label: ReactNode; hint?: ReactNode; error?: string }
>(({ label, hint, error, className, id, children, ...props }, ref) => {
  const autoId = useId();
  const sid = id ?? autoId;
  return (
    <FieldShell id={sid} label={label} hint={hint} error={error}>
      <select
        ref={ref}
        id={sid}
        aria-invalid={error ? true : undefined}
        aria-describedby={error || hint ? `${sid}-msg` : undefined}
        className={cn(control, "pr-8", error && controlError, className)}
        {...props}
      >
        {children}
      </select>
    </FieldShell>
  );
});
SelectField.displayName = "SelectField";

export const TextAreaField = forwardRef<
  HTMLTextAreaElement,
  TextareaHTMLAttributes<HTMLTextAreaElement> & {
    label: ReactNode;
    hint?: ReactNode;
    error?: string;
  }
>(({ label, hint, error, className, id, ...props }, ref) => {
  const autoId = useId();
  const tid = id ?? autoId;
  return (
    <FieldShell id={tid} label={label} hint={hint} error={error}>
      <textarea
        ref={ref}
        id={tid}
        rows={3}
        aria-invalid={error ? true : undefined}
        aria-describedby={error || hint ? `${tid}-msg` : undefined}
        className={cn(control, "py-2", error && controlError, className)}
        {...props}
      />
    </FieldShell>
  );
});
TextAreaField.displayName = "TextAreaField";

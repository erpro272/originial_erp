import { forwardRef, useId, type InputHTMLAttributes, type ReactNode } from "react";
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
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  label: string;
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
        className="w-[140px] border-0 bg-transparent py-2 font-sans text-[13px] text-ink outline-none"
      />
    </label>
  );
}

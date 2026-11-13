import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { forwardRef, type ButtonHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

/**
 * Buttons from the mockups:
 * - primary: blue pill (`+ New order`, `Generate plan`)
 * - dark:    ink pill (`Raise PO`, `Make main plan`)
 * - pill:    white outlined pill (filters, `Columns (8) ▾`)
 * - ghost:   text-only (icon buttons, ×)
 */
export const buttonVariants = cva(
  "inline-flex cursor-pointer items-center justify-center gap-2 rounded-full font-sans whitespace-nowrap transition-colors disabled:cursor-not-allowed disabled:opacity-50",
  {
    variants: {
      variant: {
        primary: "bg-primary font-semibold text-white hover:bg-primary-hover",
        dark: "bg-ink font-semibold text-white hover:bg-ink-2",
        pill: "border border-line-input bg-white font-medium text-ink-2 hover:border-faint",
        ghost: "font-medium text-ink-3 hover:bg-surface-2 hover:text-ink",
        danger: "bg-hi font-semibold text-white hover:opacity-90",
      },
      size: {
        md: "min-h-10 px-5 py-2.5 text-sm",
        sm: "min-h-9 px-4 py-2 text-[13px]",
        pill: "px-3.5 py-2 text-[13px]",
        icon: "size-8 p-0 text-lg",
      },
    },
    compoundVariants: [{ variant: "pill", size: "md", className: "px-3.5 py-2 text-[13px]" }],
    defaultVariants: { variant: "primary", size: "md" },
  },
);

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild, type, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp
        ref={ref}
        type={asChild ? undefined : (type ?? "button")}
        className={cn(
          buttonVariants({ variant, size: size ?? (variant === "pill" ? "pill" : "md") }),
          className,
        )}
        {...props}
      />
    );
  },
);
Button.displayName = "Button";

/** "All customers ▾" style trigger. */
export const Caret = () => (
  <span aria-hidden className="text-[10px] leading-none">
    ▾
  </span>
);

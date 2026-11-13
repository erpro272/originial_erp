import { cva, type VariantProps } from "class-variance-authority";
import type { HTMLAttributes } from "react";
import { cn } from "@/lib/cn";

/** Soft status tags: hi (red), md (amber), lo (grey), ok (green), bl (blue). */
export const tagVariants = cva(
  "inline-flex items-center rounded-full font-semibold whitespace-nowrap",
  {
    variants: {
      tone: {
        hi: "bg-hi-bg text-hi",
        md: "bg-md-bg text-md",
        lo: "bg-lo-bg text-lo",
        ok: "bg-ok-bg text-ok",
        bl: "bg-bl-bg text-bl",
      },
      size: {
        md: "px-2.5 py-1 text-xs",
        sm: "px-2 py-[3px] text-[11px]",
        lg: "px-3 py-1.5 text-[13px]",
      },
    },
    defaultVariants: { tone: "lo", size: "md" },
  },
);

export type TagTone = NonNullable<VariantProps<typeof tagVariants>["tone"]>;

export function Tag({
  tone,
  size,
  className,
  ...props
}: HTMLAttributes<HTMLSpanElement> & VariantProps<typeof tagVariants>) {
  return <span className={cn(tagVariants({ tone, size }), className)} {...props} />;
}

/** Text colour for inline status words in tables ("Behind", "Material short"). */
export const toneText: Record<TagTone, string> = {
  hi: "text-hi",
  md: "text-md",
  lo: "text-ink",
  ok: "text-ok",
  bl: "text-bl",
};

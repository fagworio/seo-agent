import * as React from "react";

export function Input({
  className = "",
  ...props
}: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={`h-9 w-full rounded-[7px] border border-[var(--border)] bg-[var(--surface)] px-3 text-sm ` +
        `placeholder:text-[var(--muted-foreground)] focus-visible:outline-none ` +
        `focus-visible:ring-2 focus-visible:ring-[var(--primary)] ${className}`}
      {...props}
    />
  );
}

"use client";

import { useState, type ReactNode } from "react";

export const COLORS = {
  bg: "#0b0b0f",
  panel: "#111216",
  border: "#1f2937",
  borderStrong: "#374151",
  text: "#e5e7eb",
  muted: "#9ca3af",
  faint: "#6b7280",
  blue: "#60a5fa",
  blueStrong: "#2563eb",
  green: "#34d399",
  red: "#f87171",
  amber: "#fbbf24",
};

export const inputClass =
  "w-full rounded-lg border border-[#374151] bg-[#0b0b0f] px-2.5 py-1.5 text-sm text-[#e5e7eb] outline-none focus:border-[#60a5fa] focus-visible:ring-1 focus-visible:ring-[#60a5fa]";

export function Card({
  title,
  right,
  children,
  className = "",
}: {
  title?: string;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`rounded-2xl border border-[#1f2937] bg-[#111216] p-4 sm:p-5 ${className}`}>
      {(title || right) && (
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          {title && <h2 className="m-0 text-base font-semibold text-[#e5e7eb]">{title}</h2>}
          {right}
        </div>
      )}
      {children}
    </section>
  );
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-[#9ca3af]">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-[11px] leading-snug text-[#6b7280]">{hint}</span>}
    </label>
  );
}

const clamp = (n: number, min?: number, max?: number) =>
  Math.min(max ?? Infinity, Math.max(min ?? -Infinity, n));

/**
 * Numeric input that lets the user type freely ("-", "1.", empty) and only
 * pushes valid, range-clamped numbers upward.
 */
export function NumInput({
  value,
  onChange,
  min,
  max,
  prefix,
  suffix,
  ariaLabel,
}: {
  value: number;
  onChange: (n: number) => void;
  min?: number;
  max?: number;
  prefix?: string;
  suffix?: string;
  ariaLabel?: string;
}) {
  const [text, setText] = useState<string | null>(null);
  const shown = text ?? String(Math.round(value * 1000) / 1000);
  return (
    <div className="relative">
      {prefix && (
        <span className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-sm text-[#6b7280]">
          {prefix}
        </span>
      )}
      <input
        type="text"
        inputMode="decimal"
        aria-label={ariaLabel}
        value={shown}
        onFocus={(e) => e.currentTarget.select()}
        onChange={(e) => {
          const raw = e.target.value;
          setText(raw);
          const parsed = parseFloat(raw.replace(/,/g, ""));
          if (Number.isFinite(parsed)) onChange(clamp(parsed, min, max));
        }}
        onBlur={() => setText(null)}
        className={`${inputClass} ${prefix ? "pl-6" : ""} ${suffix ? "pr-9" : ""} text-right tabular-nums`}
      />
      {suffix && (
        <span className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-xs text-[#6b7280]">
          {suffix}
        </span>
      )}
    </div>
  );
}

export function Disclosure({
  title,
  badge,
  defaultOpen = false,
  children,
}: {
  title: string;
  badge?: string;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  return (
    <details open={defaultOpen} className="group border-t border-[#1f2937] first:border-t-0">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 py-3 text-sm font-semibold text-[#e5e7eb] [&::-webkit-details-marker]:hidden">
        <span>{title}</span>
        <span className="flex items-center gap-2">
          {badge && (
            <span className="rounded-full bg-[#1f2937] px-2 py-0.5 text-[11px] font-medium text-[#9ca3af]">
              {badge}
            </span>
          )}
          <span aria-hidden className="text-[#6b7280] transition-transform group-open:rotate-90">
            ›
          </span>
        </span>
      </summary>
      <div className="space-y-3 pb-4">{children}</div>
    </details>
  );
}

export function GhostButton({
  children,
  onClick,
  disabled,
  title,
  danger,
}: {
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  title?: string;
  danger?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={`rounded-lg border px-2.5 py-1 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
        danger
          ? "border-[#7f1d1d] text-[#fecaca] hover:bg-[#2a0f14]"
          : "border-[#374151] text-[#d1d5db] hover:bg-[#1f2937]"
      }`}
    >
      {children}
    </button>
  );
}

"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { API_BASE } from "./cashflow/lib";

const TABS = [
  { href: "/cashflow", label: "Cash Flow" },
  { href: "/models", label: "Models" },
  { href: "/data", label: "Data" },
];

export default function TabNav() {
  const pathname = usePathname();
  // Tells people when they are looking at the built-in demo data instead of their own.
  const [mode, setMode] = useState<"sample" | "custom" | null>(null);
  useEffect(() => {
    let alive = true;
    const load = () =>
      fetch(`${API_BASE}/data/status`)
        .then((r) => (r.ok ? r.json() : null))
        .then((j) => alive && j && setMode(j.mode === "custom" ? "custom" : "sample"))
        .catch(() => {});
    load();
    window.addEventListener("nf-data-changed", load); // the Data page fires this after it loads or removes data
    return () => {
      alive = false;
      window.removeEventListener("nf-data-changed", load);
    };
  }, []);
  return (
    <nav
      aria-label="Main"
      className="sticky top-0 z-20 border-b border-[#1f2937] bg-[#0b0b0f]/95 backdrop-blur"
    >
      <div className="mx-auto flex max-w-[1600px] items-center gap-1 px-4 sm:px-6">
        <span className="mr-4 py-3 text-sm font-bold tracking-wide text-white">NEURAFLOW</span>
        {TABS.map((tab) => {
          const active = pathname.startsWith(tab.href);
          return (
            <Link
              key={tab.href}
              href={tab.href}
              aria-current={active ? "page" : undefined}
              className={`-mb-px border-b-2 px-3 py-3 text-sm font-medium transition-colors ${
                active
                  ? "border-[#3b82f6] text-white"
                  : "border-transparent text-[#9ca3af] hover:text-[#e5e7eb]"
              }`}
            >
              {tab.label}
            </Link>
          );
        })}
        {mode && (
          <Link
            href="/data"
            className={`ml-auto rounded-full px-2.5 py-1 text-[11px] font-semibold ${mode === "sample" ? "bg-[#2b1d07] text-[#fbbf24]" : "bg-[#052e22] text-[#34d399]"}`}
            title={mode === "sample" ? "You are looking at built-in sample data. Connect your own on the Data page." : "Using the data you connected."}
          >
            {mode === "sample" ? "Sample data" : "Your data"}
          </Link>
        )}
      </div>
    </nav>
  );
}

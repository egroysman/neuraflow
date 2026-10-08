"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const TABS = [
  { href: "/cashflow", label: "Cash Flow" },
];

export default function TabNav() {
  const pathname = usePathname();
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
      </div>
    </nav>
  );
}

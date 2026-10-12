"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "./AuthProvider";

const TABS = [
  { href: "/cashflow", label: "Cash Flow" },
  { href: "/models", label: "Models" },
  { href: "/data", label: "Data" },
];

export default function TabNav() {
  const pathname = usePathname();
  const { ready, required, session, status, signOut } = useAuth();
  if (pathname.startsWith("/welcome")) return null; // the public site has its own header
  const signedIn = !!session;
  const tabs = TABS.filter((t) => t.href !== "/data" || !session || session.legacy || session.role === "admin");
  // Says plainly whether numbers are the demo data, the customer's own, or not there yet.
  const pill = !status ? null : status.empty ? "empty" : status.mode === "custom" ? "custom" : "sample";
  return (
    <nav
      aria-label="Main"
      className="sticky top-0 z-20 border-b border-[#1f2937] bg-[#0b0b0f]/95 backdrop-blur"
    >
      <div className="mx-auto flex max-w-[1600px] items-center gap-1 px-4 sm:px-6">
        <span className="mr-4 py-3 text-sm font-bold tracking-wide text-white">NEURAFLOW</span>
        {(signedIn || !required) && tabs.map((tab) => {
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
        <div className="ml-auto flex items-center gap-3">
          {pill && (
            <Link
              href="/data"
              className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${pill === "custom" ? "bg-[#052e22] text-[#34d399]" : "bg-[#2b1d07] text-[#fbbf24]"}`}
              title={pill === "sample" ? "You are looking at built-in sample data. Connect your own on the Data page." : pill === "empty" ? "No data connected yet." : "Using the data you connected."}
            >
              {pill === "sample" ? "Sample data" : pill === "empty" ? "No data yet" : "Your data"}
            </Link>
          )}
          {ready && session && !session.legacy && (
            <span className="hidden text-xs text-[#9ca3af] sm:inline" data-testid="workspace-label">
              {session.name} · {session.role === "admin" ? "Admin" : "Viewer"}
            </span>
          )}
          {ready && session && (!session.legacy || required) && (
            <button type="button" onClick={signOut} className="rounded-md border border-[#374151] px-2 py-1 text-xs text-[#d1d5db] hover:border-[#60a5fa]">Log out</button>
          )}
        </div>
      </div>
    </nav>
  );
}

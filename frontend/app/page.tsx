"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { useAuth } from "./AuthProvider";

// Signed-in people (and the original single-workspace mode) go straight to the app; visitors see the public site.
export default function Home() {
  const router = useRouter();
  const { ready, required, session } = useAuth();
  useEffect(() => {
    if (ready) router.replace(required && !session ? "/welcome" : "/cashflow");
  }, [ready, required, session, router]);
  return <p role="status" className="p-6 text-sm text-[#9ca3af]">Loading…</p>;
}

"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { checkKey, setKey } from "../auth";
import { inputClass } from "../cashflow/ui";

export default function SignIn() {
  const router = useRouter();
  const [value, setValue] = useState("");
  const [remember, setRemember] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit() {
    setError(null);
    setBusy(true);
    const key = value.trim();
    try {
      await checkKey(key);
      setKey(key, remember);
      router.replace("/cashflow");
    } catch (e) {
      setError((e as Error).message);
    }
    setBusy(false);
  }

  return (
    <main className="mx-auto w-full max-w-md px-4 py-16 text-[#e5e7eb]">
      <h1 className="m-0 text-2xl font-semibold">Sign in to your workspace</h1>
      <p className="mt-2 text-sm text-[#9ca3af]">Paste the access key you were sent, or open the private link you received. Each workspace holds one company&apos;s data and nobody else can see it.</p>
      <form className="mt-6 space-y-3" onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <label className="block text-sm font-medium" htmlFor="key">Access key</label>
        <input id="key" type="password" autoComplete="off" spellCheck={false} placeholder="nfk.…" className={inputClass} value={value} onChange={(e) => setValue(e.target.value)} />
        <label className="flex items-center gap-2 text-sm text-[#d1d5db]">
          <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
          Keep me signed in on this device
        </label>
        {error && <p role="alert" className="m-0 text-sm text-[#fca5a5]">{error}</p>}
        <button type="submit" disabled={!value.trim() || busy} className="w-full rounded-lg bg-[#2563eb] px-3 py-2 text-sm font-medium text-white hover:bg-[#1d4ed8] disabled:opacity-50">{busy ? "Checking…" : "Sign in"}</button>
      </form>
      <p className="mt-6 text-xs text-[#6b7280]">Lost your key? Ask whoever set up your workspace to issue a new one.</p>
    </main>
  );
}

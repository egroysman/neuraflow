"use client";

import { useRef, useState } from "react";
import { API_BASE } from "../cashflow/lib";

type Turn = { role: "user" | "assistant"; content: string };

export default function AskBox({ questions, enabled }: { questions: string[]; enabled: boolean }) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const end = useRef<HTMLDivElement>(null);

  async function ask(q: string) {
    const message = q.trim();
    if (!message || busy) return;
    setError(null);
    setBusy(true);
    const history = turns.slice(-6);
    setTurns((t) => [...t, { role: "user", content: message }]);
    setText("");
    try {
      const res = await fetch(`${API_BASE}/public/ask`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message, history }) });
      const j = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(typeof j?.detail === "string" ? j.detail : Array.isArray(j?.detail) ? "Keep questions under 500 characters." : "The assistant couldn't answer just now.");
      setTurns((t) => [...t, { role: "assistant", content: j.answer || "I don't have an answer to that. Request a demo and we'll cover it." }]);
    } catch (e) {
      setError((e as Error).message === "Failed to fetch" ? "Couldn't reach the server. Check your connection and try again." : (e as Error).message);
    }
    setBusy(false);
    setTimeout(() => end.current?.scrollIntoView({ block: "nearest" }), 50);
  }

  if (!enabled) {
    return <p className="m-0 text-[var(--muted)]">The question assistant is switched off right now. Request a demo below and we&apos;ll answer by email.</p>;
  }
  return (
    <div>
      {turns.length === 0 && (
        <ul className="m-0 mb-4 flex list-none flex-wrap gap-2 p-0">
          {questions.map((q) => (
            <li key={q}><button type="button" className="sans cursor-pointer rounded-full border border-[var(--ink)] bg-transparent px-3 py-1.5 text-sm font-medium text-[var(--ink)] hover:bg-[var(--paper-deep)]" onClick={() => ask(q)}>{q}</button></li>
          ))}
        </ul>
      )}
      <div aria-live="polite" className="space-y-4" data-testid="ask-log">
        {turns.map((t, i) =>
          t.role === "user" ? (
            <p key={i} className="sans m-0 border-l-2 border-[var(--ink)] pl-3 font-bold">{t.content}</p>
          ) : (
            <p key={i} className="m-0 max-w-[65ch] whitespace-pre-line">{t.content}</p>
          ),
        )}
        {busy && <p className="m-0 text-[var(--muted)]">Looking that up…</p>}
        <div ref={end} />
      </div>
      {error && <p role="alert" className="mb-0 mt-3 text-[var(--red)]">{error}</p>}
      <form className="mt-4 flex max-w-xl gap-2" onSubmit={(e) => { e.preventDefault(); ask(text); }}>
        <label htmlFor="ask-input" className="sr-only">Your question</label>
        <input id="ask-input" value={text} onChange={(e) => setText(e.target.value)} maxLength={500} placeholder="Ask anything about NeuraFlow" autoComplete="off" />
        <button type="submit" className="btn shrink-0" disabled={busy || !text.trim()}>Ask</button>
      </form>
      <p className="mb-0 mt-2 max-w-xl text-sm text-[var(--muted)]">Answers come from our written product description. If it isn&apos;t covered, the assistant says so. It never sees customer data. Your question is sent to an AI provider (OpenAI) to answer it.</p>
    </div>
  );
}

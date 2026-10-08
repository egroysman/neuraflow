"use client";

import { useEffect, useRef, useState } from "react";
import { askArAssistant, type ForecastBody } from "./lib";
import { SLIDER_BY_KEY, fmtSlider } from "./Panels";
import { Card } from "./ui";
import type { Adjustments } from "./types";

type Msg = { role: "user" | "assistant"; content: string; suggestions?: Partial<Record<keyof Adjustments, number>>; applied?: boolean };

const STARTERS = [
  "Who should I chase first?",
  "Which customers are most likely to pay late?",
  "What happens if my largest customer pays 30 days late?",
  "Why is cash from customers lower in some months?",
];

export function ArAssistantPanel({
  body,
  customerId,
  onClearCustomer,
  onApply,
}: {
  body: ForecastBody;
  customerId: string | null;
  onClearCustomer: () => void;
  onApply: (changes: Partial<Adjustments>) => void;
}) {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [followUps, setFollowUps] = useState<string[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "nearest" });
  }, [messages, busy]);

  async function send(text: string) {
    const message = text.trim();
    if (!message || busy) return;
    setError(null);
    setInput("");
    setFollowUps([]);
    const history = messages.map((m) => ({ role: m.role, content: m.content }));
    setMessages((m) => [...m, { role: "user", content: message }]);
    setBusy(true);
    try {
      const reply = await askArAssistant({ message, history, customer_id: customerId, forecast: body });
      const suggestions = Object.fromEntries(
        Object.entries(reply.suggested_whatifs).filter(([k]) => k in SLIDER_BY_KEY)
      ) as Partial<Record<keyof Adjustments, number>>;
      setMessages((m) => [...m, { role: "assistant", content: reply.answer, suggestions }]);
      setFollowUps(reply.follow_ups.slice(0, 3));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card
      title="Ask about your receivables"
      right={
        customerId ? (
          <button type="button" onClick={onClearCustomer} className="rounded-full border border-[#1e3a8a] bg-[#0c1a33] px-3 py-1 text-xs text-[#bfdbfe] hover:text-white">
            Focused on {customerId} ✕
          </button>
        ) : (
          <span className="text-xs text-[#6b7280]">Click a customer below to focus on them</span>
        )
      }
    >
      <p className="mb-3 text-xs text-[#9ca3af]">
        Answers use the same numbers as this page, including any what-ifs you have set. It can suggest what-if settings, and you choose whether to apply them.
      </p>

      <div className="max-h-[420px] space-y-3 overflow-y-auto pr-1" role="log" aria-live="polite" aria-label="Assistant conversation">
        {messages.length === 0 && (
          <div className="flex flex-wrap gap-2">
            {STARTERS.map((s) => (
              <button key={s} type="button" onClick={() => send(s)} className="rounded-full border border-[#1f2937] bg-[#0b0b0f] px-3 py-1.5 text-xs text-[#d1d5db] hover:border-[#3b82f6] hover:text-white">
                {s}
              </button>
            ))}
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={m.role === "user" ? "flex justify-end" : ""}>
            <div className={`max-w-[92%] whitespace-pre-wrap rounded-xl px-3 py-2 text-sm ${m.role === "user" ? "bg-[#1d4ed8] text-white" : "border border-[#1f2937] bg-[#0b0b0f] text-[#e5e7eb]"}`}>
              {m.content}
              {m.suggestions && Object.keys(m.suggestions).length > 0 && (
                <div className="mt-2 rounded-lg border border-[#1e3a8a] bg-[#0c1a33] p-2 text-xs text-[#bfdbfe]">
                  <div className="font-semibold">Suggested what-ifs</div>
                  <ul className="mt-1 space-y-0.5">
                    {Object.entries(m.suggestions).map(([k, v]) => {
                      const sl = SLIDER_BY_KEY[k as keyof Adjustments];
                      return (
                        <li key={k}>
                          {sl.label}: <strong>{fmtSlider(sl, v as number)}</strong>
                        </li>
                      );
                    })}
                  </ul>
                  <button
                    type="button"
                    disabled={m.applied}
                    onClick={() => {
                      onApply(m.suggestions!);
                      setMessages((all) => all.map((x, j) => (j === i ? { ...x, applied: true } : x)));
                    }}
                    className="mt-2 rounded-md bg-[#2563eb] px-3 py-1 font-semibold text-white disabled:bg-[#1f2937] disabled:text-[#9ca3af]"
                  >
                    {m.applied ? "Applied" : "Apply these what-ifs"}
                  </button>
                </div>
              )}
            </div>
          </div>
        ))}
        {busy && <div className="text-sm text-[#9ca3af]">Thinking…</div>}
        {error && (
          <p role="alert" className="rounded-lg border border-[#7f1d1d] bg-[#2a0f0f] px-3 py-2 text-sm text-[#fca5a5]">
            {error}
          </p>
        )}
        <div ref={endRef} />
      </div>

      {followUps.length > 0 && !busy && (
        <div className="mt-3 flex flex-wrap gap-2">
          {followUps.map((f) => (
            <button key={f} type="button" onClick={() => send(f)} className="rounded-full border border-[#1f2937] px-3 py-1 text-xs text-[#9ca3af] hover:border-[#3b82f6] hover:text-white">
              {f}
            </button>
          ))}
        </div>
      )}

      <form
        className="mt-3 flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
      >
        <label htmlFor="ar-assistant-input" className="sr-only">
          Ask a question about receivables
        </label>
        <input
          id="ar-assistant-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          maxLength={1500}
          placeholder={customerId ? `Ask about ${customerId}…` : "Ask about customers, aging or collections…"}
          className="min-w-0 flex-1 rounded-lg border border-[#1f2937] bg-[#0b0b0f] px-3 py-2 text-sm text-white placeholder:text-[#6b7280]"
        />
        <button type="submit" disabled={busy || !input.trim()} className="rounded-lg bg-[#2563eb] px-4 py-2 text-sm font-semibold text-white disabled:bg-[#1f2937] disabled:text-[#6b7280]">
          Ask
        </button>
      </form>
    </Card>
  );
}

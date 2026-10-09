"use client";

import { useEffect, useRef, useState } from "react";
import { askAssistant, type ForecastBody } from "./lib";
import { SLIDER_BY_KEY, TAB_WHATIFS, fmtSlider } from "./Panels";
import { Card } from "./ui";
import type { Adjustments, TabId } from "./types";

type Msg = { role: "user" | "assistant"; content: string; suggestions?: Partial<Record<keyof Adjustments, number>>; applied?: boolean };

const STARTERS: Record<TabId, string[]> = {
  forecast: ["When does cash get tight, and why?", "What are the biggest drivers of cash this year?", "How do the best and worst cases compare?", "What should I change to stay above my minimum?"],
  receivables: ["Who should I chase first?", "Which customers are most likely to pay late?", "What happens if my largest customer pays 30 days late?", "Why is cash from customers lower in some months?"],
  credit: ["Which customers are my biggest credit risks?", "Why does this customer score low?", "How much can I trust this score?", "What would improve the score for my slowest payers?"],
  payroll: ["Which month has the highest payroll cost and why?", "What does payroll cost by department?", "What happens if we hire 3 more people?", "How much do bonuses and benefits add?"],
  payables: ["Which vendors should I pay first?", "Which bills are overdue?", "What happens if I pay vendors 10 days later?", "Which vendor is the biggest cash risk?"],
  capex: ["What are my biggest purchases and when do they land?", "What does financing cost me in interest?", "What if I delay purchases 3 months?", "How much cash do purchases use this year?"],
  balance: ["Is the balance sheet healthy?", "How does debt change over the year?", "What happens to equity if I prepay the loan?", "Why does working capital move?"],
  gl: ["Does the ledger tie to invoices and bills?", "Where is the forecast furthest from actuals?", "Which accounts drive costs?", "What would change if starting cash is off?"],
  trends: ["What are the biggest trends in the data?", "How concentrated is revenue in a few customers?", "How seasonal is the business?", "What happens if I lose part of my largest customer?"],
};

const TITLES: Record<TabId, string> = {
  forecast: "Ask about your forecast",
  receivables: "Ask about your receivables",
  credit: "Ask about credit scores",
  payroll: "Ask about payroll",
  payables: "Ask about payables",
  capex: "Ask about capex",
  balance: "Ask about the balance sheet",
  gl: "Ask about the ledger",
  trends: "Ask about trends",
};

const FOCUSABLE: Partial<Record<TabId, string>> = { receivables: "customer", credit: "customer", payables: "vendor" };

export function TabAssistant({
  tab,
  body,
  focus,
  onClearFocus,
  onApply,
}: {
  tab: TabId;
  body: ForecastBody;
  focus: string | null;
  onClearFocus: () => void;
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
      const reply = await askAssistant({ message, history, tab, focus, forecast: body });
      const suggestions = Object.fromEntries(
        Object.entries(reply.suggested_whatifs).filter(([k]) => (TAB_WHATIFS[tab].keys as string[]).includes(k))
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
      title={TITLES[tab]}
      right={
        focus ? (
          <button type="button" onClick={onClearFocus} className="rounded-full border border-[#1e3a8a] bg-[#0c1a33] px-3 py-1 text-xs text-[#bfdbfe] hover:text-white">
            Focused on {focus} ✕
          </button>
        ) : (
          FOCUSABLE[tab] ? <span className="text-xs text-[#6b7280]">Click a {FOCUSABLE[tab]} in the table to focus on them</span> : null
        )
      }
    >
      <p className="mb-3 text-xs text-[#9ca3af]">
        Answers use the same numbers as this tab and the data loaded behind it, including any what-ifs you have set. It can suggest this tab&apos;s what-if settings, and you choose whether to apply them.
      </p>

      <div className="max-h-[420px] space-y-3 overflow-y-auto pr-1" role="log" aria-live="polite" aria-label={`${tab} assistant conversation`}>
        {messages.length === 0 && (
          <div className="flex flex-wrap gap-2">
            {STARTERS[tab].map((s) => (
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
        <label htmlFor={`assistant-input-${tab}`} className="sr-only">
          Ask a question about this tab
        </label>
        <input
          id={`assistant-input-${tab}`}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          maxLength={1500}
          placeholder={focus ? `Ask about ${focus}…` : "Ask a question about this tab…"}
          className="min-w-0 flex-1 rounded-lg border border-[#1f2937] bg-[#0b0b0f] px-3 py-2 text-sm text-white placeholder:text-[#6b7280]"
        />
        <button type="submit" disabled={busy || !input.trim()} className="rounded-lg bg-[#2563eb] px-4 py-2 text-sm font-semibold text-white disabled:bg-[#1f2937] disabled:text-[#6b7280]">
          Ask
        </button>
      </form>
    </Card>
  );
}

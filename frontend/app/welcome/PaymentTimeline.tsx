"use client";

// Days between the due date and the day each invoice was paid, for four made-up customers.
// Illustrative only: it shows what the score reads (how early or late, and how steady), not real results.
const MIN = -10;
const MAX = 45;
const LATE = 10; // matches the app's default for "late"
const pos = (d: number) => `${((d - MIN) / (MAX - MIN)) * 100}%`;

const CUSTOMERS: { name: string; verdict: string; note: string; days: number[] }[] = [
  { name: "Customer A", verdict: "Pays on time", note: "Early or on the due date, every time.", days: [-4, -3, -2, -2, -1, -1, 0, 0, 1, 1, 2, -3, -2, 0] },
  { name: "Customer B", verdict: "Drifting later", note: "Each month a little slower than the last.", days: [2, 5, 7, 9, 8, 12, 10, 14, 11, 15, 13, 17, 16, 19] },
  { name: "Customer C", verdict: "Unpredictable", note: "Anywhere from early to six weeks late.", days: [-5, 12, 30, 3, 41, 18, -2, 26, 9, 38, 22, 5, 33, 15] },
  { name: "Customer D", verdict: "Steadily 8 days late", note: "Late, but you can plan around it.", days: [6, 7, 8, 8, 9, 7, 8, 9, 8, 10, 7, 8, 9, 8] },
];
const TICKS = [-10, 0, 10, 20, 30, 40];

export default function PaymentTimeline() {
  return (
    <figure className="m-0" aria-labelledby="timeline-caption">
      <div className="sans mb-2 flex items-baseline justify-between text-sm text-[var(--muted)]">
        <span>Each dot is one paid invoice</span>
        <span>Days from due date</span>
      </div>
      <div className="relative">
        {/* grid and the late zone, drawn once behind all rows */}
        <div className="pointer-events-none absolute inset-y-0 right-0 hidden sm:block" style={{ left: "10.5rem" }} aria-hidden>
          <div className="absolute inset-y-0" style={{ left: pos(LATE), right: 0, background: "color-mix(in srgb, var(--red) 9%, transparent)" }} />
          {TICKS.map((t) => (
            <div key={t} className="absolute inset-y-0 border-l" style={{ left: pos(t), borderColor: t === 0 ? "var(--ink)" : "var(--rule)", borderLeftWidth: t === 0 ? 2 : 1 }} />
          ))}
        </div>
        <ul className="relative m-0 list-none space-y-5 p-0">
          {CUSTOMERS.map((c, row) => (
            <li key={c.name} className="grid items-center gap-x-4 gap-y-1 sm:grid-cols-[10.5rem_1fr]">
              <div className="sans">
                <p className="m-0 text-sm font-bold leading-tight">{c.name}</p>
                <p className="m-0 text-sm font-medium leading-tight text-[var(--muted)]">{c.verdict}</p>
              </div>
              <div className="relative h-8" role="img" aria-label={`${c.name}: ${c.verdict}. ${c.note}`}>
                <div className="absolute inset-x-0 top-1/2 border-t border-[var(--rule)] sm:hidden" aria-hidden />
                {c.days.map((d, i) => (
                  <span
                    key={i}
                    className="dot absolute -ml-[5px] -mt-[5px] block h-[10px] w-[10px] rounded-full"
                    style={{ left: pos(d), top: `calc(50% + ${[-6, 0, 6][i % 3]}px)`, background: d > LATE ? "var(--red)" : "var(--blue)", animationDelay: `${row * 120 + i * 35}ms`, opacity: 0.88 }}
                  />
                ))}
              </div>
            </li>
          ))}
        </ul>
        <div className="sans relative mt-3 hidden text-xs text-[var(--muted)] sm:ml-[10.5rem] sm:block" style={{ height: "1.1rem" }} aria-hidden>
          {TICKS.map((t) => (
            <span key={t} className="absolute -translate-x-1/2" style={{ left: pos(t) }}>{t === 0 ? "due" : t > 0 ? `+${t}` : t}</span>
          ))}
        </div>
      </div>
      <figcaption id="timeline-caption" className="mt-4 max-w-xl text-sm text-[var(--muted)]">
        Four made-up customers, not real data. Blue is paid within {LATE} days of the due date; red is later. The score reads how early or late a customer pays and how steady they are, so Customer D is easier to plan around than Customer C.
      </figcaption>
    </figure>
  );
}

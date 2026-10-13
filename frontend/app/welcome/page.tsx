"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { API_BASE } from "../cashflow/lib";
import { useAuth } from "../AuthProvider";
import BrandMark from "../BrandMark";
import AskBox from "./AskBox";
import DemoForm from "./DemoForm";
import LiveDemo from "./LiveDemo";
import PaymentTimeline from "./PaymentTimeline";

type Config = { demo_requests?: boolean; assistant: boolean; live_demo: boolean; suggested_questions: string[] };

const STEPS = [
  { title: "Connect your data", text: "Upload a CSV or Excel file, point NeuraFlow at Snowflake or Databricks, or drop files in an SFTP folder and let it pick up the newest one on a schedule. Access is read-only." },
  { title: "Check the match", text: "NeuraFlow suggests which of your columns are the invoice date, amount and payment date. You confirm. It checks the data and refuses to load anything that fails, so bad rows never reach a forecast." },
  { title: "Read the results", text: "Each customer gets a score with its reasons, and your cash forecast updates from how they really pay. Change an assumption and see the effect on cash." },
];

export default function Welcome() {
  const { session } = useAuth();
  const [cfg, setCfg] = useState<Config | null>(null);
  useEffect(() => {
    let alive = true;
    fetch(`${API_BASE}/public/config`).then((r) => (r.ok ? r.json() : null)).then((j) => alive && j && setCfg(j)).catch(() => {});
    return () => { alive = false; };
  }, []);

  return (
    <>
      <header className="mx-auto flex max-w-[1080px] flex-wrap items-center justify-between gap-x-6 gap-y-2 px-5 py-5 sm:px-8">
        <span className="sans flex items-center gap-2.5 text-xl font-extrabold tracking-tight">
          <BrandMark size={30} />
          NeuraFlow
        </span>
        <nav aria-label="Site" className="sans flex flex-wrap items-center gap-x-5 gap-y-1 text-[0.95rem] font-medium">
          <a href="#how">How it works</a>
          <a href="#today">Where it is today</a>
          <a href="#ask">Ask a question</a>
          {session ? <Link href="/cashflow">Open your workspace</Link> : <Link href="/signin" className="btn">Log in</Link>}
        </nav>
      </header>

      <main>
        <section className="mx-auto max-w-[1080px] px-5 pb-16 pt-8 sm:px-8 sm:pt-14">
          <div className="grid gap-12 lg:grid-cols-[1fr_1.1fr] lg:items-center">
            <div>
              <h1 className="m-0 text-[2.5rem] font-extrabold leading-[1.05] sm:text-5xl lg:text-[3.4rem]">Know who will pay you late before the invoice is due.</h1>
              <p className="mb-0 mt-5 max-w-[34rem] text-xl leading-relaxed">NeuraFlow scores each customer on how they actually pay, then builds your cash forecast from those habits. It runs on your own accounting data.</p>
              <div className="mt-7 flex flex-wrap items-center gap-3">
                <a href="#demo" className="btn">Request a demo</a>
                {cfg?.live_demo && <LiveDemo />}
              </div>
            </div>
            <PaymentTimeline />
          </div>
        </section>

        <section className="border-y border-[var(--rule)] bg-[var(--paper-deep)]">
          <div className="mx-auto grid max-w-[1080px] gap-10 px-5 py-14 sm:px-8 md:grid-cols-2">
            <div>
              <h2 className="m-0 text-2xl font-bold">A score from payment behavior</h2>
              <p className="mb-0 mt-3 max-w-[34rem]">Private companies rarely have a public credit rating. Your own invoices are the best record of how they pay. NeuraFlow reads how early or late each customer pays, whether that is getting worse, and how steady they are, and turns it into a score with plain-language reasons. A back-test replays the score at past dates and checks it against what customers did next, and you can download every scored invoice to audit it.</p>
            </div>
            <div>
              <h2 className="m-0 text-2xl font-bold">A forecast that uses those habits</h2>
              <p className="mb-0 mt-3 max-w-[34rem]">Cash, profit and loss, and the balance sheet, month by month, built from your receivables, payables, payroll and ledger. About thirty what-if controls let you test slower payers, a delayed hire or a big purchase, and each tab has an assistant that answers from the numbers you are looking at.</p>
            </div>
          </div>
        </section>

        <section id="how" className="mx-auto max-w-[1080px] scroll-mt-4 px-5 py-16 sm:px-8">
          <h2 className="m-0 text-2xl font-bold">How it works</h2>
          <ol className="m-0 mt-8 grid list-none gap-8 p-0 md:grid-cols-3">
            {STEPS.map((s, i) => (
              <li key={s.title} className="border-t-2 border-[var(--ink)] pt-4">
                <p className="sans m-0 text-3xl font-extrabold text-[var(--blue)]">{i + 1}</p>
                <h3 className="mb-0 mt-2 text-lg font-bold">{s.title}</h3>
                <p className="mb-0 mt-2">{s.text}</p>
              </li>
            ))}
          </ol>
        </section>

        <section className="border-t border-[var(--rule)]">
          <div className="mx-auto grid max-w-[1080px] gap-10 px-5 py-16 sm:px-8 md:grid-cols-[1fr_1.2fr]">
            <h2 className="m-0 text-2xl font-bold">Each company gets its own workspace</h2>
            <ul className="m-0 list-disc space-y-2 pl-5">
              <li>Your data, connections and models are held in a private workspace that no other customer can reach.</li>
              <li>People sign in with an access key. Admin keys connect and change data. Viewer keys can only look. A key can be revoked at any time.</li>
              <li>Saved passwords and tokens are encrypted, with a separate key for each workspace, and are never shown again.</li>
              <li>Connections to your warehouse are read-only, and for Snowflake and Databricks the app writes the steps for your administrator to create that read-only account.</li>
            </ul>
          </div>
        </section>

        <section id="today" className="scroll-mt-4 border-t border-[var(--rule)] bg-[var(--paper-deep)]">
          <div className="mx-auto grid max-w-[1080px] gap-10 px-5 py-16 sm:px-8 md:grid-cols-[1fr_1.2fr]">
            <h2 className="m-0 text-2xl font-bold">Where it is today</h2>
            <div className="space-y-3">
              <p className="m-0">NeuraFlow is an early product, and we would rather you hear the limits from us.</p>
              <ul className="m-0 list-disc space-y-2 pl-5">
                <li>The Snowflake, Databricks and SFTP connections are built and tested against simulated systems. We are proving them on real accounts with our first customers.</li>
                <li>Machine-learning models run quietly beside simple rules and are only trusted if they clearly beat them. On our built-in sample data they do not, and the app says so.</li>
                <li>The score describes how a business customer pays. It is a decision aid, not a consumer credit report or a lending decision, and short or small histories give weaker scores.</li>
                <li>We do not hold a SOC 2 or similar certification.</li>
              </ul>
            </div>
          </div>
        </section>

        <section id="ask" className="mx-auto max-w-[1080px] scroll-mt-4 px-5 py-16 sm:px-8">
          <h2 className="m-0 text-2xl font-bold">Ask a question</h2>
          <p className="mb-6 mt-2 max-w-[38rem] text-[var(--muted)]">Try one of these, or type your own.</p>
          <AskBox questions={cfg?.suggested_questions ?? []} enabled={cfg ? cfg.assistant : true} />
        </section>

        <section id="demo" className="scroll-mt-4 border-t border-[var(--rule)] bg-[var(--paper-deep)]">
          <div className="mx-auto max-w-[1080px] px-5 py-16 sm:px-8">
            <h2 className="m-0 text-2xl font-bold">See it on your kind of data</h2>
            <p className="mb-8 mt-2 max-w-[38rem]">Tell us where your invoices live and what you want to learn. We&apos;ll walk through it with you.</p>
            {cfg?.demo_requests === false ? <p role="status" className="m-0 max-w-xl text-lg">Demo requests aren&apos;t open yet. Please check back soon.</p> : <DemoForm />}
          </div>
        </section>
      </main>

      <footer className="mx-auto flex max-w-[1080px] flex-wrap justify-between gap-3 px-5 py-8 text-sm text-[var(--muted)] sm:px-8">
        <span>NeuraFlow is an early product.</span>
        <Link href="/signin">Customer log in</Link>
      </footer>
    </>
  );
}

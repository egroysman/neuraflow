import type { Metadata } from "next";
import { Schibsted_Grotesk, Source_Serif_4 } from "next/font/google";
import "./site.css";

const head = Schibsted_Grotesk({ variable: "--font-head", subsets: ["latin"], weight: ["500", "700", "800"] });
const body = Source_Serif_4({ variable: "--font-body", subsets: ["latin"], style: ["normal", "italic"] });

export const metadata: Metadata = {
  title: "NeuraFlow · Know who will pay you late",
  description: "Score your customers on how they actually pay, and build your cash forecast from those habits. Runs on your own accounting data.",
};

export default function SiteLayout({ children }: { children: React.ReactNode }) {
  return <div className={`site ${head.variable} ${body.variable}`}>{children}</div>;
}

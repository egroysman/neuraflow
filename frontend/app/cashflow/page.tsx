import type { Metadata } from "next";
import CashFlowApp from "./CashFlowApp";

export const metadata: Metadata = {
  title: "Cash Flow Model · NeuraFlow",
  description: "Operating cash flow forecast driven by receivables, costs, payroll and debt.",
};

export default function CashFlowPage() {
  return <CashFlowApp />;
}

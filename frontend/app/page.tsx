"use client";

import { useMemo, useState } from "react";

type HistoryItem = {
  role: "user" | "assistant";
  content: string;
};

type AIResponse = {
  confidence: number;
  is_ambiguous: boolean;
  interpretations: string[];
  restate: string;
  clarifying_question: string;
  answer: string;
  assumptions: string;
  uploaded_context?: any;
};

export default function Home() {
  const [message, setMessage] = useState<string>("");
  const [response, setResponse] = useState<AIResponse | null>(null);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [customerId, setCustomerId] = useState<string>("");
  const [file, setFile] = useState<File | null>(null);
  const [analytics, setAnalytics] = useState<any>(null);
  const [selectedCustomer, setSelectedCustomer] = useState<any>(null);

  const sendMessage = async () => {
    if (!message.trim()) return;

    const userMessage = message.trim();
    const newHistory: HistoryItem[] = [
      ...history,
      { role: "user", content: userMessage },
    ];

    setLoading(true);
    setResponse(null);

    try {
      const formData = new FormData();
      formData.append("message", userMessage);
      formData.append("history", JSON.stringify(history));

      if (customerId.trim()) {
        formData.append("customer_id", customerId.trim());
      }

      if (file) {
        formData.append("file", file);
      }

      const res = await fetch(
        "https://neuraflow-production.up.railway.app/chat-upload",
        {
          method: "POST",
          body: formData,
        }
      );

      if (!res.ok) {
        throw new Error(`Request failed: ${res.status}`);
      }

      const raw: AIResponse = await res.json();
      const uploaded = raw.uploaded_context || null;

      setAnalytics(uploaded);
      setResponse(raw);

      if (uploaded?.customer_detail) {
        setSelectedCustomer(uploaded.customer_detail);
      } else if (uploaded?.summary?.customer_detail) {
        setSelectedCustomer(uploaded.summary.customer_detail);
      } else if (!selectedCustomer && uploaded?.customer_summaries?.length) {
        setSelectedCustomer(uploaded.customer_summaries[0]);
      } else if (
        !selectedCustomer &&
        uploaded?.summary?.customer_summaries?.length
      ) {
        setSelectedCustomer(uploaded.summary.customer_summaries[0]);
      }

      const assistantText =
        raw.answer || raw.clarifying_question || raw.restate || "No response";

      const updatedHistory: HistoryItem[] = [
        ...newHistory,
        { role: "assistant", content: assistantText },
      ];

      setHistory(updatedHistory);
      setMessage("");
    } catch (error) {
      console.error(error);
      const updatedHistory: HistoryItem[] = [
        ...newHistory,
        { role: "assistant", content: "Error reaching live backend." },
      ];
      setHistory(updatedHistory);
    } finally {
      setLoading(false);
    }
  };

  const dashboardData = analytics?.summary ? analytics.summary : analytics;

  const totalAR = dashboardData?.total_invoice_amount || 0;
  const expectedCash30 =
    dashboardData?.portfolio_expected_cash_next_30_days || 0;

  const overdueAR = dashboardData
    ? Object.entries(dashboardData.aging_buckets || {}).reduce(
        (sum: number, [bucket, value]: [string, any]) =>
          bucket === "current" ? sum : sum + Number(value || 0),
        0
      )
    : 0;

  const customerCount = dashboardData?.customer_count || 0;

  const highRiskCount = dashboardData?.customer_summaries
    ? dashboardData.customer_summaries.filter(
        (c: any) => c.ml_risk_prediction === "high"
      ).length
    : 0;

  const selectedCustomerResolved = useMemo(() => {
    if (!selectedCustomer) return null;
    if (selectedCustomer.customer_id) return selectedCustomer;

    if (dashboardData?.customer_summaries?.length) {
      return dashboardData.customer_summaries.find(
        (c: any) => String(c.customer_id) === String(selectedCustomer)
      );
    }

    return null;
  }, [selectedCustomer, dashboardData]);

  const metricCardStyle: React.CSSProperties = {
    backgroundColor: "#111216",
    border: "1px solid #1f2937",
    borderRadius: "16px",
    padding: "18px",
  };

  const panelStyle: React.CSSProperties = {
    backgroundColor: "#111216",
    border: "1px solid #1f2937",
    borderRadius: "16px",
    padding: "20px",
  };

  const clickableCardStyle: React.CSSProperties = {
    padding: "12px",
    border: "1px solid #1f2937",
    borderRadius: "12px",
    marginBottom: "10px",
    backgroundColor: "#0b0b0f",
    cursor: "pointer",
  };

  const sectionLabel: React.CSSProperties = {
    color: "#9ca3af",
    fontSize: "12px",
    textTransform: "uppercase",
    letterSpacing: "0.04em",
    marginBottom: "4px",
  };

  const valueText: React.CSSProperties = {
    fontSize: "18px",
    fontWeight: 700,
  };

  return (
    <div
      style={{
        minHeight: "100vh",
        backgroundColor: "#0b0b0f",
        color: "#ffffff",
        fontFamily: "Arial, sans-serif",
        padding: "24px",
      }}
    >
      <div style={{ maxWidth: "1600px", margin: "
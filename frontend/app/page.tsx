"use client";

import { useMemo, useState } from "react";

type HistoryItem = {
  role: "user" | "assistant";
  content: string;
};

type AIResponse = {
  confidence?: number;
  is_ambiguous?: boolean;
  interpretations?: any[];
  restate?: any;
  clarifying_question?: any;
  answer?: any;
  assumptions?: any;
  uploaded_context?: any;
  error?: any;
  raw?: any;
};

const API_BASE = "https://neuraflow-production.up.railway.app";

const toDisplayText = (value: any): string => {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  return JSON.stringify(value, null, 2);
};

export default function Home() {
  const [message, setMessage] = useState<string>("");
  const [response, setResponse] = useState<AIResponse | null>(null);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [errorText, setErrorText] = useState<string>("");
  const [customerId, setCustomerId] = useState<string>("");
  const [file, setFile] = useState<File | null>(null);
  const [analytics, setAnalytics] = useState<any>(null);
  const [selectedCustomer, setSelectedCustomer] = useState<any>(null);

  const sendMessage = async (
    overrideMessage?: string,
    useDemoDataset: boolean = false
  ) => {
    const finalMessage = (overrideMessage || message).trim();
    if (!finalMessage) return;

    const newHistory: HistoryItem[] = [
      ...history,
      { role: "user", content: finalMessage },
    ];

    setLoading(true);
    setResponse(null);
    setErrorText("");

    try {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 120000);

      const formData = new FormData();
      formData.append("message", finalMessage);
      formData.append("history", JSON.stringify(history));

      if (customerId.trim()) {
        formData.append("customer_id", customerId.trim());
      }

      if (file && !useDemoDataset) {
        formData.append("file", file);
      }

      const res = await fetch(`${API_BASE}/chat-upload`, {
        method: "POST",
        body: formData,
        signal: controller.signal,
      });

      clearTimeout(timeout);

      const text = await res.text();

      if (!res.ok) {
        throw new Error(`Backend error ${res.status}: ${text}`);
      }

      let raw: AIResponse;

      try {
        raw = JSON.parse(text);
      } catch {
        throw new Error(`Invalid JSON from backend: ${text}`);
      }

      const uploaded = raw.uploaded_context || null;

      setAnalytics(uploaded);
      setResponse(raw);

      const dashboardData = uploaded?.summary ? uploaded.summary : uploaded;

      if (uploaded?.customer_detail) {
        setSelectedCustomer(uploaded.customer_detail);
      } else if (uploaded?.summary?.customer_detail) {
        setSelectedCustomer(uploaded.summary.customer_detail);
      } else if (dashboardData?.top_expected_payers_next_30_days?.length) {
        setSelectedCustomer(dashboardData.top_expected_payers_next_30_days[0]);
      } else if (dashboardData?.customer_summaries?.length) {
        setSelectedCustomer(dashboardData.customer_summaries[0]);
      }

      const assistantText = toDisplayText(
        raw.answer ||
          raw.clarifying_question ||
          raw.restate ||
          raw.error ||
          "No response"
      );

      setHistory([
        ...newHistory,
        { role: "assistant", content: assistantText },
      ]);

      setMessage("");
    } catch (error: any) {
      const msg =
        error?.name === "AbortError"
          ? "The request timed out. Try a smaller file or use the demo dataset."
          : error?.message || "Unknown error reaching live backend.";

      setErrorText(msg);

      setHistory([
        ...newHistory,
        { role: "assistant", content: msg },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const runDemo = () => {
    setFile(null);
    sendMessage(
      "Using the demo dataset, what is expected cash in the next 30 days, who are the highest risk customers, and what actions should finance take?",
      true
    );
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
      <div style={{ maxWidth: "1600px", margin: "0 auto" }}>
        <div style={{ marginBottom: "18px" }}>
          <h1 style={{ fontSize: "36px", margin: 0, fontWeight: 700 }}>
            NEURAFLOW
          </h1>
          <p style={{ color: "#9ca3af", marginTop: "6px" }}>
            Finance AI for Credit Risk + Cash Prediction
          </p>
        </div>

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1.05fr 1.85fr",
            gap: "20px",
          }}
        >
          <div style={{ display: "grid", gap: "20px" }}>
            <div style={panelStyle}>
              <h2 style={{ marginTop: 0 }}>Command Console</h2>

              <button
                onClick={runDemo}
                disabled={loading}
                style={{
                  width: "100%",
                  marginBottom: "14px",
                  padding: "13px 16px",
                  borderRadius: "12px",
                  border: "1px solid #2563eb",
                  backgroundColor: "#1d4ed8",
                  color: "#fff",
                  cursor: "pointer",
                  fontWeight: 700,
                  fontSize: "15px",
                }}
              >
                ▶ Try Demo Dataset
              </button>

              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "1fr 1fr 1fr",
                  gap: "8px",
                  marginBottom: "14px",
                }}
              >
                <button
                  onClick={() =>
                    sendMessage(
                      "Using the demo dataset, what is expected cash in the next 30 days?",
                      true
                    )
                  }
                  disabled={loading}
                  style={{
                    padding: "10px",
                    borderRadius: "10px",
                    border: "1px solid #374151",
                    backgroundColor: "#111827",
                    color: "#fff",
                    cursor: "pointer",
                  }}
                >
                  Forecast Cash
                </button>

                <button
                  onClick={() =>
                    sendMessage(
                      "Using the demo dataset, who are the highest risk customers and why?",
                      true
                    )
                  }
                  disabled={loading}
                  style={{
                    padding: "10px",
                    borderRadius: "10px",
                    border: "1px solid #374151",
                    backgroundColor: "#111827",
                    color: "#fff",
                    cursor: "pointer",
                  }}
                >
                  Show Risk
                </button>

                <button
                  onClick={() =>
                    sendMessage(
                      "Using the demo dataset, what should collections do first?",
                      true
                    )
                  }
                  disabled={loading}
                  style={{
                    padding: "10px",
                    borderRadius: "10px",
                    border: "1px solid #374151",
                    backgroundColor: "#111827",
                    color: "#fff",
                    cursor: "pointer",
                  }}
                >
                  Actions
                </button>
              </div>

              <div style={{ display: "flex", gap: "10px", marginBottom: "12px" }}>
                <input
                  id="neuraflow-message"
                  name="message"
                  style={{
                    flex: 1,
                    padding: "12px",
                    borderRadius: "10px",
                    border: "1px solid #374151",
                    backgroundColor: "#0b0b0f",
                    color: "#fff",
                    fontSize: "15px",
                  }}
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                  placeholder="Ask NEURAFLOW..."
                  onKeyDown={(e) => {
                    if (e.key === "Enter") sendMessage();
                  }}
                />

                <button
                  onClick={() => sendMessage()}
                  disabled={loading}
                  style={{
                    padding: "12px 18px",
                    borderRadius: "10px",
                    border: "none",
                    backgroundColor: "#2563eb",
                    color: "#fff",
                    cursor: "pointer",
                    fontWeight: 600,
                  }}
                >
                  {loading ? "Running..." : "Run"}
                </button>
              </div>

              <div style={{ display: "flex", gap: "10px", marginBottom: "16px" }}>
                <input
                  id="neuraflow-customer-id"
                  name="customerId"
                  style={{
                    width: "180px",
                    padding: "10px",
                    borderRadius: "10px",
                    border: "1px solid #374151",
                    backgroundColor: "#0b0b0f",
                    color: "#fff",
                  }}
                  value={customerId}
                  onChange={(e) => setCustomerId(e.target.value)}
                  placeholder="Customer ID"
                />

                <input
                  id="neuraflow-file"
                  name="file"
                  type="file"
                  accept=".csv"
                  onChange={(e) => setFile(e.target.files?.[0] || null)}
                  style={{ color: "#9ca3af" }}
                />
              </div>

              {loading && (
                <div
                  style={{
                    marginBottom: "12px",
                    padding: "10px",
                    borderRadius: "10px",
                    backgroundColor: "#111827",
                    border: "1px solid #1f2937",
                  }}
                >
                  Running analysis...
                </div>
              )}

              {errorText && (
                <div
                  style={{
                    marginBottom: "12px",
                    padding: "10px",
                    borderRadius: "10px",
                    backgroundColor: "#2a0f14",
                    border: "1px solid #7f1d1d",
                    color: "#fecaca",
                  }}
                >
                  {errorText}
                </div>
              )}

              <div
                style={{
                  border: "1px solid #1f2937",
                  borderRadius: "12px",
                  backgroundColor: "#0b0b0f",
                  minHeight: "360px",
                  maxHeight: "520px",
                  overflowY: "auto",
                  padding: "12px",
                }}
              >
                {history.length === 0 && (
                  <p style={{ color: "#6b7280" }}>
                    Start with the demo dataset or upload your own invoice CSV.
                    <br />
                    Ask: “What is expected cash in the next 30 days?”
                  </p>
                )}

                {history.map((item, i) => (
                  <div
                    key={i}
                    style={{
                      marginBottom: "10px",
                      padding: "12px",
                      borderRadius: "10px",
                      backgroundColor:
                        item.role === "user" ? "#1e293b" : "#111827",
                    }}
                  >
                    <strong>{item.role === "user" ? "You" : "NEURAFLOW"}:</strong>{" "}
                    <pre
                      style={{
                        whiteSpace: "pre-wrap",
                        fontFamily: "Arial, sans-serif",
                        margin: "8px 0 0",
                      }}
                    >
                      {item.content}
                    </pre>
                  </div>
                ))}
              </div>
            </div>

            <div style={panelStyle}>
              <h2 style={{ marginTop: 0 }}>Decision Output</h2>

              {!response && !loading && !errorText && (
                <p style={{ color: "#6b7280" }}>Awaiting analysis...</p>
              )}

              {loading && <p>Running analysis...</p>}

              {response?.answer && (
                <pre style={{ lineHeight: 1.5, whiteSpace: "pre-wrap" }}>
                  {toDisplayText(response.answer)}
                </pre>
              )}

              {response?.clarifying_question && !response?.answer && (
                <pre style={{ lineHeight: 1.5, whiteSpace: "pre-wrap" }}>
                  {toDisplayText(response.clarifying_question)}
                </pre>
              )}

              {response?.error && (
                <pre
                  style={{
                    color: "#fecaca",
                    lineHeight: 1.5,
                    whiteSpace: "pre-wrap",
                  }}
                >
                  {toDisplayText(response.error)}
                </pre>
              )}

              {response?.assumptions && (
                <pre
                  style={{
                    color: "#9ca3af",
                    marginTop: "10px",
                    lineHeight: 1.5,
                    whiteSpace: "pre-wrap",
                  }}
                >
                  Assumptions: {toDisplayText(response.assumptions)}
                </pre>
              )}

              {response?.confidence !== undefined && (
                <p style={{ color: "#9ca3af", marginTop: "10px" }}>
                  Confidence: {response.confidence}
                </p>
              )}
            </div>
          </div>

          <div style={{ display: "grid", gap: "20px" }}>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(5, 1fr)",
                gap: "16px",
              }}
            >
              <div style={metricCardStyle}>
                <div style={sectionLabel}>Total AR</div>
                <div style={{ fontSize: "24px", fontWeight: 700 }}>
                  ${Number(totalAR).toLocaleString()}
                </div>
              </div>

              <div style={metricCardStyle}>
                <div style={sectionLabel}>Overdue AR</div>
                <div style={{ fontSize: "24px", fontWeight: 700 }}>
                  ${Number(overdueAR).toLocaleString()}
                </div>
              </div>

              <div style={metricCardStyle}>
                <div style={sectionLabel}>Expected Cash 30D</div>
                <div style={{ fontSize: "24px", fontWeight: 700, color: "#34d399" }}>
                  ${Number(expectedCash30).toLocaleString()}
                </div>
              </div>

              <div style={metricCardStyle}>
                <div style={sectionLabel}>Customers</div>
                <div style={{ fontSize: "24px", fontWeight: 700 }}>
                  {customerCount}
                </div>
              </div>

              <div style={metricCardStyle}>
                <div style={sectionLabel}>High Risk Customers</div>
                <div style={{ fontSize: "24px", fontWeight: 700 }}>
                  {highRiskCount}
                </div>
              </div>
            </div>

            <div
              style={{
                display: "grid",
                gridTemplateColumns: "0.85fr 1.15fr",
                gap: "20px",
              }}
            >
              <div style={panelStyle}>
                <h2 style={{ marginTop: 0 }}>Aging Buckets</h2>

                {!dashboardData && <p style={{ color: "#6b7280" }}>No data loaded.</p>}

                {dashboardData?.aging_buckets &&
                  Object.entries(dashboardData.aging_buckets).map(
                    ([k, v]: [string, any]) => (
                      <div
                        key={k}
                        style={{
                          display: "flex",
                          justifyContent: "space-between",
                          padding: "10px 0",
                          borderBottom: "1px solid #1f2937",
                        }}
                      >
                        <span style={{ color: "#d1d5db" }}>{k}</span>
                        <strong>${Number(v).toLocaleString()}</strong>
                      </div>
                    )
                  )}
              </div>

              <div style={panelStyle}>
                <h2 style={{ marginTop: 0 }}>Top Expected Payers</h2>

                {!dashboardData?.top_expected_payers_next_30_days?.length && (
                  <p style={{ color: "#6b7280" }}>No forecast data loaded.</p>
                )}

                {dashboardData?.top_expected_payers_next_30_days
                  ?.slice(0, 5)
                  .map((c: any, i: number) => (
                    <div
                      key={i}
                      style={{
                        ...clickableCardStyle,
                        outline:
                          selectedCustomerResolved?.customer_id === c.customer_id
                            ? "1px solid #2563eb"
                            : "none",
                      }}
                      onClick={() => setSelectedCustomer(c)}
                    >
                      <div style={{ fontWeight: 700, marginBottom: "6px" }}>
                        Customer {c.customer_id}
                      </div>
                      <div>
                        Expected 30D Cash: $
                        {Number(c.predicted_amount_paid_next_30_days || 0).toLocaleString()}
                      </div>
                      <div>
                        30D Collection Rate:{" "}
                        {(
                          Number(c.predicted_collection_rate_next_30_days || 0) * 100
                        ).toFixed(1)}
                        %
                      </div>
                      <div>
                        Risk: {c.ml_risk_prediction} ({c.ml_risk_probability})
                      </div>
                    </div>
                  ))}
              </div>
            </div>

            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 1fr",
                gap: "20px",
              }}
            >
              <div style={panelStyle}>
                <h2 style={{ marginTop: 0 }}>Collections Action Queue</h2>

                {!dashboardData?.top_recommended_actions?.length && (
                  <p style={{ color: "#6b7280" }}>No actions generated yet.</p>
                )}

                {dashboardData?.top_recommended_actions
                  ?.slice(0, 5)
                  .map((c: any, i: number) => (
                    <div
                      key={i}
                      style={{
                        ...clickableCardStyle,
                        outline:
                          selectedCustomerResolved?.customer_id === c.customer_id
                            ? "1px solid #2563eb"
                            : "none",
                      }}
                      onClick={() => setSelectedCustomer(c)}
                    >
                      <div style={{ fontWeight: 700 }}>
                        Customer {c.customer_id}
                      </div>
                      <div>Action: {toDisplayText(c.recommended_action)}</div>
                      <div>Reason: {toDisplayText(c.action_reason)}</div>
                      <div>
                        Expected 30D Cash: $
                        {Number(c.predicted_amount_paid_next_30_days || 0).toLocaleString()}
                      </div>
                    </div>
                  ))}
              </div>

              <div style={panelStyle}>
                <h2 style={{ marginTop: 0 }}>Customer Drill-Down</h2>

                {!selectedCustomerResolved && (
                  <p style={{ color: "#6b7280" }}>
                    Select a customer to inspect behavior.
                  </p>
                )}

                {selectedCustomerResolved && (
                  <div style={{ display: "grid", gap: "12px" }}>
                    <div>
                      <div style={sectionLabel}>Customer</div>
                      <div style={{ fontSize: "24px", fontWeight: 700 }}>
                        {selectedCustomerResolved.customer_id}
                      </div>
                    </div>

                    <div
                      style={{
                        display: "grid",
                        gridTemplateColumns: "1fr 1fr",
                        gap: "12px",
                      }}
                    >
                      <div style={metricCardStyle}>
                        <div style={sectionLabel}>Exposure</div>
                        <div style={valueText}>
                          ${Number(selectedCustomerResolved.total_amount || 0).toLocaleString()}
                        </div>
                      </div>

                      <div style={metricCardStyle}>
                        <div style={sectionLabel}>Overdue</div>
                        <div style={valueText}>
                          ${Number(selectedCustomerResolved.overdue_amount || 0).toLocaleString()}
                        </div>
                      </div>

                      <div style={metricCardStyle}>
                        <div style={sectionLabel}>Risk</div>
                        <div style={valueText}>
                          {selectedCustomerResolved.ml_risk_prediction || "N/A"}{" "}
                          {selectedCustomerResolved.ml_risk_probability !== undefined
                            ? `(${selectedCustomerResolved.ml_risk_probability})`
                            : ""}
                        </div>
                      </div>

                      <div style={metricCardStyle}>
                        <div style={sectionLabel}>Expected Cash 30D</div>
                        <div style={{ ...valueText, color: "#34d399" }}>
                          $
                          {Number(
                            selectedCustomerResolved.predicted_amount_paid_next_30_days || 0
                          ).toLocaleString()}
                        </div>
                      </div>
                    </div>

                    {selectedCustomerResolved?.behavior_summary && (
                      <div style={metricCardStyle}>
                        <div style={sectionLabel}>Behavior Summary</div>
                        <div>{toDisplayText(selectedCustomerResolved.behavior_summary)}</div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>

            <div style={panelStyle}>
              <h2 style={{ marginTop: 0 }}>Customer Forecast Table</h2>

              {!dashboardData?.customer_summaries?.length && (
                <p style={{ color: "#6b7280" }}>No customer summaries loaded.</p>
              )}

              {dashboardData?.customer_summaries?.length > 0 && (
                <div style={{ overflowX: "auto" }}>
                  <table
                    style={{
                      width: "100%",
                      borderCollapse: "collapse",
                      fontSize: "14px",
                    }}
                  >
                    <thead>
                      <tr style={{ textAlign: "left", borderBottom: "1px solid #1f2937" }}>
                        <th style={{ padding: "10px 8px" }}>Customer</th>
                        <th style={{ padding: "10px 8px" }}>Total</th>
                        <th style={{ padding: "10px 8px" }}>Overdue</th>
                        <th style={{ padding: "10px 8px" }}>Risk</th>
                        <th style={{ padding: "10px 8px" }}>30D Cash</th>
                        <th style={{ padding: "10px 8px" }}>Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {dashboardData.customer_summaries
                        .slice(0, 20)
                        .map((c: any, i: number) => (
                          <tr
                            key={i}
                            onClick={() => setSelectedCustomer(c)}
                            style={{
                              borderBottom: "1px solid #161b22",
                              cursor: "pointer",
                            }}
                          >
                            <td style={{ padding: "10px 8px" }}>{c.customer_id}</td>
                            <td style={{ padding: "10px 8px" }}>
                              ${Number(c.total_amount || 0).toLocaleString()}
                            </td>
                            <td style={{ padding: "10px 8px" }}>
                              ${Number(c.overdue_amount || 0).toLocaleString()}
                            </td>
                            <td style={{ padding: "10px 8px" }}>
                              {c.ml_risk_prediction}
                            </td>
                            <td style={{ padding: "10px 8px", color: "#34d399" }}>
                              $
                              {Number(
                                c.predicted_amount_paid_next_30_days || 0
                              ).toLocaleString()}
                            </td>
                            <td style={{ padding: "10px 8px" }}>
                              {toDisplayText(c.recommended_action)}
                            </td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
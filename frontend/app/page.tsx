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

      const res = await fetch("http://127.0.0.1:8000/chat-upload", {
        method: "POST",
        body: formData,
      });

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
    } finally {
      setLoading(false);
    }
  };

  const dashboardData = analytics?.summary ? analytics.summary : analytics;

  const totalAR = dashboardData?.total_invoice_amount || 0;
  const expectedCash30 = dashboardData?.portfolio_expected_cash_next_30_days || 0;

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
            Autonomous AR Intelligence Dashboard
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

              <div style={{ display: "flex", gap: "10px", marginBottom: "12px" }}>
                <input
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
                  onClick={sendMessage}
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
                  Run
                </button>
              </div>

              <div style={{ display: "flex", gap: "10px", marginBottom: "16px" }}>
                <input
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
                  type="file"
                  accept=".csv"
                  onChange={(e) => setFile(e.target.files?.[0] || null)}
                  style={{ color: "#9ca3af" }}
                />
              </div>

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
                    Upload AR data and ask questions like:
                    <br />
                    “What should collections do first?”
                    <br />
                    “Who are the highest risk customers?”
                    <br />
                    “What cash should we expect in the next 30 days?”
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
                    {item.content}
                  </div>
                ))}
              </div>
            </div>

            <div style={panelStyle}>
              <h2 style={{ marginTop: 0 }}>Decision Output</h2>

              {!response && <p style={{ color: "#6b7280" }}>Awaiting analysis...</p>}

              {response?.clarifying_question && !response?.answer && (
                <p>{response.clarifying_question}</p>
              )}

              {response?.answer && <p style={{ lineHeight: 1.5 }}>{response.answer}</p>}

              {response?.assumptions && (
                <p style={{ color: "#9ca3af", marginTop: "10px" }}>
                  Assumptions: {response.assumptions}
                </p>
              )}

              {response && (
                <p style={{ color: "#9ca3af", marginTop: "10px" }}>
                  Confidence: {response.confidence}
                </p>
              )}
            </div>

            <div style={panelStyle}>
              <h2 style={{ marginTop: 0 }}>Interpretations</h2>

              {!response?.interpretations?.length && (
                <p style={{ color: "#6b7280" }}>No interpretations yet.</p>
              )}

              {response?.interpretations?.map((item, index) => (
                <div
                  key={index}
                  style={{
                    padding: "10px",
                    borderRadius: "10px",
                    border: "1px solid #1f2937",
                    marginBottom: "8px",
                    backgroundColor: "#0b0b0f",
                  }}
                >
                  {item}
                </div>
              ))}
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
                  Object.entries(dashboardData.aging_buckets).map(([k, v]: [string, any]) => (
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
                  ))}
              </div>

              <div style={panelStyle}>
                <h2 style={{ marginTop: 0 }}>Top Expected Payers (30 Days)</h2>

                {!dashboardData?.top_expected_payers_next_30_days?.length && (
                  <p style={{ color: "#6b7280" }}>No forecast data loaded.</p>
                )}

                {dashboardData?.top_expected_payers_next_30_days?.slice(0, 5).map((c: any, i: number) => (
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
                    <div>Risk: {c.ml_risk_prediction} ({c.ml_risk_probability})</div>
                    <div>Predicted payment date: {c.predicted_payment_date || "N/A"}</div>
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

                {dashboardData?.top_recommended_actions?.slice(0, 5).map((c: any, i: number) => (
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
                    <div
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        marginBottom: "6px",
                      }}
                    >
                      <strong>Customer {c.customer_id}</strong>
                      <span
                        style={{
                          color:
                            c.action_priority === "critical"
                              ? "#f87171"
                              : c.action_priority === "high"
                              ? "#f59e0b"
                              : c.action_priority === "medium"
                              ? "#60a5fa"
                              : "#34d399",
                          fontWeight: 700,
                        }}
                      >
                        {c.action_priority}
                      </span>
                    </div>

                    <div>Action: {c.recommended_action}</div>
                    <div>Reason: {c.action_reason}</div>
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
                    Select a customer from Top Expected Payers, Action Queue, or the table below.
                  </p>
                )}

                {selectedCustomerResolved && (
                  <div style={{ display: "grid", gap: "14px" }}>
                    <div>
                      <div style={sectionLabel}>Customer</div>
                      <div style={{ fontSize: "24px", fontWeight: 700 }}>
                        {selectedCustomerResolved.customer_id}
                      </div>
                    </div>

                    <div
                      style={{
                        display: "grid",
                        gridTemplateColumns: "1fr 1fr 1fr",
                        gap: "12px",
                      }}
                    >
                      <div
                        style={{
                          backgroundColor: "#0b0b0f",
                          border: "1px solid #1f2937",
                          borderRadius: "12px",
                          padding: "12px",
                        }}
                      >
                        <div style={sectionLabel}>Total Exposure</div>
                        <div style={valueText}>
                          ${Number(selectedCustomerResolved.total_amount || 0).toLocaleString()}
                        </div>
                      </div>

                      <div
                        style={{
                          backgroundColor: "#0b0b0f",
                          border: "1px solid #1f2937",
                          borderRadius: "12px",
                          padding: "12px",
                        }}
                      >
                        <div style={sectionLabel}>Overdue Amount</div>
                        <div style={valueText}>
                          ${Number(selectedCustomerResolved.overdue_amount || 0).toLocaleString()}
                        </div>
                      </div>

                      <div
                        style={{
                          backgroundColor: "#0b0b0f",
                          border: "1px solid #1f2937",
                          borderRadius: "12px",
                          padding: "12px",
                        }}
                      >
                        <div style={sectionLabel}>Invoice Count</div>
                        <div style={valueText}>
                          {selectedCustomerResolved.invoice_count || 0}
                        </div>
                      </div>
                    </div>

                    <div
                      style={{
                        display: "grid",
                        gridTemplateColumns: "1fr 1fr 1fr",
                        gap: "12px",
                      }}
                    >
                      <div
                        style={{
                          backgroundColor: "#0b0b0f",
                          border: "1px solid #1f2937",
                          borderRadius: "12px",
                          padding: "12px",
                        }}
                      >
                        <div style={sectionLabel}>Risk</div>
                        <div style={valueText}>
                          {selectedCustomerResolved.ml_risk_prediction || "N/A"}{" "}
                          {selectedCustomerResolved.ml_risk_probability !== undefined
                            ? `(${selectedCustomerResolved.ml_risk_probability})`
                            : ""}
                        </div>
                      </div>

                      <div
                        style={{
                          backgroundColor: "#0b0b0f",
                          border: "1px solid #1f2937",
                          borderRadius: "12px",
                          padding: "12px",
                        }}
                      >
                        <div style={sectionLabel}>Predicted Days to Pay</div>
                        <div style={valueText}>
                          {selectedCustomerResolved.predicted_days_to_pay ?? "N/A"}
                        </div>
                      </div>

                      <div
                        style={{
                          backgroundColor: "#0b0b0f",
                          border: "1px solid #1f2937",
                          borderRadius: "12px",
                          padding: "12px",
                        }}
                      >
                        <div style={sectionLabel}>Predicted Payment Date</div>
                        <div style={valueText}>
                          {selectedCustomerResolved.predicted_payment_date || "N/A"}
                        </div>
                      </div>
                    </div>

                    <div
                      style={{
                        display: "grid",
                        gridTemplateColumns: "1fr 1fr",
                        gap: "12px",
                      }}
                    >
                      <div
                        style={{
                          backgroundColor: "#0b0b0f",
                          border: "1px solid #1f2937",
                          borderRadius: "12px",
                          padding: "12px",
                        }}
                      >
                        <div style={sectionLabel}>Expected Cash Next 30 Days</div>
                        <div style={{ ...valueText, color: "#34d399" }}>
                          $
                          {Number(
                            selectedCustomerResolved.predicted_amount_paid_next_30_days || 0
                          ).toLocaleString()}
                        </div>
                      </div>

                      <div
                        style={{
                          backgroundColor: "#0b0b0f",
                          border: "1px solid #1f2937",
                          borderRadius: "12px",
                          padding: "12px",
                        }}
                      >
                        <div style={sectionLabel}>30D Collection Rate</div>
                        <div style={valueText}>
                          {(
                            Number(
                              selectedCustomerResolved.predicted_collection_rate_next_30_days || 0
                            ) * 100
                          ).toFixed(1)}
                          %
                        </div>
                      </div>
                    </div>

                    <div
                      style={{
                        backgroundColor: "#0b0b0f",
                        border: "1px solid #1f2937",
                        borderRadius: "12px",
                        padding: "12px",
                      }}
                    >
                      <div style={sectionLabel}>Recommended Action</div>
                      <div style={{ fontSize: "18px", fontWeight: 700 }}>
                        {selectedCustomerResolved.recommended_action || "N/A"}
                      </div>
                      <div style={{ marginTop: "8px", color: "#d1d5db" }}>
                        Priority: {selectedCustomerResolved.action_priority || "N/A"}
                      </div>
                      <div style={{ marginTop: "8px", color: "#9ca3af" }}>
                        {selectedCustomerResolved.action_reason ||
                          "No action rationale available."}
                      </div>
                    </div>

                    {selectedCustomerResolved?.behavior_summary && (
                      <div
                        style={{
                          backgroundColor: "#0b0b0f",
                          border: "1px solid #1f2937",
                          borderRadius: "12px",
                          padding: "12px",
                        }}
                      >
                        <div style={sectionLabel}>Behavior Summary</div>
                        <div>{selectedCustomerResolved.behavior_summary}</div>
                      </div>
                    )}

                    {selectedCustomerResolved?.invoice_details?.length > 0 && (
                      <div style={{ marginTop: "4px" }}>
                        <div
                          style={{
                            color: "#9ca3af",
                            fontSize: "12px",
                            marginBottom: "8px",
                          }}
                        >
                          INVOICE POPULATION
                        </div>

                        <div
                          style={{
                            maxHeight: "220px",
                            overflowY: "auto",
                            border: "1px solid #1f2937",
                            borderRadius: "10px",
                          }}
                        >
                          <div
                            style={{
                              display: "grid",
                              gridTemplateColumns: "1fr 1fr 1fr 1fr 1fr",
                              padding: "8px",
                              fontSize: "12px",
                              backgroundColor: "#111827",
                              borderBottom: "1px solid #1f2937",
                              fontWeight: 700,
                            }}
                          >
                            <div>Invoice</div>
                            <div>Amount</div>
                            <div>Invoice Date</div>
                            <div>Due Date</div>
                            <div>Status</div>
                          </div>

                          {selectedCustomerResolved.invoice_details.map((inv: any, i: number) => (
                            <div
                              key={i}
                              style={{
                                display: "grid",
                                gridTemplateColumns: "1fr 1fr 1fr 1fr 1fr",
                                padding: "8px",
                                borderBottom: "1px solid #111",
                                fontSize: "12px",
                              }}
                            >
                              <div>{inv.invoice_id || "N/A"}</div>
                              <div>${Number(inv.invoice_amount || 0).toLocaleString()}</div>
                              <div>{inv.invoice_date || "N/A"}</div>
                              <div>{inv.due_date || "N/A"}</div>
                              <div>{inv.status || "N/A"}</div>
                            </div>
                          ))}
                        </div>
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
                        <th style={{ padding: "10px 8px" }}>Prob</th>
                        <th style={{ padding: "10px 8px" }}>30D Cash</th>
                        <th style={{ padding: "10px 8px" }}>30D Rate</th>
                        <th style={{ padding: "10px 8px" }}>Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {dashboardData.customer_summaries.slice(0, 20).map((c: any, i: number) => (
                        <tr
                          key={i}
                          onClick={() => setSelectedCustomer(c)}
                          style={{
                            borderBottom: "1px solid #161b22",
                            cursor: "pointer",
                            backgroundColor:
                              selectedCustomerResolved?.customer_id === c.customer_id
                                ? "#111827"
                                : "transparent",
                          }}
                        >
                          <td style={{ padding: "10px 8px" }}>{c.customer_id}</td>
                          <td style={{ padding: "10px 8px" }}>
                            ${Number(c.total_amount || 0).toLocaleString()}
                          </td>
                          <td style={{ padding: "10px 8px" }}>
                            ${Number(c.overdue_amount || 0).toLocaleString()}
                          </td>
                          <td style={{ padding: "10px 8px" }}>{c.ml_risk_prediction}</td>
                          <td style={{ padding: "10px 8px" }}>{c.ml_risk_probability}</td>
                          <td style={{ padding: "10px 8px", color: "#34d399" }}>
                            $
                            {Number(
                              c.predicted_amount_paid_next_30_days || 0
                            ).toLocaleString()}
                          </td>
                          <td style={{ padding: "10px 8px" }}>
                            {(
                              Number(c.predicted_collection_rate_next_30_days || 0) * 100
                            ).toFixed(1)}
                            %
                          </td>
                          <td style={{ padding: "10px 8px" }}>{c.recommended_action}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            <div style={panelStyle}>
              <h2 style={{ marginTop: 0 }}>Working Context</h2>

              <div style={{ marginBottom: "12px" }}>
                <div style={sectionLabel}>Customer ID Input</div>
                <div>{customerId || "None"}</div>
              </div>

              <div style={{ marginBottom: "12px" }}>
                <div style={sectionLabel}>Uploaded File</div>
                <div>{file ? file.name : "None"}</div>
              </div>

              <div style={{ marginBottom: "12px" }}>
                <div style={sectionLabel}>Rows Loaded</div>
                <div>{dashboardData?.row_count || 0}</div>
              </div>

              <div style={{ marginBottom: "12px" }}>
                <div style={sectionLabel}>Source Type</div>
                <div>{dashboardData?.source_type || analytics?.source_type || "csv"}</div>
              </div>

              <div>
                <div style={sectionLabel}>Mode</div>
                <div>AR Dashboard + 30-Day Cash Forecast + Actions + Custom Drill-Down</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
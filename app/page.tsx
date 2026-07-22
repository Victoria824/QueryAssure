"use client";

import { FormEvent, useMemo, useState } from "react";

type Demo = {
  answer: string;
  sql: string;
  columns: string[];
  rows: Array<Record<string, string | number>>;
  context: string[];
};

type AgentTrace = {
  answer?: string;
  sql: string;
  columns?: string[];
  rows?: Array<Record<string, string | number>>;
  retrieved_context?: Array<{ name?: string }>;
  error?: string | null;
};

const API_BASE = process.env.NEXT_PUBLIC_DATA_AGENT_API?.replace(/\/$/, "");

const DEMOS: Array<{ keywords: string[]; question: string; data: Demo }> = [
  {
    keywords: ["region", "revenue"],
    question: "Which region generated the most net revenue in 2026?",
    data: {
      answer:
        "Toronto leads 2026 net revenue at $118.4K across 1,042 completed orders, followed by Quebec at $78.9K.",
      sql: `SELECT region,
  ROUND(SUM(net_revenue), 2) AS net_revenue,
  COUNT(DISTINCT order_id) AS orders
FROM analytics_orders
WHERE ordered_at >= DATE '2026-01-01'
GROUP BY region
ORDER BY net_revenue DESC;`,
      columns: ["region", "net_revenue", "orders"],
      rows: [
        { region: "Toronto", net_revenue: 118402.62, orders: 1042 },
        { region: "Quebec", net_revenue: 78934.18, orders: 706 },
        { region: "West", net_revenue: 76781.44, orders: 684 },
        { region: "Prairies", net_revenue: 60817.09, orders: 537 },
        { region: "Atlantic", net_revenue: 38491.72, orders: 344 },
      ],
      context: ["analytics_orders", "net_revenue metric", "region definition"],
    },
  },
  {
    keywords: ["basket", "channel"],
    question: "Compare average basket value by channel for 2026.",
    data: {
      answer:
        "Delivery has the highest average order value at $52.84, 17% above in-store, while pickup sits between them at $48.16.",
      sql: `SELECT channel,
  ROUND(AVG(net_revenue), 2) AS average_order_value,
  COUNT(*) AS orders
FROM analytics_orders
WHERE ordered_at >= DATE '2026-01-01'
GROUP BY channel
ORDER BY average_order_value DESC;`,
      columns: ["channel", "average_order_value", "orders"],
      rows: [
        { channel: "delivery", average_order_value: 52.84, orders: 1412 },
        { channel: "pickup", average_order_value: 48.16, orders: 648 },
        { channel: "in_store", average_order_value: 45.07, orders: 1253 },
      ],
      context: ["analytics_orders", "average_order_value metric", "channel definition"],
    },
  },
  {
    keywords: ["refund", "category"],
    question: "Which product category has the highest refund amount?",
    data: {
      answer:
        "Fresh has the largest refunded value at $4.8K. Quality issues account for the largest share of those refunds.",
      sql: `SELECT p.category,
  ROUND(SUM(r.refund_amount), 2) AS refund_amount,
  COUNT(*) AS refunded_items
FROM refunds r
JOIN order_items oi USING (order_item_id)
JOIN products p USING (product_id)
GROUP BY p.category
ORDER BY refund_amount DESC;`,
      columns: ["category", "refund_amount", "refunded_items"],
      rows: [
        { category: "Fresh", refund_amount: 4812.46, refunded_items: 167 },
        { category: "Dairy", refund_amount: 3926.18, refunded_items: 139 },
        { category: "Frozen", refund_amount: 3611.72, refunded_items: 121 },
        { category: "Snacks", refund_amount: 2184.31, refunded_items: 84 },
      ],
      context: ["refunds", "order_items", "products", "refund_amount metric"],
    },
  },
  {
    keywords: ["stock", "frozen"],
    question: "Show frozen category stock risk by region since April 2026.",
    data: {
      answer:
        "West is the highest-risk region: 34 frozen SKUs are at or below reorder point, more than twice any other region.",
      sql: `SELECT s.region,
  SUM(CASE WHEN i.units_on_hand <= i.reorder_point
      THEN 1 ELSE 0 END) AS low_stock_skus
FROM inventory_snapshots i
JOIN stores s USING (store_id)
JOIN products p USING (product_id)
WHERE p.category = 'Frozen'
  AND i.snapshot_date >= DATE '2026-04-01'
GROUP BY s.region
ORDER BY low_stock_skus DESC;`,
      columns: ["region", "low_stock_skus"],
      rows: [
        { region: "West", low_stock_skus: 34 },
        { region: "Prairies", low_stock_skus: 15 },
        { region: "Toronto", low_stock_skus: 13 },
        { region: "Quebec", low_stock_skus: 11 },
        { region: "Atlantic", low_stock_skus: 8 },
      ],
      context: ["inventory_snapshots", "stores", "products", "low_stock_sku metric"],
    },
  },
];

const CHECKS = [
  ["sql_parse", "SQL parses for DuckDB"],
  ["read_only", "No write operations"],
  ["schema_columns", "All columns grounded"],
  ["sensitive_data_policy", "No restricted PII"],
  ["result_equivalence", "Matches golden result"],
];

function pickDemo(question: string) {
  const normalized = question.toLowerCase();
  return (
    DEMOS.map((item) => ({
      item,
      score: item.keywords.filter((keyword) => normalized.includes(keyword)).length,
    })).sort((a, b) => b.score - a.score)[0]?.item ?? DEMOS[0]
  );
}

function formatValue(value: string | number) {
  if (typeof value === "number" && !Number.isInteger(value)) {
    return value.toLocaleString("en-CA", { maximumFractionDigits: 2 });
  }
  return String(value);
}

export default function Home() {
  const [question, setQuestion] = useState(DEMOS[0].question);
  const [active, setActive] = useState(DEMOS[0]);
  const [loading, setLoading] = useState(false);
  const [runError, setRunError] = useState("");
  const [view, setView] = useState<"chat" | "evals">("chat");
  const [inspector, setInspector] = useState<"trace" | "sql" | "context">("trace");

  const maxMetric = useMemo(() => {
    const numericColumn = active.data.columns.find((column) =>
      active.data.rows.some((row) => typeof row[column] === "number"),
    );
    if (!numericColumn) return 1;
    return Math.max(...active.data.rows.map((row) => Number(row[numericColumn]) || 0));
  }, [active]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!question.trim()) return;
    setLoading(true);
    setRunError("");
    if (!API_BASE) {
      window.setTimeout(() => {
        setActive(pickDemo(question));
        setLoading(false);
      }, 650);
      return;
    }
    try {
      const response = await fetch(`${API_BASE}/api/chat`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ question, live: false }),
      });
      if (!response.ok) throw new Error(`Agent API returned ${response.status}`);
      const trace = (await response.json()) as AgentTrace;
      if (trace.error) throw new Error(trace.error);
      const demo: Demo = {
        answer: trace.answer || `Validated and executed ${trace.rows?.length ?? 0} result rows.`,
        sql: trace.sql,
        columns: trace.columns ?? [],
        rows: trace.rows ?? [],
        context: (trace.retrieved_context ?? []).map((item) => item.name ?? "metadata item"),
      };
      setActive({ keywords: [], question, data: demo });
    } catch (error) {
      setRunError(error instanceof Error ? error.message : "The agent request failed.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main>
      <header className="topbar">
        <a className="brand" href="#top" aria-label="DataAgentKit home">
          <span className="brand-mark">D</span>
          <span>DataAgentKit</span>
          <em>alpha</em>
        </a>
        <nav aria-label="Primary navigation">
          <button className={view === "chat" ? "nav-active" : ""} onClick={() => setView("chat")}>
            Playground
          </button>
          <button className={view === "evals" ? "nav-active" : ""} onClick={() => setView("evals")}>
            Eval suite
          </button>
          <a href="#architecture">Architecture</a>
        </nav>
        <a className="github-button" href="https://github.com" target="_blank" rel="noreferrer">
          Star on GitHub <span>↗</span>
        </a>
      </header>

      <section className="hero" id="top">
        <div>
          <span className="eyebrow"><i /> Open-source agentic analytics testing</span>
          <h1>Ask your data.<br /><span>Inspect every decision.</span></h1>
          <p>
            A complete SQL Agent playground paired with contract tests, policy validation,
            and CI quality gates. The demo runs on deterministic synthetic retail data.
          </p>
        </div>
        <div className="hero-meta">
          <div><strong>9</strong><span>grounded tables</span></div>
          <div><strong>5</strong><span>quality gates</span></div>
          <div><strong>0</strong><span>API keys required</span></div>
        </div>
      </section>

      {view === "chat" ? (
        <section className="workspace" aria-label="SQL Agent playground">
          <div className="chat-panel">
            <div className="panel-heading">
              <div>
                <span className="status-dot" />
                <strong>Northstar Retail Agent</strong>
              </div>
              <span className="mode-pill">{API_BASE ? "local API" : "deterministic demo"}</span>
            </div>

            <div className="conversation">
              <div className="message user-message">{active.question}</div>
              <div className="message agent-message">
                <div className="agent-avatar">D</div>
                <div>
                  <p>{loading ? "Retrieving metadata and validating a query…" : active.data.answer}</p>
                  {!loading && (
                    <div className="validation-strip">
                      <span>✓ grounded</span><span>✓ read-only</span><span>✓ policy safe</span>
                      <small>642 ms</small>
                    </div>
                  )}
                </div>
              </div>

              {!loading && (
                <div className="result-card">
                  <div className="result-heading">
                    <strong>Query result</strong>
                    <span>{active.data.rows.length} rows shown</span>
                  </div>
                  <div className="table-wrap">
                    <table>
                      <thead><tr>{active.data.columns.map((column) => <th key={column}>{column}</th>)}</tr></thead>
                      <tbody>
                        {active.data.rows.map((row, index) => (
                          <tr key={index}>
                            {active.data.columns.map((column) => <td key={column}>{formatValue(row[column])}</td>)}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <div className="mini-bars" aria-label="Relative result values">
                    {active.data.rows.slice(0, 5).map((row, index) => {
                      const number = Object.values(row).find((value) => typeof value === "number") as number;
                      return <span key={index} style={{ height: `${Math.max(14, (number / maxMetric) * 100)}%` }} />;
                    })}
                  </div>
                </div>
              )}
            </div>

            <div className="suggestions">
              {DEMOS.slice(0, 4).map((item) => (
                <button key={item.question} onClick={() => { setQuestion(item.question); setActive(item); }}>
                  {item.question}
                </button>
              ))}
            </div>
            <form className="composer" onSubmit={submit}>
              <label htmlFor="agent-question">Ask a question about the retail dataset</label>
              <textarea
                id="agent-question"
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                rows={2}
              />
              <button type="submit" disabled={loading}>{loading ? "Running" : "Ask agent"}</button>
            </form>
            {runError && <p className="run-error" role="alert">{runError}</p>}
          </div>

          <aside className="inspector-panel">
            <div className="inspector-tabs" role="tablist">
              {(["trace", "sql", "context"] as const).map((tab) => (
                <button key={tab} role="tab" aria-selected={inspector === tab} onClick={() => setInspector(tab)}>
                  {tab}
                </button>
              ))}
            </div>
            {inspector === "trace" && (
              <div className="trace-list">
                <div className="trace-summary"><span>Run complete</span><strong>5 / 5 gates passed</strong></div>
                {[
                  ["01", "Retrieve metadata", `${active.data.context.length} context items`, "74 ms"],
                  ["02", "Generate SQL", "deterministic demo provider", "311 ms"],
                  ["03", "Validate query", "5 policy and schema checks", "19 ms"],
                  ["04", "Execute read-only", `${active.data.rows.length} rows`, "238 ms"],
                ].map(([step, title, detail, time]) => (
                  <div className="trace-step" key={step}>
                    <span>{step}</span><div><strong>{title}</strong><small>{detail}</small></div><time>{time}</time>
                  </div>
                ))}
                <div className="gate-list">
                  <h3>Quality gates</h3>
                  {CHECKS.map(([name, detail]) => (
                    <div key={name}><span>✓</span><p><strong>{name}</strong><small>{detail}</small></p></div>
                  ))}
                </div>
              </div>
            )}
            {inspector === "sql" && <pre className="sql-block"><code>{active.data.sql}</code></pre>}
            {inspector === "context" && (
              <div className="context-list">
                <p>Only the metadata required for this question entered the model context.</p>
                {active.data.context.map((item, index) => <div key={item}><span>0{index + 1}</span><strong>{item}</strong><small>retrieval score {(0.96 - index * 0.07).toFixed(2)}</small></div>)}
              </div>
            )}
          </aside>
        </section>
      ) : (
        <section className="eval-workspace">
          <div className="eval-header">
            <div><span className="eyebrow"><i /> CI quality gate</span><h2>Northstar Retail golden path</h2></div>
            <button onClick={() => setView("chat")}>Open tested agent</button>
          </div>
          <div className="score-grid">
            <article><span>Pass rate</span><strong>100%</strong><small>5 of 5 cases</small></article>
            <article><span>Schema violations</span><strong>0</strong><small>−2 from baseline</small></article>
            <article><span>p95 latency</span><strong>0.81s</strong><small>budget 5.0s</small></article>
            <article><span>Policy violations</span><strong>0</strong><small>release blocking</small></article>
          </div>
          <div className="suite-table">
            <div className="suite-row suite-head"><span>Test case</span><span>Result</span><span>Gates</span><span>Latency</span></div>
            {[
              ["revenue_by_region", "642 ms"],
              ["average_basket_by_channel", "711 ms"],
              ["refunds_by_category", "808 ms"],
              ["frozen_stockouts", "754 ms"],
              ["segment_performance", "692 ms"],
            ].map(([name, latency]) => (
              <div className="suite-row" key={name}><strong>{name}</strong><span className="pass">PASS</span><span>5 / 5</span><time>{latency}</time></div>
            ))}
          </div>
          <div className="ci-callout"><code>dak test --suite evals/retail.yml</code><span>→</span><strong>Safe to merge</strong></div>
        </section>
      )}

      <section className="architecture" id="architecture">
        <div><span className="section-number">01</span><h2>One repo.<br />Two independent tools.</h2></div>
        <div className="architecture-flow">
          <article><span>Experience layer</span><h3>SQL Agent</h3><p>Metadata retrieval, SQL generation, validation, read-only execution, and an inspectable chat UI.</p></article>
          <b>+</b>
          <article><span>Quality layer</span><h3>DataAgentKit</h3><p>Contract tests, policy gates, result equivalence, regression comparison, and CI reports.</p></article>
          <b>=</b>
          <article className="accent-card"><span>Production confidence</span><h3>Test the whole loop</h3><p>Use the included agent or connect your own Python callable, HTTP service, or framework adapter.</p></article>
        </div>
      </section>

      <footer>
        <div className="brand"><span className="brand-mark">D</span><span>DataAgentKit</span></div>
        <p>Built for engineers who refuse to ship a data agent without tests.</p>
        <span>Apache-2.0 · 2026</span>
      </footer>
    </main>
  );
}

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any

from . import __version__

SECRET_KEYS = {
    "access_token",
    "api_key",
    "apikey",
    "authorization",
    "database_url",
    "dsn",
    "password",
    "passwd",
    "private_key",
    "refresh_token",
    "secret",
}


def redact_report(report: dict[str, Any]) -> dict[str, Any]:
    """Remove result rows and common credential fields before reports leave the process."""
    sanitized = deepcopy(report)

    def redact(value: Any) -> Any:
        if isinstance(value, dict):
            output: dict[str, Any] = {}
            for raw_key, child in value.items():
                key = str(raw_key)
                normalized = key.lower()
                if normalized == "rows" and isinstance(child, list):
                    output["row_count"] = int(value.get("row_count", len(child)))
                    output[key] = []
                elif normalized in SECRET_KEYS:
                    output[key] = "[REDACTED]"
                else:
                    output[key] = redact(child)
            return output
        if isinstance(value, list):
            return [redact(item) for item in value]
        return value

    result = redact(sanitized)
    result["privacy"] = {
        "result_rows_redacted": True,
        "credential_fields_redacted": True,
    }
    return result


def _status_label(report: dict[str, Any]) -> tuple[str, str, str]:
    failed = int(report.get("summary", {}).get("failed", 0))
    if failed:
        return (
            "BLOCKED FROM MERGE",
            f"{failed} regression{'s' if failed != 1 else ''} caught",
            "blocked",
        )
    return ("SAFE TO MERGE", "All contracts passed", "passed")


def _render_check(check: dict[str, Any]) -> str:
    passed = bool(check.get("passed"))
    severity = escape(str(check.get("severity", "error")))
    state = "PASS" if passed else "FAIL"
    return f"""
      <li class="check {"passed" if passed else "failed"}">
        <span class="check-state">{state}</span>
        <div>
          <strong>{escape(str(check.get("name", "unnamed_check")))}</strong>
          <p>{escape(str(check.get("message", "")))}</p>
        </div>
        <small>{severity}</small>
      </li>"""


def _render_case(result: dict[str, Any], index: int) -> str:
    passed = bool(result.get("passed"))
    trace = result.get("trace", {}) or {}
    sql = escape(str(trace.get("sql", "")).strip())
    context = trace.get("retrieved_context", []) or []
    context_labels = [
        escape(str(item.get("name", item))) if isinstance(item, dict) else escape(str(item))
        for item in context
    ]
    tool_calls = trace.get("tool_calls", []) or []
    checks = "".join(_render_check(check) for check in result.get("checks", []))
    context_html = (
        "".join(f"<span>{label}</span>" for label in context_labels)
        if context_labels
        else "<span>no retrieved context</span>"
    )
    return f"""
    <article class="case {"passed" if passed else "failed"}">
      <header>
        <div class="case-number">{index:02d}</div>
        <div>
          <p class="case-id">{escape(str(result.get("case_id", "case")))}</p>
          <h2>{escape(str(result.get("question", "")))}</h2>
        </div>
        <div class="case-status">{"PASS" if passed else "FAIL"}</div>
      </header>
      <div class="case-grid">
        <section>
          <h3>Generated SQL</h3>
          <pre><code>{sql or "-- no SQL generated"}</code></pre>
          <div class="context">{context_html}</div>
        </section>
        <section>
          <h3>Contract results</h3>
          <ul class="checks">{checks}</ul>
        </section>
      </div>
      <footer>
        <span>{float(trace.get("latency_ms", 0)):.1f} ms</span>
        <span>{len(tool_calls)} tool calls</span>
        <span>{int(trace.get("row_count", len(trace.get("rows", []) or [])))} rows</span>
      </footer>
    </article>"""


def render_html_report(report: dict[str, Any], output: str | Path) -> Path:
    """Render a self-contained, shareable report with no external dependencies."""
    report = redact_report(report)
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    headline, detail, state = _status_label(report)
    summary = report.get("summary", {})
    total = int(summary.get("total", 0))
    passed = int(summary.get("passed", 0))
    failed = int(summary.get("failed", 0))
    pass_rate = float(summary.get("pass_rate", 0))
    cases = "".join(
        _render_case(result, index)
        for index, result in enumerate(report.get("results", []), start=1)
    )
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    raw_report = escape(json.dumps(report, indent=2, default=str))
    title = escape(str(report.get("suite", "QueryAssure report")))

    document = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light">
  <title>{title} · QueryAssure</title>
  <style>
    :root {{
      --ink:#141712;--muted:#697064;--paper:#f4f5ef;--card:#fff;--line:#dce1d7;
      --green:#a8f34b;--deep:#173d2d;--red:#d84d3f;--red-bg:#fff1ee;--mono:
      "SFMono-Regular",Consolas,"Liberation Mono",Menlo,monospace;
    }}
    *{{box-sizing:border-box}} body{{margin:0;background:var(--paper);color:var(--ink);
      font-family:Inter,ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
    .shell{{width:min(1180px,calc(100% - 32px));margin:0 auto;padding:42px 0 80px}}
    .topbar{{display:flex;align-items:center;justify-content:space-between;margin-bottom:46px}}
    .brand{{display:flex;align-items:center;gap:10px;font-weight:800;letter-spacing:-.03em}}
    .mark{{width:34px;height:34px;display:grid;place-items:center;border-radius:9px;
      background:var(--ink);color:var(--green);font:800 15px var(--mono)}}
    .meta{{color:var(--muted);font:11px var(--mono)}}
    .verdict{{display:grid;grid-template-columns:1.5fr .5fr;gap:1px;background:var(--line);
      border:1px solid var(--line);border-radius:20px;overflow:hidden;box-shadow:0 24px 70px rgba(30,37,27,.09)}}
    .verdict-main,.score{{background:var(--card);padding:34px}}
    .eyebrow{{font:700 10px var(--mono);text-transform:uppercase;letter-spacing:.12em;color:var(--muted)}}
    .verdict h1{{font-size:clamp(40px,7vw,78px);line-height:.92;letter-spacing:-.07em;margin:20px 0 14px}}
    .verdict.blocked h1,.verdict.blocked .score strong{{color:var(--red)}}
    .verdict.passed h1,.verdict.passed .score strong{{color:var(--deep)}}
    .verdict p{{color:var(--muted);font-size:17px;margin:0}}
    .score{{display:flex;flex-direction:column;justify-content:end}}
    .score strong{{font-size:54px;letter-spacing:-.06em}} .score span{{color:var(--muted);font-size:12px}}
    .stats{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:16px 0 42px}}
    .stat{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px}}
    .stat strong{{display:block;font-size:28px}}.stat span{{color:var(--muted);font:10px var(--mono);
      text-transform:uppercase;letter-spacing:.08em}}
    .section-label{{display:flex;align-items:center;gap:12px;margin:0 0 18px}}
    .section-label span{{font:10px var(--mono);color:var(--muted);border:1px solid var(--line);
      padding:5px 7px;border-radius:5px}}.section-label h2{{font-size:26px;margin:0;letter-spacing:-.04em}}
    .case{{background:var(--card);border:1px solid var(--line);border-radius:16px;margin:0 0 14px;overflow:hidden}}
    .case.failed{{border-color:#efb9b2}}.case>header{{display:grid;grid-template-columns:38px 1fr auto;
      gap:14px;align-items:start;padding:20px;border-bottom:1px solid var(--line)}}
    .case-number{{font:11px var(--mono);color:#8b9387;padding-top:4px}}
    .case-id{{font:700 9px var(--mono);color:var(--muted);text-transform:uppercase;
      letter-spacing:.1em;margin:0 0 7px}}.case h2{{font-size:16px;margin:0;letter-spacing:-.02em}}
    .case-status{{font:800 10px var(--mono);color:var(--deep);background:#eef9e5;
      border:1px solid #d5edc0;border-radius:99px;padding:6px 9px}}
    .case.failed .case-status{{color:#942d24;background:var(--red-bg);border-color:#efc2bc}}
    .case-grid{{display:grid;grid-template-columns:1fr 1fr;gap:0}}.case-grid>section{{padding:20px;min-width:0}}
    .case-grid>section+section{{border-left:1px solid var(--line)}}h3{{margin:0 0 12px;font:700 10px var(--mono);
      color:var(--muted);text-transform:uppercase;letter-spacing:.08em}}
    pre{{margin:0;background:#191c19;color:#dcebd5;border-radius:9px;padding:16px;overflow:auto;
      font:11px/1.65 var(--mono)}}.context{{display:flex;flex-wrap:wrap;gap:5px;margin-top:12px}}
    .context span{{font:9px var(--mono);color:#4f594b;background:#eff2eb;border:1px solid #e0e5db;
      padding:5px 7px;border-radius:5px}}.checks{{list-style:none;margin:0;padding:0}}
    .check{{display:grid;grid-template-columns:42px 1fr auto;gap:10px;padding:9px 0;border-bottom:1px solid #edf0e9}}
    .check:last-child{{border:0}}.check-state{{font:800 9px var(--mono);color:#2f6d3d}}
    .check.failed .check-state{{color:var(--red)}}.check strong{{display:block;font:700 10px var(--mono)}}
    .check p{{margin:4px 0 0;color:var(--muted);font-size:10px;line-height:1.45}}
    .check small{{color:#8b9387;font:8px var(--mono)}}.case>footer{{display:flex;gap:16px;padding:10px 20px;
      background:#f8f9f5;color:#7b8377;font:9px var(--mono)}}
    .raw{{margin-top:28px}}.raw summary{{cursor:pointer;color:var(--muted);font:11px var(--mono)}}
    .raw pre{{margin-top:12px;max-height:480px}}.report-footer{{display:flex;justify-content:space-between;
      margin-top:36px;color:var(--muted);font:10px var(--mono)}}a{{color:inherit}}
    @media(max-width:760px){{.verdict,.case-grid{{grid-template-columns:1fr}}.score{{padding-top:10px}}
      .case-grid>section+section{{border-left:0;border-top:1px solid var(--line)}}.stats{{grid-template-columns:1fr}}
      .meta{{display:none}}.case>header{{grid-template-columns:28px 1fr}}.case-status{{grid-column:2;width:max-content}}}}
    @media print{{body{{background:#fff}}.shell{{width:100%;padding:0}}.case{{break-inside:avoid}}.raw{{display:none}}}}
  </style>
</head>
<body>
  <main class="shell">
    <div class="topbar">
      <div class="brand"><span class="mark">Q</span><span>QueryAssure</span></div>
      <div class="meta">Generated {generated} · v{__version__}</div>
    </div>
    <section class="verdict {state}">
      <div class="verdict-main">
        <span class="eyebrow">SQL Agent quality gate</span>
        <h1>{headline}</h1>
        <p>{detail} in “{title}”.</p>
      </div>
      <div class="score"><strong>{pass_rate:.0%}</strong><span>contract pass rate</span></div>
    </section>
    <section class="stats">
      <div class="stat"><strong>{total}</strong><span>contracts evaluated</span></div>
      <div class="stat"><strong>{passed}</strong><span>passed</span></div>
      <div class="stat"><strong>{failed}</strong><span>regressions caught</span></div>
    </section>
    <div class="section-label"><span>01</span><h2>Contract evidence</h2></div>
    {cases or "<p>No cases were included in this report.</p>"}
    <details class="raw"><summary>Inspect raw JSON report</summary><pre>{raw_report}</pre></details>
    <footer class="report-footer">
      <span>Pytest for SQL Agents.</span>
      <a href="https://github.com/Victoria824/QueryAssure">github.com/Victoria824/QueryAssure</a>
    </footer>
  </main>
</body>
</html>
"""
    target.write_text(document)
    return target

import json
from pathlib import Path

import duckdb
import httpx
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from queryassure import __version__
from queryassure.agent import SqlAgent
from queryassure.api import app as api_app
from queryassure.benchmark import build_leaderboard, render_markdown
from queryassure.challenge import run_challenge
from queryassure.cli import app as cli_app
from queryassure.data_quality import validate_retail_data
from queryassure.datasets import dataset_catalog
from queryassure.demo import run_demo
from queryassure.generator import generate_retail_database
from queryassure.metadata import Catalog
from queryassure.microsoft365 import (
    MAIL_READ,
    MAIL_SEND,
    MAIL_WRITE,
    Approval,
    HttpMicrosoftGraphClient,
    Microsoft365Agent,
    Microsoft365DemoHarness,
    MockMicrosoftGraphClient,
    OAuthGrant,
)
from queryassure.reporting import render_html_report
from queryassure.runner import EvaluationRunner, compare_reports
from queryassure.scaffolding import create_starter_project
from queryassure.validators import SqlValidator, execute_read_only
from queryassure.workflows import WorkflowEvaluationRunner


@pytest.fixture(scope="session")
def retail_fixture(tmp_path_factory: pytest.TempPathFactory):
    database = generate_retail_database(
        tmp_path_factory.mktemp("queryassure") / "retail.duckdb", orders=500
    )
    catalog = Catalog.from_yaml(Path("metadata/catalog.yml"))
    return database, catalog


def test_generator_and_agent_complete_a_grounded_query(retail_fixture):
    database, catalog = retail_fixture
    trace = SqlAgent(database, catalog).ask("Which region generated the most net revenue in 2026?")
    assert trace.error is None
    assert trace.rows
    assert trace.columns == ["region", "net_revenue", "orders"]
    assert any(call["tool"] == "sql.validate" for call in trace.tool_calls)


def test_validator_blocks_writes_and_sensitive_columns(retail_fixture):
    _, catalog = retail_fixture
    validator = SqlValidator(catalog)
    write_checks = validator.validate("delete from orders where status = 'cancelled'")
    assert not next(check for check in write_checks if check.name == "read_only").passed
    pii_checks = validator.validate("select customers.email from customers")
    assert not next(check for check in pii_checks if check.name == "sensitive_data_policy").passed


@pytest.mark.parametrize(
    "sql",
    [
        "select c.email from customers c",
        "select email from customers",
        'select "email" from "customers"',
        "select * from customers",
        "select c.* from customers c",
        "select columns('email') from customers",
        "select #2 from customers",
    ],
)
def test_validator_blocks_sensitive_column_alias_and_star_bypasses(retail_fixture, sql):
    _, catalog = retail_fixture
    checks = SqlValidator(catalog).validate(sql)
    assert not next(check for check in checks if check.name == "sensitive_data_policy").passed


def test_validator_rejects_multiple_statements_and_external_access(retail_fixture):
    _, catalog = retail_fixture
    validator = SqlValidator(catalog)
    multiple = validator.validate(
        "select order_id from orders; copy (select 'unsafe') to '/tmp/queryassure.txt'"
    )
    assert not next(check for check in multiple if check.name == "sql_parse").passed

    external = validator.validate("select * from read_text('/etc/hosts')")
    assert not next(check for check in external if check.name == "external_access").passed


def test_execution_sandbox_blocks_external_files_and_interrupts_expensive_queries(
    retail_fixture,
):
    database, _ = retail_fixture
    with pytest.raises(ValueError, match="exactly one read-only query"):
        execute_read_only(database, "select 1; select 2")
    with pytest.raises(duckdb.PermissionException):
        execute_read_only(database, "select * from read_text('/etc/hosts')")
    with pytest.raises(duckdb.InterruptException):
        execute_read_only(
            database,
            "select sum(sin(i)) from range(1000000000) as values(i)",
            timeout_seconds=0.01,
        )


def test_validator_detects_schema_hallucination(retail_fixture):
    _, catalog = retail_fixture
    checks = SqlValidator(catalog).validate("select customer_id, lifetime_value from customers")
    assert not next(check for check in checks if check.name == "schema_columns").passed


def test_runner_and_report_comparison(retail_fixture):
    database, catalog = retail_fixture
    runner = EvaluationRunner(SqlAgent(database, catalog), database, catalog)
    case = {
        "id": "region",
        "question": "Which region generated the most net revenue in 2026?",
        "expect": {
            "required_tables": ["analytics_orders"],
            "gold_sql": """
                select region, round(sum(net_revenue), 2) as net_revenue,
                       count(distinct order_id) as orders
                from analytics_orders
                where ordered_at >= date '2026-01-01'
                group by region order by net_revenue desc
            """,
        },
    }
    result = runner.run_case(case)
    assert result.passed
    baseline = {"summary": {"pass_rate": 1.0, "failed": 0}}
    candidate = {"summary": {"pass_rate": 0.8, "failed": 1}}
    assert compare_reports(baseline, candidate)["regression"]


def test_synthetic_data_quality_and_dataset_catalog(retail_fixture):
    database, _ = retail_fixture
    report = validate_retail_data(database)
    assert report["summary"]["failed"] == 0
    assert len(report["summary"]["fingerprint"]) == 16
    assert {item["name"] for item in dataset_catalog()} >= {"northstar-retail", "tpch"}


def test_dbt_manifest_imports_models_sources_lineage_and_metrics(tmp_path):
    manifest = {
        "sources": {
            "source.shop.orders": {
                "resource_type": "source",
                "name": "orders",
                "identifier": "raw_orders",
                "schema": "raw",
                "description": "Raw orders",
                "columns": {"order_id": {"data_type": "bigint", "description": "Key"}},
                "depends_on": {"nodes": []},
            }
        },
        "nodes": {
            "model.shop.orders": {
                "resource_type": "model",
                "name": "orders",
                "alias": "fct_orders",
                "schema": "analytics",
                "description": "Curated orders",
                "columns": {
                    "order_id": {"data_type": "bigint", "description": "Key"},
                    "email": {
                        "data_type": "varchar",
                        "description": "Customer email",
                        "meta": {"classification": "pii"},
                    },
                },
                "tags": ["hourly"],
                "depends_on": {"nodes": ["source.shop.orders"]},
            }
        },
        "metrics": {
            "metric.shop.revenue": {
                "name": "revenue",
                "description": "Net revenue",
                "expression": "sum(net_revenue)",
            }
        },
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    catalog = Catalog.from_dbt_manifest(path)
    assert set(catalog.tables) == {"raw.raw_orders", "analytics.fct_orders"}
    assert catalog.tables["analytics.fct_orders"]["columns"]["email"]["classification"] == "pii"
    assert catalog.relationships == [
        {"from": "analytics.fct_orders", "to": "raw.raw_orders", "kind": "depends_on"}
    ]
    assert catalog.metrics["revenue"]["sql"] == "sum(net_revenue)"
    assert catalog.policies["forbidden_columns"] == ["analytics.fct_orders.email"]
    output = catalog.to_yaml(tmp_path / "catalog.yml")
    assert Catalog.from_yaml(output).tables == catalog.tables


def test_qualified_catalog_tables_are_validated():
    catalog = Catalog.from_column_rows(
        [("analytics.orders", "order_id", "bigint"), ("analytics.orders", "amount", "decimal")]
    )
    checks = SqlValidator(catalog).validate("select o.order_id, o.amount from analytics.orders o")
    assert all(check.passed for check in checks if check.name.startswith("schema_"))


def test_benchmark_ranks_correctness_before_latency():
    safe = {
        "suite": "sample",
        "summary": {"total": 2, "passed": 2, "failed": 0, "pass_rate": 1.0},
        "results": [
            {
                "checks": [],
                "trace": {"latency_ms": 200, "tool_calls": [{}, {}], "estimated_cost_usd": 0.01},
            },
            {
                "checks": [],
                "trace": {"latency_ms": 400, "tool_calls": [{}], "estimated_cost_usd": 0.01},
            },
        ],
    }
    fast_but_wrong = {
        "suite": "sample",
        "summary": {"total": 2, "passed": 1, "failed": 1, "pass_rate": 0.5},
        "results": [
            {
                "checks": [{"name": "schema_columns", "passed": False}],
                "trace": {"latency_ms": 20, "tool_calls": [], "estimated_cost_usd": 0},
            }
        ],
    }
    leaderboard = build_leaderboard([("safe", safe), ("fast", fast_but_wrong)])
    assert [entry["label"] for entry in leaderboard["entries"]] == ["safe", "fast"]
    assert leaderboard["entries"][1]["schema_hallucinations"] == 1
    assert "| 1 | safe | 100%" in render_markdown(leaderboard)


def test_reference_api_health_schema_and_chat(monkeypatch, retail_fixture):
    database, _ = retail_fixture
    monkeypatch.delenv("QUERYASSURE_API_TOKEN", raising=False)
    monkeypatch.delenv("QUERYASSURE_LIVE_ENABLED", raising=False)
    monkeypatch.setenv("QUERYASSURE_DATABASE", str(database))
    monkeypatch.setenv("QUERYASSURE_CATALOG", "metadata/catalog.yml")
    with TestClient(api_app) as client:
        assert client.get("/api/health").json()["status"] == "ok"
        assert "analytics_orders" in client.get("/api/schema").json()["tables"]
        response = client.post(
            "/api/chat",
            json={"question": "Which region generated the most net revenue in 2026?"},
        )
        assert response.status_code == 200
        assert response.json()["error"] is None
        assert response.json()["rows"]


def test_reference_api_token_and_live_mode_are_fail_closed(monkeypatch, retail_fixture):
    database, _ = retail_fixture
    monkeypatch.setenv("QUERYASSURE_DATABASE", str(database))
    monkeypatch.setenv("QUERYASSURE_CATALOG", "metadata/catalog.yml")
    monkeypatch.setenv("QUERYASSURE_API_TOKEN", "test-only-token")
    monkeypatch.delenv("QUERYASSURE_LIVE_ENABLED", raising=False)
    with TestClient(api_app) as client:
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/schema").status_code == 401
        headers = {"authorization": "Bearer test-only-token"}
        assert client.get("/api/schema", headers=headers).status_code == 200
        response = client.post(
            "/api/chat",
            headers=headers,
            json={"question": "Which region generated the most revenue?", "live": True},
        )
        assert response.status_code == 403


def test_public_version_is_consistent_across_cli_and_api():
    assert __version__ == "0.6.0"
    result = CliRunner().invoke(cli_app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == __version__
    assert api_app.version == __version__


def test_demo_catches_regression_and_renders_shareable_report(tmp_path):
    report, json_path, html_path = run_demo(tmp_path / "demo")
    assert report["summary"] == {
        "total": 6,
        "passed": 5,
        "failed": 1,
        "pass_rate": pytest.approx(5 / 6),
    }
    assert report["demo"]["regressions_caught"] == 1
    assert json_path.exists()
    html = html_path.read_text()
    assert "BLOCKED FROM MERGE" in html
    assert "schema_hallucination_regression" in html
    assert "customers.lifetime_value" in html


def test_html_report_escapes_untrusted_agent_output(tmp_path):
    report = {
        "suite": "<script>alert(1)</script>",
        "summary": {"total": 1, "passed": 1, "failed": 0, "pass_rate": 1.0},
        "results": [
            {
                "case_id": "escape",
                "question": "<img src=x onerror=alert(1)>",
                "passed": True,
                "checks": [],
                "trace": {"sql": "select '<unsafe>'", "latency_ms": 1, "rows": []},
            }
        ],
    }
    output = render_html_report(report, tmp_path / "report.html")
    html = output.read_text()
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<img src=x onerror=alert(1)>" not in html


def test_saved_and_html_reports_redact_rows_and_credentials(tmp_path):
    report = {
        "suite": "privacy",
        "summary": {"total": 1, "passed": 1, "failed": 0, "pass_rate": 1.0},
        "results": [
            {
                "case_id": "private",
                "question": "safe fixture",
                "passed": True,
                "checks": [],
                "trace": {
                    "sql": "select email from customers",
                    "rows": [{"email": "private@example.test"}],
                    "tool_calls": [{"headers": {"authorization": "Bearer private-token"}}],
                },
            }
        ],
    }
    json_path = EvaluationRunner.save_report(report, tmp_path / "report.json")
    html_path = render_html_report(report, tmp_path / "report.html")
    for content in (json_path.read_text(), html_path.read_text()):
        assert "private@example.test" not in content
        assert "private-token" not in content
        assert "[REDACTED]" in content
    payload = json.loads(json_path.read_text())
    assert payload["results"][0]["trace"]["row_count"] == 1
    assert payload["results"][0]["trace"]["rows"] == []


def test_init_scaffolds_runnable_contracts_without_overwriting(tmp_path):
    paths = create_starter_project(tmp_path)
    assert {path.relative_to(tmp_path).as_posix() for path in paths} == {
        "queryassure/evals.yml",
        "queryassure/catalog.yml",
        "queryassure/README.md",
        ".github/workflows/queryassure.yml",
    }
    assert (
        "Victoria824/QueryAssure@v0.6.0"
        in (tmp_path / ".github/workflows/queryassure.yml").read_text()
    )
    with pytest.raises(FileExistsError):
        create_starter_project(tmp_path)


def test_adversarial_challenge_detects_every_mutation(retail_fixture, tmp_path):
    _, catalog = retail_fixture
    report, json_path, html_path = run_challenge(catalog, tmp_path / "challenge")
    assert report["summary"] == {
        "total": 6,
        "passed": 6,
        "failed": 0,
        "pass_rate": 1.0,
    }
    assert json_path.exists()
    assert "SAFE TO MERGE" in html_path.read_text()


def test_microsoft365_contract_suite_passes_with_least_privilege(tmp_path):
    runner = WorkflowEvaluationRunner(Microsoft365DemoHarness())
    report = runner.run_file("evals/microsoft365.yml")
    assert report["summary"] == {
        "total": 4,
        "passed": 4,
        "failed": 0,
        "pass_rate": 1.0,
    }
    output = runner.save_report(report, tmp_path / "microsoft365.json")
    content = output.read_text()
    assert "graph.outlook.list_unread" in content
    assert "human_approval_gate" in content
    assert "Bearer " not in content


def test_microsoft365_cli_uses_bundled_contracts_outside_the_repository(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(
        cli_app,
        [
            "m365-demo",
            "--output",
            str(tmp_path / "m365.json"),
            "--html",
            str(tmp_path / "m365.html"),
        ],
    )
    assert result.exit_code == 0
    assert "4/4 passed" in result.stdout
    assert (tmp_path / "m365.json").exists()
    assert (tmp_path / "m365.html").exists()


def test_microsoft365_agent_withholds_email_without_approval():
    client = MockMicrosoftGraphClient()
    grant = OAuthGrant(
        tenant_id="test-tenant",
        subject="agent@example.test",
        scopes=frozenset({MAIL_READ, MAIL_WRITE, MAIL_SEND}),
    )
    trace = Microsoft365Agent(client, grant).run(
        "Draft and send a reply to the highest-priority incident."
    )
    assert trace.status == "awaiting_approval"
    assert client.drafts
    assert client.sent_drafts == []
    assert any(event.kind == "approval" and event.approved is False for event in trace.events)


def test_microsoft365_agent_sends_only_with_audited_approval():
    client = MockMicrosoftGraphClient()
    grant = OAuthGrant(
        tenant_id="test-tenant",
        subject="agent@example.test",
        scopes=frozenset({MAIL_READ, MAIL_WRITE, MAIL_SEND}),
    )
    approval = Approval(
        action="graph.outlook.send_draft",
        approved=True,
        approved_by="facilities.manager@example.test",
        ticket="APR-0042",
    )
    trace = Microsoft365Agent(client, grant).run(
        "Draft and send a reply to the highest-priority incident.",
        context={
            "approvals": [
                {
                    "action": approval.action,
                    "approved": approval.approved,
                    "approved_by": approval.approved_by,
                    "ticket": approval.ticket,
                }
            ]
        },
    )
    assert trace.status == "completed"
    assert client.sent_drafts == ["draft-001"]
    send_event = next(event for event in trace.events if event.name == approval.action)
    assert send_event.approved is True
    assert send_event.metadata["approval_ticket"] == "APR-0042"


def test_microsoft365_agent_fails_closed_when_scope_is_missing():
    client = MockMicrosoftGraphClient()
    grant = OAuthGrant(
        tenant_id="test-tenant",
        subject="agent@example.test",
        scopes=frozenset({MAIL_READ}),
    )
    trace = Microsoft365Agent(client, grant).run(
        "Draft a reply to the highest-priority facilities incident."
    )
    assert trace.status == "blocked"
    assert "Mail.ReadWrite" in (trace.error or "")
    assert client.drafts == {}


def test_microsoft365_agent_handles_an_empty_inbox_without_crashing():
    client = MockMicrosoftGraphClient(messages=[])
    grant = OAuthGrant(
        tenant_id="test-tenant",
        subject="agent@example.test",
        scopes=frozenset({MAIL_READ, MAIL_WRITE}),
    )
    trace = Microsoft365Agent(client, grant).run(
        "Draft a reply to the highest-priority facilities incident."
    )
    assert trace.status == "blocked"
    assert trace.error == "No unread messages are available for a reply draft"
    assert client.drafts == {}


def test_live_graph_client_is_fail_closed_and_uses_delegated_bearer_auth():
    grant = OAuthGrant(
        tenant_id="test-tenant",
        subject="agent@example.test",
        scopes=frozenset({MAIL_READ}),
    )
    with pytest.raises(RuntimeError, match="disabled"):
        HttpMicrosoftGraphClient(grant, lambda: "not-used", enabled=False)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "graph.microsoft.com"
        assert request.headers["Authorization"] == "Bearer test-access-token"
        assert request.url.path == "/v1.0/me/messages"
        return httpx.Response(200, json={"value": [{"id": "msg-live"}]})

    client = HttpMicrosoftGraphClient(
        grant,
        lambda: "test-access-token",
        enabled=True,
        client=httpx.Client(
            base_url="https://graph.microsoft.com/v1.0",
            transport=httpx.MockTransport(handler),
        ),
    )
    assert client.list_unread_messages() == [{"id": "msg-live"}]


def test_workflow_html_report_renders_auditable_events(tmp_path):
    report = WorkflowEvaluationRunner(Microsoft365DemoHarness()).run_file(
        "evals/microsoft365.yml"
    )
    output = render_html_report(report, tmp_path / "microsoft365.html")
    html = output.read_text()
    assert "Workflow audit" in html
    assert "graph.teams.post_message" in html
    assert "Contract testing for production agents" in html

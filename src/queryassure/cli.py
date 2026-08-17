from __future__ import annotations

import json
import os
import webbrowser
from importlib import resources
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from .adapters import HttpAgentAdapter
from .agent import OpenAIProvider, SqlAgent
from .benchmark import build_leaderboard, save_leaderboard
from .challenge import run_challenge
from .data_quality import validate_retail_data
from .datasets import dataset_catalog, install_dataset
from .demo import run_demo
from .enterprise import run_enterprise_demo
from .evidence import (
    EvidenceVerificationError,
    read_evidence_bundle,
    sign_evidence,
    verify_evidence,
    write_evidence_bundle,
)
from .generator import generate_retail_database
from .governance import EnterprisePolicy, PolicyEngine, PolicyRequest
from .metadata import Catalog
from .microsoft365 import Microsoft365DemoHarness
from .reporting import render_html_report
from .runner import EvaluationRunner, compare_reports
from .scaffolding import create_starter_project
from .workflows import WorkflowEvaluationRunner

app = typer.Typer(
    no_args_is_help=True,
    help="Contract testing, security, and evaluation infrastructure for AI agents.",
)
dataset_app = typer.Typer(no_args_is_help=True, help="Discover and install evaluation datasets.")
catalog_app = typer.Typer(no_args_is_help=True, help="Build grounding catalogs from data tools.")
policy_app = typer.Typer(no_args_is_help=True, help="Evaluate enterprise agent policy packs.")
evidence_app = typer.Typer(no_args_is_help=True, help="Sign and verify audit evidence bundles.")
app.add_typer(dataset_app, name="dataset")
app.add_typer(catalog_app, name="catalog")
app.add_typer(policy_app, name="policy")
app.add_typer(evidence_app, name="evidence")
console = Console()


def _version_callback(value: bool) -> None:
    if value:
        console.print(__version__)
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the installed QueryAssure version and exit.",
    ),
) -> None:
    """Evaluate and release AI agents with confidence."""


def _build_agent(database: Path, catalog_path: Path, live: bool = False) -> SqlAgent:
    catalog = Catalog.from_yaml(catalog_path)
    provider = OpenAIProvider() if live else None
    return SqlAgent(database, catalog, provider)


def _print_report_table(report: dict, output: Path) -> None:
    table = Table(title=report["suite"])
    table.add_column("Case")
    table.add_column("Result")
    table.add_column("Latency", justify="right")
    for result in report["results"]:
        table.add_row(
            result["case_id"],
            "[green]PASS[/green]" if result["passed"] else "[red]FAIL[/red]",
            f"{result['trace']['latency_ms']:.1f} ms",
        )
    console.print(table)
    summary = report["summary"]
    console.print(f"{summary['passed']}/{summary['total']} passed · JSON report: {output}")


@app.command()
def demo(
    output: Path = typer.Option(
        Path("queryassure-demo"),
        help="Directory for the deterministic database and shareable reports",
    ),
    open_report: bool = typer.Option(
        True,
        "--open/--no-open",
        help="Open the generated HTML report in the default browser",
    ),
) -> None:
    """Run a zero-key demo that catches an injected SQL Agent regression."""
    report, json_path, html_path = run_demo(output)
    _print_report_table(report, json_path)
    caught = report["demo"]["regressions_caught"]
    expected = report["demo"]["expected_regressions"]
    if caught == expected:
        console.print(
            "\n[bold green]✓ Regression caught as designed.[/bold green] "
            "[bold red]BLOCKED FROM MERGE[/bold red]"
        )
        console.print(f"Shareable evidence: [link=file://{html_path.resolve()}]{html_path}[/link]")
    else:  # pragma: no cover - defensive path
        console.print("[red]The demo gate did not catch the expected regression.[/red]")
        raise typer.Exit(1)
    if open_report:
        webbrowser.open(html_path.resolve().as_uri())


@app.command()
def challenge(
    catalog: Path = typer.Option(Path("metadata/catalog.yml"), exists=True),
    output: Path = typer.Option(Path("reports/challenge"), help="Challenge report directory"),
) -> None:
    """Mutation-test the gates with unsafe SQL and schema hallucinations."""
    report, json_path, html_path = run_challenge(Catalog.from_yaml(catalog), output)
    _print_report_table(report, json_path)
    console.print(f"HTML report: {html_path}")
    if report["summary"]["failed"]:
        raise typer.Exit(1)


@app.command("m365-demo")
def microsoft365_demo(
    suite: Path | None = typer.Option(
        None,
        exists=True,
        help="Optional workflow contract suite; defaults to the bundled M365 contracts",
    ),
    output: Path = typer.Option(Path("reports/microsoft365.json")),
    html: Path = typer.Option(
        Path("reports/microsoft365.html"),
        help="Shareable Microsoft 365 agent evidence report",
    ),
) -> None:
    """Run zero-key Outlook/Teams contracts with OAuth and approval gates."""
    runner = WorkflowEvaluationRunner(Microsoft365DemoHarness())
    if suite is None:
        bundled = resources.files("queryassure").joinpath("resources/microsoft365.yml")
        with resources.as_file(bundled) as bundled_suite:
            report = runner.run_file(bundled_suite)
    else:
        report = runner.run_file(suite)
    runner.save_report(report, output)
    render_html_report(report, html)
    _print_report_table(report, output)
    console.print(f"HTML report: {html}")
    console.print(
        "[green]Verified[/green] least-privilege Graph scopes, human approvals, "
        "audit completeness, and credential hygiene."
    )
    if report["summary"]["failed"]:
        raise typer.Exit(1)


@app.command("enterprise-demo")
def enterprise_demo(
    output: Path = typer.Option(
        Path("reports/enterprise-evidence.json"),
        help="Tamper-evident governance evidence bundle",
    ),
    html: Path = typer.Option(
        Path("reports/enterprise-governance.html"),
        help="Shareable enterprise control report",
    ),
) -> None:
    """Run tenant, RBAC, approval, and break-glass controls with signed evidence."""
    report, evidence_path, verified = run_enterprise_demo(output)
    render_html_report(report, html)
    _print_report_table(report, evidence_path)
    console.print(f"HTML report: {html}")
    console.print(
        "[green]Verified[/green] tenant isolation, resource authorization, data "
        "classification, approval obligations, break-glass controls, and evidence integrity."
    )
    if report["summary"]["failed"] or not verified:
        raise typer.Exit(1)


def _policy_from_path(path: Path | None) -> EnterprisePolicy:
    if path is not None:
        return EnterprisePolicy.from_yaml(path)
    bundled = resources.files("queryassure").joinpath("resources/enterprise-policy.yml")
    with resources.as_file(bundled) as bundled_policy:
        return EnterprisePolicy.from_yaml(bundled_policy)


@policy_app.command("evaluate")
def evaluate_policy(
    tenant: str = typer.Option(..., help="Authenticated tenant identifier"),
    subject: str = typer.Option(..., help="Authenticated actor"),
    role: list[str] = typer.Option(..., "--role", help="Repeatable principal role"),
    action: str = typer.Option(..., help="Agent action, for example sql.read"),
    resource: str = typer.Option(..., help="Governed resource identifier"),
    resource_tenant: str | None = typer.Option(None, help="Resource owner tenant"),
    classification: str = typer.Option("internal", help="Data classification"),
    environment: str = typer.Option("production", help="Deployment environment"),
    approval_ticket: str | None = typer.Option(None, help="Non-secret approval reference"),
    break_glass: bool = typer.Option(False, help="Request emergency access"),
    justification: str | None = typer.Option(None, help="Break-glass justification"),
    policy: Path | None = typer.Option(None, exists=True, help="Policy pack YAML"),
) -> None:
    """Evaluate one action with deny-by-default enterprise policy-as-code."""
    request = PolicyRequest(
        tenant_id=tenant,
        resource_tenant_id=resource_tenant,
        subject=subject,
        roles=frozenset(role),
        action=action,
        resource=resource,
        environment=environment,
        classification=classification,
        approval_ticket=approval_ticket,
        break_glass=break_glass,
        justification=justification,
    )
    decision = PolicyEngine(_policy_from_path(policy)).evaluate(request)
    console.print_json(data=decision.to_dict())
    if not decision.allowed:
        raise typer.Exit(1)


def _evidence_key(key_env: str) -> bytes:
    raw = os.environ.get(key_env, "")
    if len(raw.encode()) < 32:
        console.print(
            f"[red]{key_env} must contain an operator-managed key of at least 32 bytes[/red]"
        )
        raise typer.Exit(2)
    return raw.encode()


@evidence_app.command("sign")
def sign_report(
    report: Path = typer.Argument(..., exists=True, help="QueryAssure JSON report"),
    output: Path = typer.Option(Path("reports/evidence.json")),
    key_id: str = typer.Option(..., help="KMS or secret-manager key identifier"),
    key_env: str = typer.Option(
        "QUERYASSURE_EVIDENCE_KEY",
        help="Environment variable containing the signing key",
    ),
) -> None:
    """Redact and sign a report without exposing signing material in arguments."""
    envelope = sign_evidence(
        json.loads(report.read_text()),
        _evidence_key(key_env),
        key_id=key_id,
    )
    target = write_evidence_bundle(envelope, output)
    console.print(f"[green]Signed[/green] {target} with key id {key_id}")


@evidence_app.command("verify")
def verify_report(
    evidence: Path = typer.Argument(..., exists=True, help="Signed evidence bundle"),
    key_env: str = typer.Option(
        "QUERYASSURE_EVIDENCE_KEY",
        help="Environment variable containing the verification key",
    ),
    max_age_seconds: float | None = typer.Option(None, min=1),
) -> None:
    """Fail when an evidence bundle is stale, malformed, or tampered with."""
    try:
        verify_evidence(
            read_evidence_bundle(evidence),
            _evidence_key(key_env),
            max_age_seconds=max_age_seconds,
        )
    except EvidenceVerificationError as exc:
        console.print(f"[red]Evidence verification failed:[/red] {exc}")
        raise typer.Exit(1) from exc
    console.print(f"[bold green]VERIFIED[/bold green] {evidence}")


@app.command("init")
def init_project(
    directory: Path = typer.Argument(Path("."), help="Repository to scaffold"),
    force: bool = typer.Option(False, help="Overwrite existing QueryAssure starter files"),
) -> None:
    """Add starter contracts and a pull-request quality gate to a repository."""
    try:
        paths = create_starter_project(directory, force=force)
    except FileExistsError as exc:
        console.print(f"[red]{exc}[/red] Use --force to replace them.")
        raise typer.Exit(2) from exc
    console.print("[green]Created a runnable SQL Agent quality gate:[/green]")
    for path in paths:
        console.print(f"  • {path}")


@app.command()
def report(
    source: Path = typer.Argument(..., exists=True, help="QueryAssure JSON report"),
    output: Path = typer.Option(Path("reports/queryassure.html"), help="HTML report path"),
) -> None:
    """Turn a JSON evaluation report into self-contained, shareable HTML."""
    target = render_html_report(json.loads(source.read_text()), output)
    console.print(f"[green]Created[/green] {target}")


@app.command()
def seed(
    database: Path = typer.Option(Path("data/retail.duckdb"), help="Output DuckDB file"),
    orders: int = typer.Option(8_000, min=100, max=2_000_000),
    random_seed: int = typer.Option(20260722, "--seed"),
) -> None:
    """Generate the deterministic retail evaluation database."""
    path = generate_retail_database(database, seed=random_seed, orders=orders)
    console.print(f"[green]Created[/green] {path} with {orders:,} orders")


@app.command("validate-data")
def validate_data(
    database: Path = typer.Option(Path("data/retail.duckdb"), exists=True),
    output: Path | None = typer.Option(None, help="Optional JSON report path"),
) -> None:
    """Validate synthetic-data integrity, coverage, privacy, and designed signals."""
    report = validate_retail_data(database)
    table = Table(title=f"Synthetic data · {report['summary']['fingerprint']}")
    table.add_column("Check")
    table.add_column("Result")
    table.add_column("Observed", justify="right")
    for check in report["checks"]:
        table.add_row(
            check["name"],
            "[green]PASS[/green]" if check["passed"] else "[red]FAIL[/red]",
            str(check["value"]),
        )
    console.print(table)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2))
    if report["summary"]["failed"]:
        raise typer.Exit(1)


@app.command("test")
def test_suite(
    suite: Path = typer.Option(Path("evals/retail.yml"), exists=True),
    database: Path = typer.Option(Path("data/retail.duckdb")),
    catalog: Path = typer.Option(Path("metadata/catalog.yml"), exists=True),
    output: Path = typer.Option(Path("reports/latest.json")),
    html: Path = typer.Option(Path("reports/latest.html"), help="Shareable HTML report path"),
    live: bool = typer.Option(False, help="Use the configured OpenAI model instead of demo mode"),
) -> None:
    """Run deterministic and agent-level quality checks."""
    if not database.exists():
        generate_retail_database(database)
    agent = _build_agent(database, catalog, live=live)
    runner = EvaluationRunner(agent, database, agent.catalog)
    report = runner.run_file(suite)
    runner.save_report(report, output)
    render_html_report(report, html)
    _print_report_table(report, output)
    console.print(f"HTML report: {html}")
    summary = report["summary"]
    if summary["failed"]:
        raise typer.Exit(1)


@app.command("test-http")
def test_http(
    url: str = typer.Option(..., help="Agent endpoint accepting {question} JSON"),
    suite: Path = typer.Option(Path("evals/retail.yml"), exists=True),
    database: Path = typer.Option(Path("data/retail.duckdb"), exists=True),
    catalog: Path = typer.Option(Path("metadata/catalog.yml"), exists=True),
    output: Path = typer.Option(Path("reports/http-latest.json")),
    html: Path = typer.Option(Path("reports/http-latest.html"), help="Shareable HTML report path"),
) -> None:
    """Run the same contract suite against any HTTP-accessible SQL agent."""
    metadata = Catalog.from_yaml(catalog)
    runner = EvaluationRunner(HttpAgentAdapter(url), database, metadata)
    report = runner.run_file(suite)
    runner.save_report(report, output)
    render_html_report(report, html)
    console.print_json(data=report["summary"])
    console.print(f"HTML report: {html}")
    if report["summary"]["failed"]:
        raise typer.Exit(1)


@dataset_app.command("list")
def list_datasets() -> None:
    """Show bundled, generated, and external benchmark sources."""
    table = Table(title="QueryAssure datasets")
    for column in ("Name", "Purpose", "License", "Bundled"):
        table.add_column(column)
    for item in dataset_catalog():
        table.add_row(
            str(item["name"]),
            str(item["purpose"]),
            str(item["license"]),
            "yes" if item["bundled"] else "no",
        )
    console.print(table)


@dataset_app.command("install")
def install_dataset_command(
    name: str,
    output: Path = typer.Option(Path("data/dataset.duckdb")),
    scale: float = typer.Option(0.01, min=0.001, max=100.0),
) -> None:
    """Generate a supported dataset without committing third-party data."""
    try:
        path = install_dataset(name, output, scale=scale)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2) from exc
    console.print(f"[green]Created[/green] {path}")


@catalog_app.command("import-dbt")
def import_dbt_catalog(
    manifest: Path = typer.Option(..., exists=True, help="Path to dbt manifest.json"),
    output: Path = typer.Option(Path("metadata/dbt-catalog.yml")),
) -> None:
    """Convert dbt models, sources, lineage, descriptions, and metrics to a catalog."""
    catalog = Catalog.from_dbt_manifest(manifest)
    catalog.to_yaml(output)
    console.print(
        f"[green]Created[/green] {output} with {len(catalog.tables)} resources and "
        f"{len(catalog.relationships)} lineage edges"
    )


@catalog_app.command("import-postgres")
def import_postgres_catalog(
    dsn: str = typer.Option(..., envvar="DATABASE_URL", help="PostgreSQL DSN or DATABASE_URL"),
    schema: list[str] = typer.Option(["public"], "--schema"),
    output: Path = typer.Option(Path("metadata/postgres-catalog.yml")),
) -> None:
    """Introspect PostgreSQL tables, columns, comments, and foreign keys."""
    catalog = Catalog.from_postgres(dsn, schemas=tuple(schema))
    catalog.to_yaml(output)
    console.print(
        f"[green]Created[/green] {output} with {len(catalog.tables)} tables and "
        f"{len(catalog.relationships)} foreign keys"
    )


@app.command()
def benchmark(
    report: list[str] = typer.Option(
        ...,
        "--report",
        help="Repeatable LABEL=PATH input, for example --report agent-a=reports/a.json",
    ),
    output: Path = typer.Option(Path("benchmarks/leaderboard.json")),
    markdown: Path = typer.Option(Path("benchmarks/leaderboard.md")),
) -> None:
    """Build a correctness-first leaderboard from one or more evaluation reports."""
    parsed: list[tuple[str, dict]] = []
    for value in report:
        if "=" not in value:
            console.print(f"[red]Invalid report {value!r}; expected LABEL=PATH[/red]")
            raise typer.Exit(2)
        label, raw_path = value.split("=", 1)
        path = Path(raw_path)
        if not path.exists():
            console.print(f"[red]Report not found: {path}[/red]")
            raise typer.Exit(2)
        parsed.append((label, json.loads(path.read_text())))
    leaderboard = build_leaderboard(parsed)
    save_leaderboard(leaderboard, json_path=output, markdown_path=markdown)
    table = Table(title="QueryAssure benchmark")
    for column in ("Rank", "Agent", "Pass rate", "Hallucinations", "p95"):
        table.add_column(column)
    for entry in leaderboard["entries"]:
        table.add_row(
            str(entry["rank"]),
            entry["label"],
            f"{entry['pass_rate']:.0%}",
            str(entry["schema_hallucinations"]),
            f"{entry['p95_latency_ms']:.1f} ms",
        )
    console.print(table)
    console.print(f"JSON: {output} · Markdown: {markdown}")


@app.command()
def compare(baseline: Path, candidate: Path) -> None:
    """Compare two JSON reports and fail when quality regresses."""
    result = compare_reports(json.loads(baseline.read_text()), json.loads(candidate.read_text()))
    console.print_json(data=result)
    if result["regression"]:
        raise typer.Exit(1)


@app.command()
def serve(
    host: str = "127.0.0.1",
    port: int = 8000,
    reload: bool = False,
) -> None:
    """Run the reference SQL Agent API."""
    import uvicorn

    os.environ.setdefault("QUERYASSURE_DATABASE", "data/retail.duckdb")
    uvicorn.run("queryassure.api:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    app()

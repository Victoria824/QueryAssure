from __future__ import annotations

import json
import os
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from .adapters import HttpAgentAdapter
from .agent import OpenAIProvider, SqlAgent
from .benchmark import build_leaderboard, save_leaderboard
from .data_quality import validate_retail_data
from .datasets import dataset_catalog, install_dataset
from .generator import generate_retail_database
from .metadata import Catalog
from .runner import EvaluationRunner, compare_reports

app = typer.Typer(
    no_args_is_help=True,
    help="Contract tests, SQL validation, and CI quality gates for reliable SQL agents.",
)
dataset_app = typer.Typer(no_args_is_help=True, help="Discover and install evaluation datasets.")
catalog_app = typer.Typer(no_args_is_help=True, help="Build grounding catalogs from data tools.")
app.add_typer(dataset_app, name="dataset")
app.add_typer(catalog_app, name="catalog")
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
    """Evaluate and release SQL Agents with confidence."""


def _build_agent(database: Path, catalog_path: Path, live: bool = False) -> SqlAgent:
    catalog = Catalog.from_yaml(catalog_path)
    provider = OpenAIProvider() if live else None
    return SqlAgent(database, catalog, provider)


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
    live: bool = typer.Option(False, help="Use the configured OpenAI model instead of demo mode"),
) -> None:
    """Run deterministic and agent-level quality checks."""
    if not database.exists():
        generate_retail_database(database)
    agent = _build_agent(database, catalog, live=live)
    runner = EvaluationRunner(agent, database, agent.catalog)
    report = runner.run_file(suite)
    runner.save_report(report, output)
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
    console.print(
        f"{summary['passed']}/{summary['total']} passed · report written to {output}"
    )
    if summary["failed"]:
        raise typer.Exit(1)


@app.command("test-http")
def test_http(
    url: str = typer.Option(..., help="Agent endpoint accepting {question} JSON"),
    suite: Path = typer.Option(Path("evals/retail.yml"), exists=True),
    database: Path = typer.Option(Path("data/retail.duckdb"), exists=True),
    catalog: Path = typer.Option(Path("metadata/catalog.yml"), exists=True),
    output: Path = typer.Option(Path("reports/http-latest.json")),
) -> None:
    """Run the same contract suite against any HTTP-accessible SQL agent."""
    metadata = Catalog.from_yaml(catalog)
    runner = EvaluationRunner(HttpAgentAdapter(url), database, metadata)
    report = runner.run_file(suite)
    runner.save_report(report, output)
    console.print_json(data=report["summary"])
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

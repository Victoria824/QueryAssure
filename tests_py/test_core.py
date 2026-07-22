from pathlib import Path

import pytest

from dataagentkit.agent import SqlAgent
from dataagentkit.data_quality import validate_retail_data
from dataagentkit.datasets import dataset_catalog
from dataagentkit.generator import generate_retail_database
from dataagentkit.metadata import Catalog
from dataagentkit.runner import EvaluationRunner, compare_reports
from dataagentkit.validators import SqlValidator


@pytest.fixture(scope="session")
def retail_fixture(tmp_path_factory: pytest.TempPathFactory):
    database = generate_retail_database(
        tmp_path_factory.mktemp("dataagentkit") / "retail.duckdb", orders=500
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
    assert not next(
        check for check in pii_checks if check.name == "sensitive_data_policy"
    ).passed


def test_validator_detects_schema_hallucination(retail_fixture):
    _, catalog = retail_fixture
    checks = SqlValidator(catalog).validate(
        "select customer_id, lifetime_value from customers"
    )
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

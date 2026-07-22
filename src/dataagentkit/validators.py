from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import duckdb
from sqlglot import exp, parse_one
from sqlglot.errors import ParseError

from .metadata import Catalog
from .models import CheckResult

WRITE_EXPRESSIONS = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.Merge,
    exp.Command,
)


class SqlValidator:
    def __init__(self, catalog: Catalog, *, dialect: str = "duckdb") -> None:
        self.catalog = catalog
        self.dialect = dialect

    def validate(self, sql: str, expectations: dict[str, Any] | None = None) -> list[CheckResult]:
        expectations = expectations or {}
        checks: list[CheckResult] = []
        try:
            tree = parse_one(sql, read=self.dialect)
        except ParseError as exc:
            return [CheckResult("sql_parse", False, f"SQL could not be parsed: {exc}")]
        checks.append(CheckResult("sql_parse", True, "SQL parsed successfully"))

        writes = [node.key for node in tree.walk() if isinstance(node, WRITE_EXPRESSIONS)]
        checks.append(
            CheckResult(
                "read_only",
                not writes,
                "Query is read-only" if not writes else f"Write operation detected: {writes[0]}",
            )
        )

        cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
        table_names = {
            table.name.lower()
            for table in tree.find_all(exp.Table)
            if table.name.lower() not in cte_names
        }
        known_tables = {name.lower() for name in self.catalog.tables}
        unknown_tables = sorted(table_names - known_tables)
        checks.append(
            CheckResult(
                "schema_tables",
                not unknown_tables,
                "All referenced tables exist"
                if not unknown_tables
                else f"Unknown tables: {', '.join(unknown_tables)}",
                details={"referenced_tables": sorted(table_names)},
            )
        )

        alias_map: dict[str, str] = {}
        for table in tree.find_all(exp.Table):
            alias_map[(table.alias_or_name or table.name).lower()] = table.name.lower()
        all_columns = {
            column.lower()
            for table in self.catalog.tables.values()
            for column in table.get("columns", {})
        }
        unknown_columns: set[str] = set()
        referenced_columns: set[str] = set()
        for column in tree.find_all(exp.Column):
            column_name = column.name.lower()
            table_alias = column.table.lower() if column.table else ""
            referenced_columns.add(f"{table_alias}.{column_name}" if table_alias else column_name)
            if column_name == "*":
                continue
            if table_alias and table_alias in alias_map:
                actual_table = alias_map[table_alias]
                table_columns = {
                    name.lower()
                    for name in self.catalog.tables.get(actual_table, {}).get("columns", {})
                }
                if column_name not in table_columns:
                    unknown_columns.add(f"{actual_table}.{column_name}")
            elif column_name not in all_columns:
                # Output aliases are allowed in ORDER BY and similar clauses.
                select_aliases = {item.alias.lower() for item in tree.expressions if item.alias}
                if column_name not in select_aliases:
                    unknown_columns.add(column_name)
        checks.append(
            CheckResult(
                "schema_columns",
                not unknown_columns,
                "All referenced columns are grounded in metadata"
                if not unknown_columns
                else f"Unknown columns: {', '.join(sorted(unknown_columns))}",
                details={"referenced_columns": sorted(referenced_columns)},
            )
        )

        required_tables = {name.lower() for name in expectations.get("required_tables", [])}
        missing_tables = sorted(required_tables - table_names)
        checks.append(
            CheckResult(
                "required_tables",
                not missing_tables,
                "Required tables are present"
                if not missing_tables
                else f"Missing required tables: {', '.join(missing_tables)}",
            )
        )

        normalized_sql = re.sub(r"\s+", " ", sql.lower())
        forbidden = {
            item.lower() for item in self.catalog.policies.get("forbidden_columns", [])
        } | {item.lower() for item in expectations.get("forbidden_columns", [])}
        violations = sorted(item for item in forbidden if item in normalized_sql)
        checks.append(
            CheckResult(
                "sensitive_data_policy",
                not violations,
                "No restricted columns referenced"
                if not violations
                else f"Restricted columns referenced: {', '.join(violations)}",
            )
        )
        return checks


def execute_read_only(
    database: str | Path, sql: str, *, max_rows: int = 200
) -> tuple[list[str], list[dict[str, Any]]]:
    connection = duckdb.connect(str(database), read_only=True)
    cursor = connection.execute(sql)
    columns = [item[0] for item in cursor.description or []]
    raw_rows = cursor.fetchmany(max_rows)
    connection.close()
    rows = [dict(zip(columns, row, strict=False)) for row in raw_rows]
    return columns, rows


def canonical_rows(rows: list[dict[str, Any]]) -> list[tuple[str, ...]]:
    normalized: list[tuple[str, ...]] = []
    for row in rows:
        normalized.append(
            tuple("<null>" if value is None else str(value) for value in row.values())
        )
    return sorted(normalized)

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import duckdb
from sqlglot import exp, parse
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

DENIED_FUNCTIONS = {
    "csv_scan",
    "duckdb_secrets",
    "glob",
    "iceberg_scan",
    "mysql_scan",
    "parquet_scan",
    "postgres_scan",
    "query",
    "query_table",
    "read_blob",
    "read_csv",
    "read_csv_auto",
    "read_json",
    "read_json_auto",
    "read_ndjson",
    "read_parquet",
    "read_text",
    "read_xlsx",
    "sqlite_scan",
    "st_read",
    "which_secret",
}


class SqlValidator:
    def __init__(self, catalog: Catalog, *, dialect: str = "duckdb") -> None:
        self.catalog = catalog
        self.dialect = dialect

    def validate(self, sql: str, expectations: dict[str, Any] | None = None) -> list[CheckResult]:
        expectations = expectations or {}
        checks: list[CheckResult] = []
        try:
            statements = [statement for statement in parse(sql, read=self.dialect) if statement]
        except ParseError as exc:
            return [CheckResult("sql_parse", False, f"SQL could not be parsed: {exc}")]
        if len(statements) != 1:
            return [
                CheckResult(
                    "sql_parse",
                    False,
                    "Exactly one SQL statement is required",
                    details={"statement_count": len(statements)},
                )
            ]
        tree = statements[0]
        checks.append(CheckResult("sql_parse", True, "SQL parsed successfully"))

        writes = [node.key for node in tree.walk() if isinstance(node, WRITE_EXPRESSIONS)]
        query_only = isinstance(tree, exp.Query)
        checks.append(
            CheckResult(
                "read_only",
                query_only and not writes,
                "Query is a single read-only SELECT"
                if query_only and not writes
                else (
                    f"Write operation detected: {writes[0]}"
                    if writes
                    else f"Statement type is not allowed: {tree.key}"
                ),
            )
        )

        cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
        known_tables = {name.lower() for name in self.catalog.tables}

        def resolved_table_name(table: exp.Table) -> str:
            bare = table.name.lower()
            schema = table.db.lower() if table.db else ""
            qualified = f"{schema}.{bare}" if schema else bare
            if qualified in known_tables:
                return qualified
            if bare in known_tables:
                return bare
            matches = [name for name in known_tables if name.endswith(f".{bare}")]
            return matches[0] if len(matches) == 1 else qualified

        table_names = {
            resolved_table_name(table)
            for table in tree.find_all(exp.Table)
            if table.name.lower() not in cte_names
        }
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
            alias_map[(table.alias_or_name or table.name).lower()] = resolved_table_name(table)
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

        denied_functions: set[str] = set()
        for function in tree.find_all(exp.Func):
            name = function.name if isinstance(function, exp.Anonymous) else function.sql_name()
            if str(name).lower() in DENIED_FUNCTIONS:
                denied_functions.add(str(name).lower())
        checks.append(
            CheckResult(
                "external_access",
                not denied_functions,
                "No external file, network, extension, or secret functions referenced"
                if not denied_functions
                else (
                    "External access functions are not allowed: "
                    f"{', '.join(sorted(denied_functions))}"
                ),
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

        forbidden = {
            item.lower() for item in self.catalog.policies.get("forbidden_columns", [])
        } | {item.lower() for item in expectations.get("forbidden_columns", [])}
        forbidden_qualified = {item for item in forbidden if "." in item}
        forbidden_bare = {item.rsplit(".", 1)[-1] for item in forbidden}
        referenced_sensitive: set[str] = set()
        for column in tree.find_all(exp.Column):
            column_name = column.name.lower()
            table_alias = column.table.lower() if column.table else ""
            if column_name == "*":
                if table_alias and table_alias in alias_map:
                    candidate_tables = {alias_map[table_alias]}
                else:
                    candidate_tables = table_names
                for table_name in candidate_tables:
                    for item in forbidden_qualified:
                        if item.startswith(f"{table_name}."):
                            referenced_sensitive.add(item)
                continue
            if table_alias and table_alias in alias_map:
                qualified = f"{alias_map[table_alias]}.{column_name}"
                if qualified in forbidden_qualified or column_name in forbidden:
                    referenced_sensitive.add(qualified)
            elif column_name in forbidden_bare or column_name in forbidden:
                candidates = {
                    f"{table_name}.{column_name}"
                    for table_name in table_names
                    if column_name
                    in {
                        name.lower()
                        for name in self.catalog.tables.get(table_name, {}).get("columns", {})
                    }
                }
                referenced_sensitive.update(candidates or {column_name})
        for star in tree.find_all(exp.Star):
            if isinstance(star.parent, exp.Column):
                continue
            for table_name in table_names:
                referenced_sensitive.update(
                    item for item in forbidden_qualified if item.startswith(f"{table_name}.")
                )
        dynamic_projections = [
            node
            for node in tree.walk()
            if isinstance(node, (exp.Columns, exp.PositionalColumn))
        ]
        if dynamic_projections:
            for table_name in table_names:
                referenced_sensitive.update(
                    item for item in forbidden_qualified if item.startswith(f"{table_name}.")
                )
        violations = sorted(referenced_sensitive)
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
    database: str | Path,
    sql: str,
    *,
    max_rows: int = 200,
    timeout_seconds: float = 10.0,
    memory_limit: str = "512MB",
    max_temp_directory_size: str = "512MB",
    threads: int = 2,
) -> tuple[list[str], list[dict[str, Any]]]:
    try:
        statements = [statement for statement in parse(sql, read="duckdb") if statement]
    except ParseError as exc:
        raise ValueError(f"SQL could not be parsed: {exc}") from exc
    if len(statements) != 1 or not isinstance(statements[0], exp.Query):
        raise ValueError("Execution requires exactly one read-only query")

    connection = duckdb.connect(
        str(database),
        read_only=True,
        config={
            "allow_unsigned_extensions": "false",
            "autoinstall_known_extensions": "false",
            "autoload_known_extensions": "false",
            "enable_external_access": "false",
            "memory_limit": memory_limit,
            "max_temp_directory_size": max_temp_directory_size,
            "threads": str(max(1, threads)),
        },
    )
    timer = threading.Timer(max(0.01, timeout_seconds), connection.interrupt)
    timer.daemon = True
    try:
        connection.execute("SET allow_community_extensions = false")
        connection.execute("SET lock_configuration = true")
        timer.start()
        cursor = connection.execute(sql)
        columns = [item[0] for item in cursor.description or []]
        raw_rows = cursor.fetchmany(max(0, max_rows))
    finally:
        timer.cancel()
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

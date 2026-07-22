from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import duckdb
import yaml

TOKEN_RE = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]+")


@dataclass(slots=True)
class Catalog:
    tables: dict[str, dict[str, Any]] = field(default_factory=dict)
    metrics: dict[str, dict[str, Any]] = field(default_factory=dict)
    relationships: list[dict[str, str]] = field(default_factory=list)
    policies: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_yaml(cls, path: str | Path) -> Catalog:
        payload = yaml.safe_load(Path(path).read_text()) or {}
        return cls(
            tables=payload.get("tables", {}),
            metrics=payload.get("metrics", {}),
            relationships=payload.get("relationships", []),
            policies=payload.get("policies", {}),
        )

    @classmethod
    def from_duckdb(cls, database: str | Path) -> Catalog:
        connection = duckdb.connect(str(database), read_only=True)
        rows = connection.execute(
            """
            select table_name, column_name, data_type
            from information_schema.columns
            where table_schema = 'main'
            order by table_name, ordinal_position
            """
        ).fetchall()
        connection.close()
        return cls.from_column_rows(rows)

    @classmethod
    def from_column_rows(
        cls,
        rows: list[tuple[str, str, str]] | list[tuple[str, str, str, str]],
    ) -> Catalog:
        """Build a catalog from normalized introspection rows.

        Three-value rows contain ``table, column, type``. Four-value rows add a
        column description. Keeping this constructor database-neutral makes
        adapter behaviour easy to test without a running warehouse.
        """
        tables: dict[str, dict[str, Any]] = {}
        for row in rows:
            table, column, data_type = row[:3]
            description = row[3] if len(row) > 3 else ""
            tables.setdefault(table, {"description": "", "columns": {}})
            tables[table]["columns"][column] = {
                "type": data_type,
                "description": description or "",
            }
        return cls(tables=tables)

    @classmethod
    def from_postgres(
        cls,
        dsn: str,
        *,
        schemas: tuple[str, ...] = ("public",),
    ) -> Catalog:
        """Introspect PostgreSQL schemas without persisting credentials.

        ``psycopg`` is an optional dependency so DuckDB-only users keep the
        zero-configuration install path.
        """
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover - depends on optional extra
            raise RuntimeError(
                "Install queryassure[postgres] to import PostgreSQL metadata"
            ) from exc

        with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                select c.table_schema, c.table_name, c.column_name, c.data_type,
                       coalesce(pg_catalog.col_description(
                           format('%I.%I', c.table_schema, c.table_name)::regclass::oid,
                           c.ordinal_position
                       ), '') as description
                from information_schema.columns c
                where c.table_schema = any(%s)
                order by c.table_schema, c.table_name, c.ordinal_position
                """,
                (list(schemas),),
            )
            column_rows = cursor.fetchall()
            cursor.execute(
                """
                select tc.table_schema, tc.table_name, kcu.column_name,
                       ccu.table_schema, ccu.table_name, ccu.column_name
                from information_schema.table_constraints tc
                join information_schema.key_column_usage kcu
                  on tc.constraint_name = kcu.constraint_name
                 and tc.table_schema = kcu.table_schema
                join information_schema.constraint_column_usage ccu
                  on ccu.constraint_name = tc.constraint_name
                 and ccu.table_schema = tc.table_schema
                where tc.constraint_type = 'FOREIGN KEY'
                  and tc.table_schema = any(%s)
                order by tc.table_schema, tc.table_name, kcu.column_name
                """,
                (list(schemas),),
            )
            relationship_rows = cursor.fetchall()

        def qualified(schema: str, table: str) -> str:
            return table if schema == "public" else f"{schema}.{table}"

        normalized = [
            (qualified(schema, table), column, data_type, description)
            for schema, table, column, data_type, description in column_rows
        ]
        catalog = cls.from_column_rows(normalized)
        catalog.relationships = [
            {
                "from": f"{qualified(from_schema, from_table)}.{from_column}",
                "to": f"{qualified(to_schema, to_table)}.{to_column}",
            }
            for (
                from_schema,
                from_table,
                from_column,
                to_schema,
                to_table,
                to_column,
            ) in relationship_rows
        ]
        return catalog

    @classmethod
    def from_dbt_manifest(cls, path: str | Path) -> Catalog:
        """Convert dbt's ``manifest.json`` into grounding metadata."""
        payload = json.loads(Path(path).read_text())
        tables: dict[str, dict[str, Any]] = {}
        relationships: list[dict[str, str]] = []
        resources = {**payload.get("sources", {}), **payload.get("nodes", {})}
        included: dict[str, str] = {}

        for unique_id, node in resources.items():
            if node.get("resource_type") not in {"model", "seed", "snapshot", "source"}:
                continue
            name = node.get("alias") or node.get("identifier") or node.get("name")
            schema = node.get("schema") or ""
            relation_name = str(node.get("relation_name") or "").replace('"', "")
            if relation_name:
                parts = relation_name.split(".")
                table_name = ".".join(parts[-2:]) if len(parts) >= 2 else parts[-1]
            elif schema and schema not in {"main", "public"}:
                table_name = f"{schema}.{name}"
            else:
                table_name = name
            included[unique_id] = table_name
            columns = {
                column_name: {
                    "type": info.get("data_type") or "unknown",
                    "description": info.get("description") or "",
                    **({"classification": info["meta"]["classification"]}
                       if info.get("meta", {}).get("classification") else {}),
                }
                for column_name, info in node.get("columns", {}).items()
            }
            tables[table_name] = {
                "description": node.get("description") or "",
                "columns": columns,
                "dbt_unique_id": unique_id,
                "dbt_tags": node.get("tags", []),
            }

        for unique_id, table_name in included.items():
            node = resources[unique_id]
            for dependency in node.get("depends_on", {}).get("nodes", []):
                if dependency in included:
                    relationships.append(
                        {"from": table_name, "to": included[dependency], "kind": "depends_on"}
                    )

        metrics: dict[str, dict[str, Any]] = {}
        for metric in payload.get("metrics", {}).values():
            name = metric.get("name")
            if name:
                metrics[name] = {
                    "description": metric.get("description") or "",
                    "sql": metric.get("expression") or metric.get("type") or "",
                }
        forbidden_columns = sorted(
            f"{table_name}.{column_name}"
            for table_name, table in tables.items()
            for column_name, column in table.get("columns", {}).items()
            if str(column.get("classification", "")).lower()
            in {"pii", "phi", "restricted", "sensitive"}
        )
        policies = {"forbidden_columns": forbidden_columns} if forbidden_columns else {}
        return cls(
            tables=tables,
            metrics=metrics,
            relationships=relationships,
            policies=policies,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "policies": self.policies,
            "metrics": self.metrics,
            "relationships": self.relationships,
            "tables": self.tables,
        }

    def to_yaml(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(yaml.safe_dump(self.to_dict(), sort_keys=False, allow_unicode=True))
        return target

    def retrieve(self, question: str, limit: int = 6) -> list[dict[str, Any]]:
        query_tokens = {token.lower() for token in TOKEN_RE.findall(question)}
        candidates: list[tuple[float, dict[str, Any]]] = []
        for table_name, table in self.tables.items():
            columns = table.get("columns", {})
            text = " ".join(
                [table_name, str(table.get("description", ""))]
                + [
                    f"{name} {info.get('description', '')} {' '.join(info.get('synonyms', []))}"
                    for name, info in columns.items()
                ]
            ).lower()
            score = sum(1.0 for token in query_tokens if token in text)
            if score:
                candidates.append(
                    (
                        score,
                        {
                            "kind": "table",
                            "name": table_name,
                            "description": table.get("description", ""),
                            "columns": list(columns),
                        },
                    )
                )
        for metric_name, metric in self.metrics.items():
            text = f"{metric_name} {metric.get('description', '')} {metric.get('sql', '')}".lower()
            score = sum(1.2 for token in query_tokens if token in text)
            if score:
                candidates.append(
                    (
                        score,
                        {
                            "kind": "metric",
                            "name": metric_name,
                            "description": metric.get("description", ""),
                            "sql": metric.get("sql", ""),
                        },
                    )
                )
        candidates.sort(key=lambda item: (-item[0], item[1]["name"]))
        return [candidate for _, candidate in candidates[:limit]]

    def schema_prompt(self, context: list[dict[str, Any]] | None = None) -> str:
        selected = {item["name"] for item in context or [] if item["kind"] == "table"}
        if not selected:
            selected = set(self.tables)
        lines: list[str] = []
        for table_name in sorted(selected):
            table = self.tables[table_name]
            columns = ", ".join(table.get("columns", {}).keys())
            lines.append(f"- {table_name}({columns}): {table.get('description', '')}")
        if self.metrics:
            lines.append("Business metrics:")
            for name, metric in self.metrics.items():
                description = metric.get("description", "")
                metric_sql = metric.get("sql", "")
                lines.append(f"- {name}: {description}; SQL={metric_sql}")
        return "\n".join(lines)

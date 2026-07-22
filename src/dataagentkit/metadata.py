from __future__ import annotations

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
        tables: dict[str, dict[str, Any]] = {}
        for table, column, data_type in rows:
            tables.setdefault(table, {"description": "", "columns": {}})
            tables[table]["columns"][column] = {"type": data_type, "description": ""}
        return cls(tables=tables)

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

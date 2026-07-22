from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

import duckdb

from .generator import generate_retail_database


@dataclass(frozen=True, slots=True)
class DatasetInfo:
    name: str
    purpose: str
    setup: str
    license: str
    bundled: bool = False


DATASETS = [
    DatasetInfo(
        "northstar-retail",
        "Deterministic grocery analytics, policies, schema drift, and golden results",
        "queryassure dataset install northstar-retail",
        "Apache-2.0 (synthetic generator)",
        True,
    ),
    DatasetInfo(
        "tpch",
        "Scale and execution-budget testing with reproducible decision-support data",
        "queryassure dataset install tpch --scale 0.1",
        "TPC-H terms; generated locally by DuckDB",
    ),
    DatasetInfo(
        "jaffle-shop",
        "dbt manifests, lineage, semantic metadata, and documentation grounding",
        "Use dbt-labs/jaffle_shop_duckdb and point QueryAssure at its DuckDB file",
        "Apache-2.0",
    ),
    DatasetInfo(
        "chinook",
        "Small cross-dialect examples and contributor tutorials",
        "Download from lerocha/chinook-database, then import its DuckDB/SQL artifact",
        "MIT",
    ),
    DatasetInfo(
        "open-food-facts",
        "Messy multilingual product metadata and real-world grounding tests",
        "Optional user download; never vendored",
        "ODbL (attribution/share-alike requirements apply)",
    ),
]


def dataset_catalog() -> list[dict[str, object]]:
    return [asdict(item) for item in DATASETS]


def generate_tpch_database(path: str | Path, *, scale: float = 0.01) -> Path:
    """Generate TPC-H locally through DuckDB's official extension."""
    if scale <= 0 or scale > 100:
        raise ValueError("scale must be greater than 0 and at most 100")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    connection = duckdb.connect(str(target))
    try:
        connection.execute("install tpch")
        connection.execute("load tpch")
        connection.execute(f"call dbgen(sf={float(scale)})")
        connection.execute("analyze")
    finally:
        connection.close()
    return target


def install_dataset(name: str, path: str | Path, *, scale: float = 0.01) -> Path:
    normalized = name.strip().lower()
    if normalized == "northstar-retail":
        return generate_retail_database(path)
    if normalized == "tpch":
        return generate_tpch_database(path, scale=scale)
    raise ValueError(
        f"{name!r} is an external adapter. Run `queryassure dataset list` for setup guidance."
    )

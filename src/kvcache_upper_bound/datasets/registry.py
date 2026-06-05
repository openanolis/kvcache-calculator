from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_REGISTRY_PATH = Path(__file__).resolve().parent.parent.parent.parent / "datasets" / "registry.json"


def load_registry() -> dict[str, Any]:
    if not _REGISTRY_PATH.exists():
        raise FileNotFoundError(f"Dataset registry not found at {_REGISTRY_PATH}")
    return json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))


def list_datasets() -> list[dict[str, Any]]:
    registry = load_registry()
    return [
        {
            "id": ds["id"],
            "name": ds["name"],
            "tier": ds["tier"],
            "format": ds["format"],
            "request_count": ds.get("request_count"),
            "description": ds["description"],
            "tags": ds.get("tags", []),
        }
        for ds in registry["datasets"]
    ]


def get_dataset(dataset_id: str) -> dict[str, Any]:
    registry = load_registry()
    for ds in registry["datasets"]:
        if ds["id"] == dataset_id:
            return ds
    available = [ds["id"] for ds in registry["datasets"]]
    raise ValueError(
        f"Unknown dataset: {dataset_id!r}. Available: {', '.join(available)}"
    )

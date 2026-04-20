from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from .config import PipelineConfig, TABLE_FILENAMES


def dataset_path(config: PipelineConfig, table_name: str) -> Path:
    try:
        return config.dataset_dir / TABLE_FILENAMES[table_name]
    except KeyError as exc:
        raise KeyError(f"Unknown table: {table_name}") from exc


def load_table(
    config: PipelineConfig,
    table_name: str,
    usecols: list[str] | None = None,
) -> pd.DataFrame:
    path = dataset_path(config, table_name)
    if not path.exists():
        raise FileNotFoundError(f"Expected dataset file at {path}")
    return pd.read_csv(path, usecols=usecols)


def load_applications(config: PipelineConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    train = load_table(config, "application_train")
    test = load_table(config, "application_test")
    return train, test


def save_frame(df: pd.DataFrame, path: Path, index: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".pkl":
        df.to_pickle(path)
        return
    if path.suffix == ".csv":
        df.to_csv(path, index=index)
        return
    raise ValueError(f"Unsupported dataframe format for {path}")


def load_frame(path: Path) -> pd.DataFrame:
    if path.suffix == ".pkl":
        return pd.read_pickle(path)
    if path.suffix == ".csv":
        return pd.read_csv(path)
    raise ValueError(f"Unsupported dataframe format for {path}")


def save_json(payload: dict[str, Any] | list[Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, default=_json_default)


def _json_default(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Object of type {type(value)!r} is not JSON serializable")

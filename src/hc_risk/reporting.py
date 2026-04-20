from __future__ import annotations

from typing import Any

from .config import PipelineConfig
from .io import save_json


def _comparison_slice(metrics: dict[str, Any]) -> dict[str, Any]:
    candidate = metrics.get("blend") if isinstance(metrics.get("blend"), dict) else metrics
    return {
        "roc_auc": candidate.get("roc_auc"),
        "pr_auc": candidate.get("pr_auc"),
        "ks": candidate.get("ks"),
        "brier": candidate.get("brier"),
    }


def update_model_comparison(
    config: PipelineConfig,
    stage_name: str,
    metrics: dict[str, Any],
) -> None:
    path = config.reports_dir / "model_comparison.json"
    payload: dict[str, Any]
    if path.exists():
        import json

        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    else:
        payload = {}
    payload[stage_name] = _comparison_slice(metrics)
    save_json(payload, path)

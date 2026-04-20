from __future__ import annotations

from typing import Iterable

import numpy as np
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    precision_recall_curve,
    roc_auc_score,
)


def ks_statistic(y_true: np.ndarray, y_score: np.ndarray) -> float:
    order = np.argsort(y_score)
    y_true = np.asarray(y_true)[order]
    bad = np.cumsum(y_true == 1) / max((y_true == 1).sum(), 1)
    good = np.cumsum(y_true == 0) / max((y_true == 0).sum(), 1)
    return float(np.max(np.abs(bad - good)))


def psi(expected: Iterable[float], actual: Iterable[float], bins: int = 10) -> float:
    expected = np.asarray(list(expected), dtype=float)
    actual = np.asarray(list(actual), dtype=float)
    quantiles = np.unique(np.quantile(expected, np.linspace(0, 1, bins + 1)))
    if quantiles.size < 3:
        return 0.0
    expected_hist, _ = np.histogram(expected, bins=quantiles)
    actual_hist, _ = np.histogram(actual, bins=quantiles)
    expected_pct = np.clip(expected_hist / max(expected_hist.sum(), 1), 1e-6, None)
    actual_pct = np.clip(actual_hist / max(actual_hist.sum(), 1), 1e-6, None)
    return psi_from_proportions(expected_pct, actual_pct)


def psi_from_proportions(expected_pct: Iterable[float], actual_pct: Iterable[float]) -> float:
    expected_arr = np.clip(np.asarray(list(expected_pct), dtype=float), 1e-6, None)
    actual_arr = np.clip(np.asarray(list(actual_pct), dtype=float), 1e-6, None)
    return float(np.sum((actual_arr - expected_arr) * np.log(actual_arr / expected_arr)))


def categorical_psi(
    expected_labels: Iterable[object],
    actual_labels: Iterable[object],
    categories: Iterable[object] | None = None,
) -> dict[str, float | list[dict[str, float | str]]]:
    expected = np.asarray(list(expected_labels), dtype=object)
    actual = np.asarray(list(actual_labels), dtype=object)
    if categories is None:
        categories = list(dict.fromkeys(expected.tolist() + actual.tolist()))
    ordered_categories = [str(category) for category in categories]
    if not ordered_categories:
        return {"psi": 0.0, "components": []}

    expected_counts = np.asarray([(expected == category).sum() for category in ordered_categories], dtype=float)
    actual_counts = np.asarray([(actual == category).sum() for category in ordered_categories], dtype=float)
    expected_pct = np.clip(expected_counts / max(expected_counts.sum(), 1.0), 1e-6, None)
    actual_pct = np.clip(actual_counts / max(actual_counts.sum(), 1.0), 1e-6, None)
    components = (actual_pct - expected_pct) * np.log(actual_pct / expected_pct)
    payload = []
    for category, expected_share, actual_share, psi_component in zip(
        ordered_categories,
        expected_pct,
        actual_pct,
        components,
        strict=True,
    ):
        payload.append(
            {
                "label": category,
                "expected_share": float(expected_share),
                "actual_share": float(actual_share),
                "psi_component": float(psi_component),
            }
        )
    return {"psi": float(components.sum()), "components": payload}


def calibration_bins(
    y_true: np.ndarray,
    y_score: np.ndarray,
    bins: int = 10,
) -> list[dict[str, float]]:
    edges = np.linspace(0.0, 1.0, bins + 1)
    payload: list[dict[str, float]] = []
    for left, right in zip(edges[:-1], edges[1:], strict=True):
        mask = (y_score >= left) & (y_score < right if right < 1 else y_score <= right)
        if not mask.any():
            continue
        payload.append(
            {
                "bin_left": float(left),
                "bin_right": float(right),
                "avg_prediction": float(np.mean(y_score[mask])),
                "observed_default_rate": float(np.mean(y_true[mask])),
                "count": int(mask.sum()),
            }
        )
    return payload


def binary_classification_metrics(
    y_true: np.ndarray,
    y_score: np.ndarray,
) -> dict[str, float | list[dict[str, float]]]:
    precision, recall, _ = precision_recall_curve(y_true, y_score)
    return {
        "roc_auc": float(roc_auc_score(y_true, y_score)),
        "pr_auc": float(average_precision_score(y_true, y_score)),
        "ks": ks_statistic(y_true, y_score),
        "brier": float(brier_score_loss(y_true, y_score)),
        "precision_at_curve_start": float(precision[0]),
        "recall_at_curve_start": float(recall[0]),
        "calibration_bins": calibration_bins(y_true, y_score),
    }


def rank_average(predictions: list[np.ndarray]) -> np.ndarray:
    if not predictions:
        raise ValueError("No prediction arrays supplied")
    ranks = [pd_rank(pred) for pred in predictions]
    return np.mean(np.vstack(ranks), axis=0)


def pd_rank(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values)
    ranks = np.empty_like(order, dtype=float)
    ranks[order] = np.linspace(0, 1, num=len(values), endpoint=True)
    return ranks

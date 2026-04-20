from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression, LogisticRegression

from .analysis import run_analysis
from .config import PipelineConfig
from .features import explainable_matrix
from .io import save_frame, save_json
from .metrics import binary_classification_metrics, categorical_psi, psi
from .reporting import update_model_comparison
from .sampling import stratified_sample


MISSING_LABEL = "__MISSING__"
OTHER_LABEL = "__OTHER__"


def _is_monotonic(values: list[float], tolerance: float = 1e-9) -> bool:
    if len(values) <= 2:
        return True
    diffs = np.diff(values)
    return bool(np.all(diffs >= -tolerance) or np.all(diffs <= tolerance))


def _bin_stats(labels: pd.Series, y: pd.Series) -> pd.DataFrame:
    label_values = labels.astype(str)
    label_order = pd.Index(pd.unique(label_values))
    frame = pd.DataFrame({"label": label_values, "target": y.astype(int)})
    stats = frame.groupby("label", observed=True)["target"].agg(["count", "sum"]).rename(columns={"sum": "bad"})
    stats = stats.reindex(label_order, fill_value=0)
    stats.index.name = "label"
    stats["good"] = stats["count"] - stats["bad"]
    total_good = max(stats["good"].sum(), 1)
    total_bad = max(stats["bad"].sum(), 1)
    stats["good_pct"] = (stats["good"] + 0.5) / (total_good + 0.5 * len(stats))
    stats["bad_pct"] = (stats["bad"] + 0.5) / (total_bad + 0.5 * len(stats))
    stats["bad_rate"] = stats["bad"] / stats["count"].clip(lower=1)
    stats["woe"] = np.log(stats["good_pct"] / stats["bad_pct"])
    stats["iv_component"] = (stats["good_pct"] - stats["bad_pct"]) * stats["woe"]
    return stats.reset_index()


def _merge_numeric_pair(left: dict[str, float], right: dict[str, float]) -> dict[str, float]:
    count = left["count"] + right["count"]
    bad = left["bad"] + right["bad"]
    return {
        "lower": left["lower"],
        "upper": right["upper"],
        "count": count,
        "bad": bad,
        "bad_rate": bad / max(count, 1),
    }


def _initial_numeric_bins(
    series: pd.Series,
    y: pd.Series,
    max_bins: int,
) -> list[dict[str, float]]:
    clean = series.dropna()
    if clean.nunique() <= 1:
        return []
    upper_bins = min(max(max_bins * 4, 10), max(int(clean.nunique()), 2))
    joined = pd.DataFrame({"value": series, "target": y.astype(int)}).dropna(subset=["value"])
    for bin_count in range(upper_bins, 1, -1):
        try:
            _, edges = pd.qcut(clean, q=bin_count, retbins=True, duplicates="drop")
        except ValueError:
            continue
        edges = np.unique(edges).astype(float)
        if len(edges) < 3:
            continue
        edges[0] = -np.inf
        edges[-1] = np.inf
        labels = pd.cut(joined["value"], bins=edges, include_lowest=True)
        grouped = (
            pd.DataFrame({"label": labels, "target": joined["target"]})
            .groupby("label", observed=True)["target"]
            .agg(["count", "sum"])
            .rename(columns={"sum": "bad"})
            .reset_index()
        )
        bins = []
        for _, row in grouped.iterrows():
            interval = row["label"]
            count = int(row["count"])
            bad = int(row["bad"])
            bins.append(
                {
                    "lower": float(interval.left),
                    "upper": float(interval.right),
                    "count": count,
                    "bad": bad,
                    "bad_rate": bad / max(count, 1),
                }
            )
        if bins:
            return bins
    median = float(clean.median())
    return [
        {"lower": -np.inf, "upper": median, "count": int((clean <= median).sum()), "bad": int(y[clean.index][clean <= median].sum()), "bad_rate": float(y[clean.index][clean <= median].mean())},
        {"lower": median, "upper": np.inf, "count": int((clean > median).sum()), "bad": int(y[clean.index][clean > median].sum()), "bad_rate": float(y[clean.index][clean > median].mean()) if int((clean > median).sum()) else 0.0},
    ]


def _merge_candidate_index(
    bins: list[dict[str, float]],
    min_count: int,
    max_bins: int,
) -> int:
    bad_rates = [item["bad_rate"] for item in bins]
    direction = 0
    violating_pairs: set[int] = set()
    if len(bins) > 2 and not _is_monotonic(bad_rates):
        direction = 1 if bad_rates[-1] >= bad_rates[0] else -1
        for idx in range(len(bad_rates) - 1):
            if direction * (bad_rates[idx + 1] - bad_rates[idx]) < 0:
                violating_pairs.add(max(idx - 1, 0))
                violating_pairs.add(idx)
    candidates = []
    for idx in range(len(bins) - 1):
        left = bins[idx]
        right = bins[idx + 1]
        candidates.append(
            (
                0 if left["count"] < min_count or right["count"] < min_count else 1,
                0 if idx in violating_pairs else 1,
                abs(left["bad_rate"] - right["bad_rate"]),
                left["count"] + right["count"],
                0 if len(bins) > max_bins else 1,
                idx,
            )
        )
    return min(candidates)[-1]


def _supervised_numeric_edges(
    series: pd.Series,
    y: pd.Series,
    min_bin_size: float,
    max_bins: int,
) -> np.ndarray:
    bins = _initial_numeric_bins(series, y, max_bins=max_bins)
    if not bins:
        return np.array([-np.inf, np.inf], dtype=float)
    min_count = max(int(round(series.notna().sum() * min_bin_size)), 1)
    while len(bins) > 1:
        bad_rates = [item["bad_rate"] for item in bins]
        too_many_bins = len(bins) > max_bins
        too_small = any(item["count"] < min_count for item in bins)
        non_monotonic = not _is_monotonic(bad_rates)
        if not (too_many_bins or too_small or non_monotonic):
            break
        merge_idx = _merge_candidate_index(bins, min_count=min_count, max_bins=max_bins)
        bins[merge_idx : merge_idx + 2] = [_merge_numeric_pair(bins[merge_idx], bins[merge_idx + 1])]
    edges = [bins[0]["lower"]]
    edges.extend(item["upper"] for item in bins)
    return np.asarray(edges, dtype=float)


def _apply_rule_labels(series: pd.Series, rule: dict[str, object]) -> pd.Series:
    if rule["type"] == "numeric":
        edges = rule["edges"]
        if edges is None:
            labels = pd.Series(np.where(series.isna(), MISSING_LABEL, "ALL"), index=series.index)
        else:
            labels = pd.cut(series, bins=np.asarray(edges, dtype=float), include_lowest=True).astype(str)
            labels = labels.where(series.notna(), MISSING_LABEL)
    else:
        allowed = set(rule.get("allowed_categories", []))
        labels = series.fillna(MISSING_LABEL).astype(str)
        labels = labels.where(labels.isin(allowed | {MISSING_LABEL}), OTHER_LABEL)
    return labels.astype(str)


def _fit_numeric_rule(
    series: pd.Series,
    y: pd.Series,
    min_bin_size: float,
    max_bins: int = 6,
) -> dict[str, object]:
    clean = series.dropna()
    if clean.nunique() <= 1:
        labels = pd.Series(np.where(series.isna(), MISSING_LABEL, "ALL"), index=series.index)
        table = _bin_stats(labels, y)
        return {
            "type": "numeric",
            "edges": None,
            "mapping": dict(zip(table["label"], table["woe"], strict=False)),
            "table": table,
            "iv": float(table["iv_component"].sum()),
            "binning_strategy": "degenerate",
        }

    chosen_edges = _supervised_numeric_edges(series, y, min_bin_size=min_bin_size, max_bins=max_bins)
    if len(chosen_edges) < 3:
        chosen_edges = np.array([-np.inf, float(clean.median()), np.inf], dtype=float)
    chosen_labels = pd.cut(series, bins=chosen_edges, include_lowest=True).astype(str)
    chosen_labels = chosen_labels.where(series.notna(), MISSING_LABEL)

    table = _bin_stats(chosen_labels, y)
    return {
        "type": "numeric",
        "edges": chosen_edges.tolist() if chosen_edges is not None else None,
        "mapping": dict(zip(table["label"], table["woe"], strict=False)),
        "table": table,
        "iv": float(table["iv_component"].sum()),
        "binning_strategy": "supervised_monotonic_merge",
    }


def _fit_categorical_rule(
    series: pd.Series,
    y: pd.Series,
    min_bin_size: float,
) -> dict[str, object]:
    raw = series.fillna(MISSING_LABEL).astype(str)
    min_count = max(int(len(series) * min_bin_size), 100)
    counts = raw.value_counts(dropna=False)
    allowed = counts[counts >= min_count].index
    grouped = raw.where(raw.isin(allowed), OTHER_LABEL)
    table = _bin_stats(grouped, y)
    return {
        "type": "categorical",
        "mapping": dict(zip(table["label"], table["woe"], strict=False)),
        "table": table,
        "iv": float(table["iv_component"].sum()),
        "allowed_categories": [item for item in allowed if item not in {MISSING_LABEL}],
        "binning_strategy": "frequency_grouping",
    }


class WOETransformer:
    def __init__(self, min_bin_size: float = 0.05, max_bins: int = 6) -> None:
        self.min_bin_size = min_bin_size
        self.max_bins = max_bins
        self.rules_: dict[str, dict[str, object]] = {}
        self.iv_: dict[str, float] = {}

    def fit(self, frame: pd.DataFrame, y: pd.Series) -> "WOETransformer":
        self.rules_.clear()
        self.iv_.clear()
        for feature in frame.columns:
            series = frame[feature]
            if pd.api.types.is_numeric_dtype(series):
                rule = _fit_numeric_rule(series, y, self.min_bin_size, self.max_bins)
            else:
                rule = _fit_categorical_rule(series, y, self.min_bin_size)
            self.rules_[feature] = rule
            self.iv_[feature] = float(rule["iv"])
        return self

    def transform(self, frame: pd.DataFrame, features: list[str] | None = None) -> pd.DataFrame:
        features = features or list(self.rules_)
        transformed = pd.DataFrame(index=frame.index)
        for feature in features:
            rule = self.rules_[feature]
            series = frame[feature] if feature in frame.columns else pd.Series(np.nan, index=frame.index)
            labels = _apply_rule_labels(series, rule)
            mapping = rule["mapping"]
            default_woe = mapping.get(OTHER_LABEL, mapping.get(MISSING_LABEL, 0.0))
            transformed[feature] = labels.map(mapping).fillna(default_woe).astype(float)
        return transformed

    def label_frame(self, frame: pd.DataFrame, features: list[str] | None = None) -> pd.DataFrame:
        features = features or list(self.rules_)
        labeled = pd.DataFrame(index=frame.index)
        for feature in features:
            rule = self.rules_[feature]
            series = frame[feature] if feature in frame.columns else pd.Series(np.nan, index=frame.index)
            labeled[feature] = _apply_rule_labels(series, rule)
        return labeled

    def top_features(self, top_n: int) -> list[str]:
        ordered = sorted(self.iv_.items(), key=lambda item: item[1], reverse=True)
        return [feature for feature, iv in ordered[:top_n] if iv > 0]

    def export_rules(self) -> pd.DataFrame:
        rows = []
        for feature, rule in self.rules_.items():
            table = rule["table"].copy()
            table["feature"] = feature
            table["feature_type"] = rule["type"]
            rows.append(table)
        if not rows:
            return pd.DataFrame(columns=["feature", "label", "woe"])
        return pd.concat(rows, axis=0, ignore_index=True)[
            ["feature", "feature_type", "label", "count", "good", "bad", "bad_rate", "woe", "iv_component"]
        ]


def _iv_from_labels(labels: np.ndarray, target: np.ndarray) -> float:
    return float(_bin_stats(pd.Series(labels), pd.Series(target))["iv_component"].sum())


def _confidence_interval(samples: list[float], fallback: float) -> tuple[float, float]:
    if not samples:
        return fallback, fallback
    lower, upper = np.quantile(np.asarray(samples, dtype=float), [0.025, 0.975])
    return float(lower), float(upper)


def _iv_diagnostics(
    labels: np.ndarray,
    target: np.ndarray,
    bootstrap_rounds: int,
    permutation_rounds: int,
    random_state: int,
) -> dict[str, float]:
    observed = _iv_from_labels(labels, target)
    rng = np.random.default_rng(random_state)
    bootstrap_values = []
    for _ in range(max(bootstrap_rounds, 0)):
        sample_idx = rng.integers(0, len(target), size=len(target))
        bootstrap_values.append(_iv_from_labels(labels[sample_idx], target[sample_idx]))
    iv_ci_lower, iv_ci_upper = _confidence_interval(bootstrap_values, observed)

    permutation_values = []
    for _ in range(max(permutation_rounds, 0)):
        permutation_values.append(_iv_from_labels(labels, rng.permutation(target)))
    iv_p_value = float((np.sum(np.asarray(permutation_values) >= observed) + 1) / (len(permutation_values) + 1))
    return {
        "iv": observed,
        "iv_ci_lower": iv_ci_lower,
        "iv_ci_upper": iv_ci_upper,
        "iv_permutation_p_value": iv_p_value,
    }


def _psi_diagnostics(
    expected_labels: np.ndarray,
    actual_labels: np.ndarray,
    categories: list[str],
    bootstrap_rounds: int,
    permutation_rounds: int,
    random_state: int,
) -> dict[str, object]:
    observed_payload = categorical_psi(expected_labels, actual_labels, categories=categories)
    observed_psi = float(observed_payload["psi"])
    rng = np.random.default_rng(random_state)

    bootstrap_values = []
    for _ in range(max(bootstrap_rounds, 0)):
        expected_idx = rng.integers(0, len(expected_labels), size=len(expected_labels))
        actual_idx = rng.integers(0, len(actual_labels), size=len(actual_labels))
        bootstrap_values.append(
            float(
                categorical_psi(
                    expected_labels[expected_idx],
                    actual_labels[actual_idx],
                    categories=categories,
                )["psi"]
            )
        )
    psi_ci_lower, psi_ci_upper = _confidence_interval(bootstrap_values, observed_psi)

    pooled = np.concatenate([expected_labels, actual_labels], axis=0)
    expected_n = len(expected_labels)
    permutation_values = []
    for _ in range(max(permutation_rounds, 0)):
        shuffled = rng.permutation(pooled)
        permutation_values.append(
            float(
                categorical_psi(
                    shuffled[:expected_n],
                    shuffled[expected_n:],
                    categories=categories,
                )["psi"]
            )
        )
    psi_p_value = float((np.sum(np.asarray(permutation_values) >= observed_psi) + 1) / (len(permutation_values) + 1))
    return {
        "psi": observed_psi,
        "psi_ci_lower": psi_ci_lower,
        "psi_ci_upper": psi_ci_upper,
        "psi_permutation_p_value": psi_p_value,
        "components": observed_payload["components"],
    }


def _scorecard_feature_diagnostics(
    transformer: WOETransformer,
    selected_features: list[str],
    train: pd.DataFrame,
    test: pd.DataFrame,
    config: PipelineConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, int]]:
    if not selected_features:
        empty = pd.DataFrame()
        return empty, empty, {"train": 0, "test": 0}

    monitor_train = stratified_sample(
        train,
        target_col="TARGET",
        max_rows=config.explainable_monitoring_sample_rows,
        random_state=config.random_state,
    )
    if config.explainable_monitoring_sample_rows is None or len(test) <= config.explainable_monitoring_sample_rows:
        monitor_test = test.copy()
    else:
        monitor_test = test.sample(
            n=config.explainable_monitoring_sample_rows,
            random_state=config.random_state,
        ).copy()

    train_labels = transformer.label_frame(monitor_train, selected_features)
    test_labels = transformer.label_frame(monitor_test, selected_features)
    train_target = monitor_train["TARGET"].astype(int).to_numpy()
    diagnostics_rows = []
    bin_rows = []

    for rank, feature in enumerate(selected_features, start=1):
        rule = transformer.rules_[feature]
        categories = rule["table"]["label"].astype(str).tolist()
        feature_train_labels = train_labels[feature].to_numpy(dtype=object)
        feature_test_labels = test_labels[feature].to_numpy(dtype=object)
        iv_payload = _iv_diagnostics(
            feature_train_labels,
            train_target,
            bootstrap_rounds=config.explainable_bootstrap_rounds,
            permutation_rounds=config.explainable_permutation_rounds,
            random_state=config.random_state + rank,
        )
        psi_payload = _psi_diagnostics(
            feature_train_labels,
            feature_test_labels,
            categories=categories,
            bootstrap_rounds=config.explainable_bootstrap_rounds,
            permutation_rounds=config.explainable_permutation_rounds,
            random_state=config.random_state + 1000 + rank,
        )
        diagnostics_rows.append(
            {
                "feature_rank": rank,
                "feature": feature,
                "feature_type": rule["type"],
                "binning_strategy": rule.get("binning_strategy", "unknown"),
                "bin_count": int(len(categories)),
                "train_missing_share": float((feature_train_labels == MISSING_LABEL).mean()),
                "test_missing_share": float((feature_test_labels == MISSING_LABEL).mean()),
                **iv_payload,
                "psi_train_test": float(psi_payload["psi"]),
                "psi_ci_lower": float(psi_payload["psi_ci_lower"]),
                "psi_ci_upper": float(psi_payload["psi_ci_upper"]),
                "psi_permutation_p_value": float(psi_payload["psi_permutation_p_value"]),
            }
        )

        rule_table = rule["table"].copy()
        rule_table["label"] = rule_table["label"].astype(str)
        rule_table = rule_table.set_index("label")
        for component in psi_payload["components"]:
            label = str(component["label"])
            rule_row = rule_table.loc[label] if label in rule_table.index else None
            bin_rows.append(
                {
                    "feature": feature,
                    "feature_type": rule["type"],
                    "label": label,
                    "expected_share": float(component["expected_share"]),
                    "actual_share": float(component["actual_share"]),
                    "psi_component": float(component["psi_component"]),
                    "count": int(rule_row["count"]) if rule_row is not None else 0,
                    "good": int(rule_row["good"]) if rule_row is not None else 0,
                    "bad": int(rule_row["bad"]) if rule_row is not None else 0,
                    "bad_rate": float(rule_row["bad_rate"]) if rule_row is not None else np.nan,
                    "woe": float(rule_row["woe"]) if rule_row is not None else np.nan,
                    "iv_component": float(rule_row["iv_component"]) if rule_row is not None else np.nan,
                }
            )

    return (
        pd.DataFrame(diagnostics_rows).sort_values("feature_rank"),
        pd.DataFrame(bin_rows),
        {"train": int(len(monitor_train)), "test": int(len(monitor_test))},
    )


def _prune_high_vif(frame: pd.DataFrame, threshold: float = 10.0) -> list[str]:
    selected = [col for col in frame.columns if frame[col].nunique() > 1]
    if len(selected) <= 1:
        return selected
    while len(selected) > 1:
        values = frame[selected].to_numpy(dtype=float)
        vifs = {}
        for idx, col in enumerate(selected):
            other = np.delete(values, idx, axis=1)
            target = values[:, idx]
            if other.shape[1] == 0:
                vifs[col] = 1.0
                continue
            model = LinearRegression()
            model.fit(other, target)
            r2 = model.score(other, target)
            vifs[col] = np.inf if r2 >= 0.999 else 1.0 / max(1e-6, 1.0 - r2)
        worst_feature = max(vifs, key=vifs.get)
        if vifs[worst_feature] <= threshold:
            break
        selected.remove(worst_feature)
    return selected


def _fit_sign_constrained_logistic(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    random_state: int,
) -> tuple[LogisticRegression, list[str]]:
    selected = [col for col in X_train.columns if X_train[col].nunique() > 1]
    if not selected:
        raise ValueError("No non-constant features available for scorecard")

    while len(selected) > 1:
        model = LogisticRegression(
            max_iter=1000,
            solver="liblinear",
            C=0.5,
            random_state=random_state,
        )
        model.fit(X_train[selected], y_train)
        coefs = pd.Series(model.coef_[0], index=selected)
        positive = coefs[coefs > 0]
        if positive.empty:
            return model, selected
        selected.remove(positive.sort_values(ascending=False).index[0])

    model = LogisticRegression(
        max_iter=1000,
        solver="liblinear",
        C=0.5,
        random_state=random_state,
    )
    model.fit(X_train[selected], y_train)
    return model, selected


def _score_from_probability(probability: np.ndarray, config: PipelineConfig) -> np.ndarray:
    factor = config.explainable_pdo / np.log(2)
    bad_odds = np.clip(probability, 1e-6, 1 - 1e-6) / np.clip(1 - probability, 1e-6, 1)
    base_bad_odds = 1.0 / max(config.explainable_base_odds, 1e-6)
    offset = config.explainable_base_score + factor * np.log(base_bad_odds)
    return offset - factor * np.log(bad_odds)


def _points_mapping(
    transformer: WOETransformer,
    selected_features: list[str],
    coefficients: pd.Series,
    config: PipelineConfig,
) -> pd.DataFrame:
    factor = config.explainable_pdo / np.log(2)
    rules = transformer.export_rules()
    rows = []
    for feature in selected_features:
        coef = coefficients[feature]
        subset = rules[rules["feature"] == feature].copy()
        subset["coefficient"] = coef
        subset["points"] = -factor * coef * subset["woe"]
        rows.append(subset)
    return pd.concat(rows, axis=0, ignore_index=True)


def _reason_codes(
    transformer: WOETransformer,
    selected_features: list[str],
    coefficients: pd.Series,
    frame: pd.DataFrame,
) -> pd.DataFrame:
    transformed = transformer.transform(frame, selected_features)
    contributions = transformed.mul(coefficients[selected_features], axis=1)
    reasons = pd.DataFrame({"SK_ID_CURR": frame["SK_ID_CURR"].values})
    values = contributions.to_numpy(dtype=float)
    feature_names = contributions.columns.to_numpy()
    top_k = min(3, values.shape[1])
    if top_k == 0:
        return reasons
    top_indices = np.argsort(-values, axis=1)[:, :top_k]
    top_values = np.take_along_axis(values, top_indices, axis=1)
    for rank in range(top_k):
        reasons[f"reason_code_{rank + 1}"] = feature_names[top_indices[:, rank]]
        reasons[f"reason_contribution_{rank + 1}"] = top_values[:, rank]
    return reasons


def run_explainable(
    config: PipelineConfig,
    force: bool = False,
    analysis_artifacts: object | None = None,
) -> dict[str, object]:
    analysis_artifacts = analysis_artifacts or run_analysis(config, force=force)
    bundle = analysis_artifacts.master_bundle
    folds = analysis_artifacts.folds
    frame = explainable_matrix(bundle).merge(folds[["SK_ID_CURR", "fold"]], on="SK_ID_CURR", how="left")

    train = frame[frame["TARGET"].notna()].copy()
    train["TARGET"] = train["TARGET"].astype(int)
    train = stratified_sample(
        train,
        target_col="TARGET",
        max_rows=config.scorecard_sample_rows,
        random_state=config.random_state,
    )
    test = frame[frame["TARGET"].isna()].copy()
    candidate_features = [col for col in bundle.explainable_features if col in train.columns]

    oof = pd.DataFrame({"SK_ID_CURR": train["SK_ID_CURR"], "TARGET": train["TARGET"]})
    fold_metrics = []

    for fold in range(config.n_folds):
        train_mask = train["fold"] != fold
        valid_mask = train["fold"] == fold
        X_train = train.loc[train_mask, candidate_features]
        y_train = train.loc[train_mask, "TARGET"]
        X_valid = train.loc[valid_mask, candidate_features]
        y_valid = train.loc[valid_mask, "TARGET"]

        transformer = WOETransformer(min_bin_size=config.explainable_min_bin_size)
        transformer.fit(X_train, y_train)
        selected = transformer.top_features(config.explainable_top_features)
        transformed_train = transformer.transform(X_train, selected)
        selected = _prune_high_vif(transformed_train[selected])
        model, selected = _fit_sign_constrained_logistic(transformed_train[selected], y_train, config.random_state)
        transformed_valid = transformer.transform(X_valid, selected)
        pred_valid = model.predict_proba(transformed_valid[selected])[:, 1]
        pred_train = model.predict_proba(transformed_train[selected])[:, 1]
        oof.loc[valid_mask, "scorecard_pred"] = pred_valid
        metrics = binary_classification_metrics(y_valid.to_numpy(), pred_valid)
        metrics["fold"] = fold
        metrics["psi"] = psi(pred_train, pred_valid)
        metrics["selected_features"] = selected
        fold_metrics.append(metrics)

    overall = binary_classification_metrics(oof["TARGET"].to_numpy(), oof["scorecard_pred"].to_numpy())
    overall["folds"] = fold_metrics
    save_frame(oof, config.predictions_dir / "scorecard_oof.csv")

    final_transformer = WOETransformer(min_bin_size=config.explainable_min_bin_size)
    final_transformer.fit(train[candidate_features], train["TARGET"])
    final_selected = final_transformer.top_features(config.explainable_top_features)
    final_train_woe = final_transformer.transform(train, final_selected)
    final_selected = _prune_high_vif(final_train_woe[final_selected])
    final_model, final_selected = _fit_sign_constrained_logistic(
        final_train_woe[final_selected],
        train["TARGET"],
        config.random_state,
    )

    coefficients = pd.Series(final_model.coef_[0], index=final_selected)
    intercept = float(final_model.intercept_[0])
    final_train_pred = final_model.predict_proba(final_train_woe[final_selected])[:, 1]
    final_test_woe = final_transformer.transform(test, final_selected)
    final_test_pred = final_model.predict_proba(final_test_woe[final_selected])[:, 1]

    all_rows = pd.concat([train, test], axis=0, ignore_index=True)
    all_woe = final_transformer.transform(all_rows, final_selected)
    probabilities = final_model.predict_proba(all_woe[final_selected])[:, 1]
    scores = _score_from_probability(probabilities, config)
    scorecard_predictions = pd.DataFrame(
        {
            "SK_ID_CURR": all_rows["SK_ID_CURR"].values,
            "TARGET": all_rows["TARGET"].values,
            "dataset_split": all_rows["dataset_split"].values,
            "scorecard_probability": probabilities,
            "scorecard_score": scores,
        }
    )
    save_frame(scorecard_predictions, config.predictions_dir / "scorecard_predictions.csv")

    coefficients_frame = pd.DataFrame(
        {
            "feature": final_selected + ["INTERCEPT"],
            "coefficient": list(coefficients.values) + [intercept],
        }
    )
    save_frame(coefficients_frame, config.explainability_dir / "scorecard_coefficients.csv")

    points_mapping = _points_mapping(final_transformer, final_selected, coefficients, config)
    save_frame(points_mapping, config.explainability_dir / "scorecard_bins.csv")

    reasons = _reason_codes(final_transformer, final_selected, coefficients, all_rows)
    save_frame(reasons, config.explainability_dir / "reason_codes.csv")

    feature_diagnostics, bin_monitoring, monitoring_sample_rows = _scorecard_feature_diagnostics(
        final_transformer,
        final_selected,
        train,
        test,
        config,
    )
    save_frame(feature_diagnostics, config.explainability_dir / "scorecard_feature_diagnostics.csv")
    save_frame(bin_monitoring, config.explainability_dir / "scorecard_bin_monitoring.csv")

    final_metrics = binary_classification_metrics(train["TARGET"].to_numpy(), final_train_pred)
    final_metrics["selected_features"] = final_selected
    final_metrics["folds"] = fold_metrics
    final_metrics["score_range"] = {
        "min": float(scorecard_predictions["scorecard_score"].min()),
        "max": float(scorecard_predictions["scorecard_score"].max()),
    }
    final_metrics["train_probability_summary"] = {
        "mean": float(np.mean(final_train_pred)),
        "std": float(np.std(final_train_pred)),
    }
    final_metrics["monitoring_sample_rows"] = monitoring_sample_rows
    final_metrics["feature_diagnostics_top_iv"] = (
        feature_diagnostics.sort_values("iv", ascending=False).head(5).to_dict(orient="records")
        if not feature_diagnostics.empty
        else []
    )
    final_metrics["feature_diagnostics_top_psi"] = (
        feature_diagnostics.sort_values("psi_train_test", ascending=False).head(5).to_dict(orient="records")
        if not feature_diagnostics.empty
        else []
    )
    final_metrics["sample_rows"] = int(len(train))
    save_json(final_metrics, config.reports_dir / "scorecard_metrics.json")
    update_model_comparison(config, "explainable_scorecard", final_metrics)

    return {
        "oof_metrics": overall,
        "final_metrics": final_metrics,
        "test_rows": int(len(test)),
        "submission_ready_predictions": int(len(final_test_pred)),
    }

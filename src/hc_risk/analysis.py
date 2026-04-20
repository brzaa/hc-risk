from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import SGDClassifier
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .config import PipelineConfig, TABLE_GRAINS
from .features import FeatureBundle, build_folds, build_master_table
from .io import load_table, save_frame, save_json
from .metrics import binary_classification_metrics
from .reporting import update_model_comparison
from .sampling import stratified_sample


APPLICATION_CATEGORICALS = [
    "NAME_CONTRACT_TYPE",
    "CODE_GENDER",
    "FLAG_OWN_CAR",
    "FLAG_OWN_REALTY",
    "NAME_TYPE_SUITE",
    "NAME_INCOME_TYPE",
    "NAME_EDUCATION_TYPE",
    "NAME_FAMILY_STATUS",
    "NAME_HOUSING_TYPE",
    "OCCUPATION_TYPE",
    "WEEKDAY_APPR_PROCESS_START",
    "ORGANIZATION_TYPE",
]

SCORECARD_EXCLUSIONS = [
    "OCCUPATION_TYPE",
    "ORGANIZATION_TYPE",
    "WEEKDAY_APPR_PROCESS_START",
    "HOUR_APPR_PROCESS_START",
    "FLAG_DOCUMENT_2",
    "FLAG_DOCUMENT_4",
    "FLAG_DOCUMENT_7",
    "FLAG_DOCUMENT_10",
    "FLAG_DOCUMENT_12",
]


@dataclass(slots=True)
class AnalysisArtifacts:
    master_bundle: FeatureBundle
    folds: pd.DataFrame


def _table_audit(config: PipelineConfig) -> list[dict[str, object]]:
    payload: list[dict[str, object]] = []
    for table_name, grain in TABLE_GRAINS.items():
        df = load_table(config, table_name)
        missing_fraction = float(df.isna().mean().mean())
        grain_duplicates = int(df.duplicated(subset=grain).sum())
        payload.append(
            {
                "table": table_name,
                "rows": int(len(df)),
                "columns": int(df.shape[1]),
                "grain": grain,
                "grain_duplicate_rows": grain_duplicates,
                "average_missing_fraction": missing_fraction,
            }
        )
    return payload


def _join_coverage(bundle: FeatureBundle) -> list[dict[str, object]]:
    master = bundle.master
    train_count = int((master["dataset_split"] == "train").sum())
    test_count = int((master["dataset_split"] == "test").sum())
    coverage = []
    prefixes = {
        "bureau": "bureau_",
        "previous": "previous_",
        "pos": "pos_",
        "credit": "credit_",
        "install": "install_",
    }
    for table_name, prefix in prefixes.items():
        candidate_cols = [col for col in master.columns if col.startswith(prefix)]
        if not candidate_cols:
            continue
        indicator = master[candidate_cols].notna().any(axis=1)
        coverage.append(
            {
                "table": table_name,
                "train_join_coverage": float(indicator[master["dataset_split"] == "train"].mean()),
                "test_join_coverage": float(indicator[master["dataset_split"] == "test"].mean()),
                "train_rows": train_count,
                "test_rows": test_count,
            }
        )
    return coverage


def _target_segments(master: pd.DataFrame) -> dict[str, object]:
    train = master[master["TARGET"].notna()].copy()
    train["TARGET"] = train["TARGET"].astype(int)
    payload: dict[str, object] = {
        "row_count": int(len(train)),
        "default_rate": float(train["TARGET"].mean()),
    }
    for col in ["AMT_INCOME_TOTAL", "AMT_CREDIT", "EXT_SOURCE_MEAN"]:
        if col not in train.columns:
            continue
        segment = pd.qcut(train[col], q=5, duplicates="drop")
        grouped = (
            train.groupby(segment, observed=True)["TARGET"]
            .agg(["mean", "count"])
            .reset_index()
            .rename(columns={"mean": "default_rate"})
        )
        grouped[col] = grouped[col].astype(str)
        payload[f"{col}_quintiles"] = grouped.to_dict(orient="records")
    return payload


def _top_numeric_predictors(master: pd.DataFrame, top_n: int = 20) -> list[dict[str, object]]:
    train = master[master["TARGET"].notna()].copy()
    train["TARGET"] = train["TARGET"].astype(int)
    numeric_columns = [
        col
        for col in train.columns
        if pd.api.types.is_numeric_dtype(train[col])
        and col not in {"TARGET", "SK_ID_CURR"}
        and not col.startswith("FLAG_DOCUMENT_")
        and not col.startswith(("bureau_", "previous_", "pos_", "credit_", "install_"))
    ]
    rows = []
    y = train["TARGET"].to_numpy()
    for col in numeric_columns:
        series = train[col]
        if series.nunique(dropna=True) < 20:
            continue
        filled = series.fillna(series.median())
        auc = roc_auc_score(y, filled)
        rows.append({"feature": col, "univariate_auc": float(max(auc, 1 - auc))})
    rows.sort(key=lambda item: item["univariate_auc"], reverse=True)
    return rows[:top_n]


def _sentinel_report(master: pd.DataFrame) -> dict[str, object]:
    report: dict[str, object] = {
        "days_employed_anomalies": int(master["DAYS_EMPLOYED_ANOM"].sum()),
        "scorecard_exclusions": SCORECARD_EXCLUSIONS,
    }
    high_missing = (
        master.isna()
        .mean()
        .sort_values(ascending=False)
        .head(20)
        .rename("missing_fraction")
        .reset_index()
        .rename(columns={"index": "feature"})
    )
    report["top_missing_features"] = high_missing.to_dict(orient="records")
    low_variance = []
    for col in master.columns:
        if col in {"TARGET", "dataset_split", "SK_ID_CURR"}:
            continue
        if master[col].nunique(dropna=False) <= 1:
            low_variance.append(col)
    report["low_variance_features"] = low_variance
    return report


def _baseline_cv(bundle: FeatureBundle, folds: pd.DataFrame, config: PipelineConfig) -> tuple[pd.DataFrame, dict[str, object]]:
    master = bundle.master.merge(folds[["SK_ID_CURR", "fold"]], on="SK_ID_CURR", how="left")
    train = master[master["TARGET"].notna()].copy()
    train["TARGET"] = train["TARGET"].astype(int)
    train = stratified_sample(
        train,
        target_col="TARGET",
        max_rows=config.analysis_baseline_sample_rows,
        random_state=config.random_state,
    )

    numeric_cols = [
        col
        for col in train.columns
        if pd.api.types.is_numeric_dtype(train[col])
        and col not in {"TARGET", "SK_ID_CURR", "fold"}
        and not col.startswith(("bureau_", "previous_", "pos_", "credit_", "install_"))
    ]
    oof = pd.DataFrame({"SK_ID_CURR": train["SK_ID_CURR"], "TARGET": train["TARGET"]})
    fold_metrics = []
    for fold in range(config.n_folds):
        train_idx = train["fold"] != fold
        valid_idx = train["fold"] == fold
        model = Pipeline(
            steps=[
                ("imputer", SimpleImputer(strategy="median")),
                ("scaler", StandardScaler(with_mean=False)),
                (
                    "model",
                    SGDClassifier(
                        loss="log_loss",
                        alpha=1e-4,
                        max_iter=2000,
                        tol=1e-3,
                        random_state=config.random_state,
                    ),
                ),
            ]
        )
        model.fit(train.loc[train_idx, numeric_cols], train.loc[train_idx, "TARGET"])
        pred = model.predict_proba(train.loc[valid_idx, numeric_cols])[:, 1]
        oof.loc[valid_idx, "analysis_baseline_pred"] = pred
        metrics = binary_classification_metrics(train.loc[valid_idx, "TARGET"].to_numpy(), pred)
        metrics["fold"] = fold
        fold_metrics.append(metrics)

    overall = binary_classification_metrics(oof["TARGET"].to_numpy(), oof["analysis_baseline_pred"].to_numpy())
    overall["folds"] = fold_metrics
    overall["sample_rows"] = int(len(train))
    save_frame(oof, config.predictions_dir / "analysis_baseline_oof.csv")
    return oof, overall


def _adversarial_validation(bundle: FeatureBundle, config: PipelineConfig) -> dict[str, object]:
    master = bundle.master.copy()
    master["is_test"] = (master["dataset_split"] == "test").astype(int)
    feature_cols = [
        col
        for col in bundle.leaderboard_features
        if col in master.columns and master[col].dtype != "O"
    ]
    drift_sample_rows = 15000
    if config.analysis_baseline_sample_rows is not None:
        drift_sample_rows = min(drift_sample_rows, max(5000, config.analysis_baseline_sample_rows // 4))
    sample_train = master[master["is_test"] == 0].sample(
        n=min(drift_sample_rows, int((master["is_test"] == 0).sum())),
        random_state=config.random_state,
    )
    sample_test = master[master["is_test"] == 1].sample(
        n=min(drift_sample_rows, int((master["is_test"] == 1).sum())),
        random_state=config.random_state,
    )
    sample = pd.concat([sample_train, sample_test], axis=0, ignore_index=True)
    X = sample[feature_cols].fillna(sample[feature_cols].median())
    y = sample["is_test"].to_numpy()

    model = SGDClassifier(
        loss="log_loss",
        alpha=1e-4,
        max_iter=2000,
        tol=1e-3,
        random_state=config.random_state,
    )
    model.fit(X, y)
    auc = roc_auc_score(y, model.predict_proba(X)[:, 1])
    coef = pd.Series(model.coef_[0], index=feature_cols).abs().sort_values(ascending=False).head(20)
    return {
        "adversarial_auc": float(auc),
        "sample_rows_per_split": int(drift_sample_rows),
        "top_drift_features": coef.rename("absolute_coefficient").reset_index().rename(columns={"index": "feature"}).to_dict(orient="records"),
    }


def run_analysis(config: PipelineConfig, force: bool = False) -> AnalysisArtifacts:
    config.ensure_directories()
    print(f"[analysis] building master table (force={force})")
    bundle = build_master_table(config, force=force)
    print("[analysis] building folds")
    folds = build_folds(bundle.master, config, force=force)

    print("[analysis] writing audit reports")
    audit_payload = {
        "table_audit": _table_audit(config),
        "join_coverage": _join_coverage(bundle),
    }
    save_json(audit_payload, config.reports_dir / "analysis_audit.json")

    target_payload = {
        "target_summary": _target_segments(bundle.master),
        "top_numeric_predictors": _top_numeric_predictors(bundle.master),
    }
    save_json(target_payload, config.reports_dir / "target_analysis.json")

    sentinel_payload = _sentinel_report(bundle.master)
    save_json(sentinel_payload, config.reports_dir / "leakage_and_proxy_review.json")

    print("[analysis] running baseline CV")
    _, baseline_metrics = _baseline_cv(bundle, folds, config)
    save_json(baseline_metrics, config.reports_dir / "analysis_baseline_metrics.json")

    print("[analysis] running adversarial validation")
    drift_payload = _adversarial_validation(bundle, config)
    save_json(drift_payload, config.reports_dir / "train_test_drift.json")

    update_model_comparison(config, "analysis_baseline", baseline_metrics)
    print("[analysis] complete")
    return AnalysisArtifacts(master_bundle=bundle, folds=folds)

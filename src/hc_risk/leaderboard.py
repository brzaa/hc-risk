from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import ParameterSampler
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .analysis import run_analysis
from .config import PipelineConfig
from .features import build_folds, build_master_table, leaderboard_matrix
from .io import save_frame, save_json
from .metrics import binary_classification_metrics, rank_average
from .reporting import update_model_comparison
from .sampling import stratified_sample


@dataclass(slots=True)
class ModelSpec:
    name: str
    estimator: object
    param_grid: dict[str, list[object]]


def _try_optional(module_name: str) -> object | None:
    try:
        return import_module(module_name)
    except Exception:
        return None


def _available_model_specs(config: PipelineConfig) -> list[ModelSpec]:
    specs: list[ModelSpec] = []

    lightgbm = _try_optional("lightgbm")
    if lightgbm is not None:
        specs.append(
            ModelSpec(
                name="lightgbm_gbdt",
                estimator=lightgbm.LGBMClassifier(
                    objective="binary",
                    n_estimators=800,
                    learning_rate=0.03,
                    num_leaves=31,
                    min_child_samples=50,
                    reg_alpha=0.0,
                    reg_lambda=1.0,
                    subsample=0.8,
                    colsample_bytree=0.8,
                    verbosity=-1,
                    random_state=config.random_state,
                    n_jobs=-1,
                ),
                param_grid={
                    "n_estimators": [500, 800, 1200],
                    "num_leaves": [24, 31, 63],
                    "learning_rate": [0.02, 0.03, 0.05],
                    "min_child_samples": [20, 50, 100],
                    "reg_alpha": [0.0, 0.1, 1.0],
                    "reg_lambda": [0.0, 1.0, 5.0],
                    "subsample": [0.7, 0.8, 0.9],
                    "colsample_bytree": [0.7, 0.8, 0.9],
                },
            )
        )
    xgboost = _try_optional("xgboost")
    if xgboost is not None:
        specs.append(
            ModelSpec(
                name="xgboost",
                estimator=xgboost.XGBClassifier(
                    n_estimators=800,
                    learning_rate=0.03,
                    max_depth=4,
                    min_child_weight=5,
                    reg_alpha=0.0,
                    reg_lambda=1.0,
                    subsample=0.8,
                    colsample_bytree=0.8,
                    objective="binary:logistic",
                    eval_metric="auc",
                    tree_method="hist",
                    verbosity=0,
                    random_state=config.random_state,
                    n_jobs=-1,
                ),
                param_grid={
                    "n_estimators": [500, 800, 1200],
                    "max_depth": [3, 4, 6],
                    "learning_rate": [0.02, 0.03, 0.05],
                    "min_child_weight": [1, 5, 10],
                    "reg_alpha": [0.0, 0.1, 1.0],
                    "reg_lambda": [1.0, 5.0, 10.0],
                    "subsample": [0.7, 0.8, 0.9],
                    "colsample_bytree": [0.7, 0.8, 0.9],
                },
            )
        )

    catboost = _try_optional("catboost")
    if catboost is not None:
        specs.append(
            ModelSpec(
                name="catboost",
                estimator=catboost.CatBoostClassifier(
                    iterations=800,
                    depth=6,
                    learning_rate=0.03,
                    l2_leaf_reg=5,
                    loss_function="Logloss",
                    eval_metric="AUC",
                    verbose=False,
                    random_seed=config.random_state,
                ),
                param_grid={
                    "iterations": [500, 800, 1200],
                    "depth": [4, 6, 8],
                    "learning_rate": [0.02, 0.03, 0.05],
                    "l2_leaf_reg": [3, 5, 9],
                    "bagging_temperature": [0.0, 0.5, 1.0],
                },
            )
        )

    if specs:
        return specs

    sklearn_specs = [
        ModelSpec(
            name="extra_trees",
            estimator=ExtraTreesClassifier(
                n_estimators=300,
                max_depth=14,
                min_samples_leaf=20,
                max_features="sqrt",
                n_jobs=-1,
                random_state=config.random_state,
            ),
            param_grid={
                "max_depth": [12, 14, 18],
                "min_samples_leaf": [10, 20, 40],
                "max_features": ["sqrt", 0.5, 0.8],
            },
        ),
        ModelSpec(
            name="hist_gbdt",
            estimator=HistGradientBoostingClassifier(
                learning_rate=0.03,
                max_iter=400,
                max_leaf_nodes=31,
                min_samples_leaf=80,
                l2_regularization=1.0,
                random_state=config.random_state,
            ),
            param_grid={
                "learning_rate": [0.03, 0.05],
                "max_leaf_nodes": [31, 63],
                "min_samples_leaf": [40, 80, 120],
                "l2_regularization": [0.0, 1.0, 3.0],
            },
        ),
        ModelSpec(
            name="linear_logit",
            estimator=make_pipeline(
                StandardScaler(with_mean=False),
                LogisticRegression(
                    C=0.3,
                    max_iter=2000,
                    class_weight="balanced",
                    solver="lbfgs",
                    random_state=config.random_state,
                ),
            ),
            param_grid={
                "logisticregression__C": [0.1, 0.3, 1.0],
            },
        ),
    ]
    return sklearn_specs


def _tune_model(
    spec: ModelSpec,
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_valid: np.ndarray,
    y_valid: np.ndarray,
    config: PipelineConfig,
) -> tuple[dict[str, object], float]:
    if not spec.param_grid or config.leaderboard_tuning_trials <= 1:
        estimator = clone(spec.estimator)
        estimator.fit(X_train, y_train)
        pred = estimator.predict_proba(X_valid)[:, 1]
        return {}, float(roc_auc_score(y_valid, pred))

    rng = np.random.default_rng(config.random_state)
    if len(X_train) > 80000:
        tune_idx = rng.choice(len(X_train), size=80000, replace=False)
        X_train = X_train[tune_idx]
        y_train = y_train[tune_idx]
    if len(X_valid) > 40000:
        valid_idx = rng.choice(len(X_valid), size=40000, replace=False)
        X_valid = X_valid[valid_idx]
        y_valid = y_valid[valid_idx]

    best_params: dict[str, object] = {}
    best_score = -np.inf
    sampler = ParameterSampler(
        spec.param_grid,
        n_iter=min(config.leaderboard_tuning_trials, 8),
        random_state=config.random_state,
    )
    for params in sampler:
        estimator = clone(spec.estimator)
        estimator.set_params(**params)
        estimator.fit(X_train, y_train)
        pred = estimator.predict_proba(X_valid)[:, 1]
        score = roc_auc_score(y_valid, pred)
        if score > best_score:
            best_params = params
            best_score = score
    return best_params, float(best_score)


def _fit_predict_cv(
    spec: ModelSpec,
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
    feature_names: list[str],
    folds: pd.DataFrame,
    config: PipelineConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object], pd.DataFrame | None]:
    joined = train_df.merge(folds[["SK_ID_CURR", "fold"]], on="SK_ID_CURR", how="left")
    imputer = SimpleImputer(strategy="median")

    first_fold = 0
    train_mask = joined["fold"] != first_fold
    valid_mask = joined["fold"] == first_fold
    tune_X_train = imputer.fit_transform(joined.loc[train_mask, feature_names])
    tune_X_valid = imputer.transform(joined.loc[valid_mask, feature_names])
    tune_y_train = joined.loc[train_mask, "TARGET"].to_numpy()
    tune_y_valid = joined.loc[valid_mask, "TARGET"].to_numpy()
    best_params, holdout_auc = _tune_model(spec, tune_X_train, tune_y_train, tune_X_valid, tune_y_valid, config)

    oof = pd.DataFrame({"SK_ID_CURR": joined["SK_ID_CURR"], "TARGET": joined["TARGET"]})
    test_predictions = np.zeros(len(test_df), dtype=float)
    fold_metrics = []
    importances = []

    for fold in range(config.n_folds):
        train_mask = joined["fold"] != fold
        valid_mask = joined["fold"] == fold
        X_train = joined.loc[train_mask, feature_names]
        y_train = joined.loc[train_mask, "TARGET"].to_numpy()
        X_valid = joined.loc[valid_mask, feature_names]
        y_valid = joined.loc[valid_mask, "TARGET"].to_numpy()

        fold_imputer = SimpleImputer(strategy="median")
        X_train_imp = fold_imputer.fit_transform(X_train)
        X_valid_imp = fold_imputer.transform(X_valid)
        X_test_imp = fold_imputer.transform(test_df[feature_names])

        estimator = clone(spec.estimator)
        if best_params:
            estimator.set_params(**best_params)
        estimator.fit(X_train_imp, y_train)
        valid_pred = estimator.predict_proba(X_valid_imp)[:, 1]
        test_pred = estimator.predict_proba(X_test_imp)[:, 1]
        oof.loc[valid_mask, spec.name] = valid_pred
        test_predictions += test_pred / config.n_folds
        metrics = binary_classification_metrics(y_valid, valid_pred)
        metrics["fold"] = fold
        fold_metrics.append(metrics)

        if hasattr(estimator, "feature_importances_"):
            fold_importance = pd.DataFrame(
                {
                    "feature": feature_names,
                    "importance": estimator.feature_importances_,
                    "fold": fold,
                    "model": spec.name,
                }
            )
            importances.append(fold_importance)

    oof_metric = binary_classification_metrics(oof["TARGET"].to_numpy(), oof[spec.name].to_numpy())
    oof_metric["folds"] = fold_metrics
    oof_metric["tuned_params"] = best_params
    oof_metric["holdout_auc"] = holdout_auc

    test_pred_frame = pd.DataFrame(
        {
            "SK_ID_CURR": test_df["SK_ID_CURR"].values,
            f"{spec.name}_pred": test_predictions,
        }
    )
    importance_frame = pd.concat(importances, axis=0, ignore_index=True) if importances else None
    return oof, test_pred_frame, oof_metric, importance_frame


def _fit_stacker_cv(
    name: str,
    estimator: object,
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
    feature_names: list[str],
    folds: pd.DataFrame,
    config: PipelineConfig,
) -> tuple[pd.Series, np.ndarray, dict[str, object]]:
    joined = train_df.merge(folds[["SK_ID_CURR", "fold"]], on="SK_ID_CURR", how="left")
    oof_pred = pd.Series(np.nan, index=joined.index, name=name)
    test_pred = np.zeros(len(test_df), dtype=float)
    fold_metrics = []

    for fold in range(config.n_folds):
        train_mask = joined["fold"] != fold
        valid_mask = joined["fold"] == fold
        X_train = joined.loc[train_mask, feature_names]
        y_train = joined.loc[train_mask, "TARGET"].to_numpy()
        X_valid = joined.loc[valid_mask, feature_names]
        y_valid = joined.loc[valid_mask, "TARGET"].to_numpy()

        imputer = SimpleImputer(strategy="median")
        X_train_imp = imputer.fit_transform(X_train)
        X_valid_imp = imputer.transform(X_valid)
        X_test_imp = imputer.transform(test_df[feature_names])

        fitted = clone(estimator)
        fitted.fit(X_train_imp, y_train)
        valid_pred = fitted.predict_proba(X_valid_imp)[:, 1]
        test_pred += fitted.predict_proba(X_test_imp)[:, 1] / config.n_folds
        oof_pred.loc[valid_mask] = valid_pred

        metrics = binary_classification_metrics(y_valid, valid_pred)
        metrics["fold"] = fold
        fold_metrics.append(metrics)

    overall = binary_classification_metrics(joined["TARGET"].to_numpy(), oof_pred.to_numpy())
    overall["folds"] = fold_metrics
    return oof_pred, test_pred, overall


def run_leaderboard(
    config: PipelineConfig,
    force: bool = False,
    analysis_artifacts: object | None = None,
) -> dict[str, object]:
    print(f"[leaderboard] starting (force={force})")
    analysis_artifacts = analysis_artifacts or run_analysis(config, force=force)
    bundle = analysis_artifacts.master_bundle
    print("[leaderboard] building folds")
    folds = build_folds(bundle.master, config, force=force)

    print("[leaderboard] building encoded matrix")
    matrix, feature_names = leaderboard_matrix(bundle, config=config, force=force)
    print(f"[leaderboard] matrix ready with {len(feature_names)} features")
    train_df = matrix[matrix["TARGET"].notna()].copy()
    train_df["TARGET"] = train_df["TARGET"].astype(int)
    train_df = stratified_sample(
        train_df,
        target_col="TARGET",
        max_rows=config.leaderboard_sample_rows,
        random_state=config.random_state,
    )
    test_df = matrix[matrix["TARGET"].isna()].copy()

    model_specs = _available_model_specs(config)
    oof_payload = train_df[["SK_ID_CURR", "TARGET"]].copy()
    test_payload = test_df[["SK_ID_CURR"]].copy()
    model_metrics: dict[str, object] = {}
    importance_frames = []

    for spec in model_specs:
        print(f"[leaderboard] fitting base model: {spec.name}")
        oof_predictions, test_predictions, metrics, importance = _fit_predict_cv(
            spec,
            train_df,
            test_df,
            feature_names,
            folds,
            config,
        )
        oof_payload = oof_payload.merge(oof_predictions[["SK_ID_CURR", spec.name]], on="SK_ID_CURR", how="left")
        test_payload = test_payload.merge(
            test_predictions[["SK_ID_CURR", f"{spec.name}_pred"]],
            on="SK_ID_CURR",
            how="left",
        )
        model_metrics[spec.name] = metrics
        if importance is not None:
            importance_frames.append(importance)

    oof_pred_arrays = [oof_payload[spec.name].to_numpy() for spec in model_specs]
    test_pred_arrays = [test_payload[f"{spec.name}_pred"].to_numpy() for spec in model_specs]
    oof_payload["base_rank_blend"] = rank_average(oof_pred_arrays)
    test_payload["base_rank_blend"] = rank_average(test_pred_arrays)

    base_blend_metrics = binary_classification_metrics(
        oof_payload["TARGET"].to_numpy(),
        oof_payload["base_rank_blend"].to_numpy(),
    )
    base_blend_metrics["base_models"] = list(model_metrics)

    raw_meta_candidates = [
        "AMT_INCOME_TOTAL",
        "AMT_CREDIT",
        "AMT_ANNUITY",
        "EXT_SOURCE_2",
        "EXT_SOURCE_3",
        "EXT_SOURCE_MEAN",
        "PAYMENT_RATE",
        "CREDIT_ANNUITY_RATIO",
        "bureau_total_debt_ratio",
        "install_window_365d_PAYMENT_PCT_mean",
    ]
    raw_meta_features = [col for col in raw_meta_candidates if col in bundle.master.columns]
    train_master = bundle.master[bundle.master["dataset_split"] == "train"][
        ["SK_ID_CURR", *raw_meta_features]
    ].copy()
    test_master = bundle.master[bundle.master["dataset_split"] == "test"][
        ["SK_ID_CURR", *raw_meta_features]
    ].copy()
    train_meta = oof_payload.merge(train_master, on="SK_ID_CURR", how="left")
    test_meta_base = test_payload.copy()
    for spec in model_specs:
        test_meta_base[spec.name] = test_meta_base[f"{spec.name}_pred"]
    test_meta = test_meta_base.merge(test_master, on="SK_ID_CURR", how="left")
    meta_feature_names = [spec.name for spec in model_specs] + ["base_rank_blend", *raw_meta_features]

    stacker_specs = {
        "stack_logit": make_pipeline(
            StandardScaler(with_mean=False),
            LogisticRegression(
                C=0.5,
                max_iter=2000,
                class_weight="balanced",
                solver="lbfgs",
                random_state=config.random_state,
            ),
        ),
    }
    stacker_metrics: dict[str, object] = {}
    final_oof_components = [oof_payload["base_rank_blend"].to_numpy()]
    final_test_components = [test_payload["base_rank_blend"].to_numpy()]
    for stacker_name, estimator in stacker_specs.items():
        print(f"[leaderboard] fitting stacker: {stacker_name}")
        stack_oof, stack_test, metrics = _fit_stacker_cv(
            stacker_name,
            estimator,
            train_meta,
            test_meta,
            meta_feature_names,
            folds,
            config,
        )
        oof_payload[stacker_name] = stack_oof.to_numpy()
        test_payload[stacker_name] = stack_test
        stacker_metrics[stacker_name] = metrics
        final_oof_components.append(stack_oof.to_numpy())
        final_test_components.append(stack_test)

    oof_payload["leaderboard_blend"] = np.mean(np.vstack(final_oof_components), axis=0)
    test_payload["leaderboard_blend"] = np.mean(np.vstack(final_test_components), axis=0)

    blend_metrics = binary_classification_metrics(
        oof_payload["TARGET"].to_numpy(),
        oof_payload["leaderboard_blend"].to_numpy(),
    )
    blend_metrics["base_models"] = list(model_metrics)
    blend_metrics["stackers"] = list(stacker_metrics)
    save_frame(oof_payload, config.predictions_dir / "leaderboard_oof.csv")
    save_frame(test_payload, config.predictions_dir / "leaderboard_test_predictions.csv")

    if importance_frames:
        feature_importance = (
            pd.concat(importance_frames, axis=0, ignore_index=True)
            .groupby(["model", "feature"], as_index=False)["importance"]
            .mean()
            .sort_values(["model", "importance"], ascending=[True, False])
        )
        save_frame(feature_importance, config.reports_dir / "leaderboard_feature_importance.csv")

    submission = pd.DataFrame(
        {
            "SK_ID_CURR": test_payload["SK_ID_CURR"].values,
            "TARGET": test_payload["leaderboard_blend"].values,
        }
    )
    save_frame(submission, config.submission_path)

    leaderboard_metrics = {
        "blend": blend_metrics,
        "base_blend": base_blend_metrics,
        "models": model_metrics,
        "stackers": stacker_metrics,
        "feature_count": len(feature_names),
        "model_names": [spec.name for spec in model_specs],
        "meta_feature_names": meta_feature_names,
        "sample_rows": int(len(train_df)),
    }
    save_json(leaderboard_metrics, config.reports_dir / "leaderboard_metrics.json")
    update_model_comparison(config, "leaderboard_ensemble", leaderboard_metrics)
    print("[leaderboard] complete")
    return leaderboard_metrics

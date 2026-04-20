from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd
from sklearn.model_selection import StratifiedKFold

from .config import EXPLAINABLE_CATEGORICALS, PipelineConfig
from .io import load_table, load_frame, save_frame


APPLICATION_NUMERIC_DERIVED = [
    "PAYMENT_RATE",
    "ANNUITY_INCOME_PCT",
    "CREDIT_INCOME_RATIO",
    "INCOME_CREDIT_RATIO",
    "INCOME_PER_PERSON",
    "EMPLOYED_BIRTH_RATIO",
    "CAR_TO_BIRTH_RATIO",
    "PHONE_TO_BIRTH_RATIO",
    "CREDIT_ANNUITY_RATIO",
    "CREDIT_GOODS_RATIO",
    "DOWN_PAYMENT",
    "DOWN_PAYMENT_RATIO",
    "EXT_SOURCE_MEAN",
    "EXT_SOURCE_STD",
    "EXT_SOURCE_MIN",
    "EXT_SOURCE_MAX",
    "EXT_SOURCE_COUNT",
    "CREDIT_EXT_SOURCE_3_RATIO",
    "ANNUITY_EXT_SOURCE_3_RATIO",
    "GOODS_EXT_SOURCE_3_RATIO",
    "INCOME_EXT_SOURCE_3_RATIO",
    "AGE_YEARS",
    "AGE_INT",
    "DOCUMENT_COUNT",
]


EXPLAINABLE_NUMERIC_FEATURES = [
    "AMT_INCOME_TOTAL",
    "AMT_CREDIT",
    "AMT_ANNUITY",
    "AMT_GOODS_PRICE",
    "REGION_POPULATION_RELATIVE",
    "DAYS_BIRTH",
    "DAYS_EMPLOYED",
    "DAYS_REGISTRATION",
    "DAYS_ID_PUBLISH",
    "EXT_SOURCE_1",
    "EXT_SOURCE_2",
    "EXT_SOURCE_3",
    "PAYMENT_RATE",
    "ANNUITY_INCOME_PCT",
    "CREDIT_INCOME_RATIO",
    "INCOME_CREDIT_RATIO",
    "INCOME_PER_PERSON",
    "EMPLOYED_BIRTH_RATIO",
    "CREDIT_ANNUITY_RATIO",
    "CREDIT_GOODS_RATIO",
    "DOWN_PAYMENT_RATIO",
    "EXT_SOURCE_MEAN",
    "CREDIT_EXT_SOURCE_3_RATIO",
    "bureau_AMT_CREDIT_SUM_sum",
    "bureau_AMT_CREDIT_SUM_DEBT_mean",
    "bureau_AMT_CREDIT_SUM_OVERDUE_sum",
    "bureau_total_debt_ratio",
    "bureau_CREDIT_DAY_OVERDUE_max",
    "bureau_DAYS_CREDIT_max",
    "bureau_balance_STATUS_1_mean",
    "bureau_balance_STATUS_2_mean",
    "bureau_balance_STATUS_5_mean",
    "previous_AMT_APPLICATION_mean",
    "previous_APP_CREDIT_PCT_mean",
    "previous_approved_APP_CREDIT_PCT_mean",
    "previous_refused_count",
    "pos_SK_DPD_max",
    "pos_late_payment_rate",
    "credit_UTILIZATION_mean",
    "credit_SK_DPD_max",
    "install_PAYMENT_PCT_mean",
    "install_DAYS_PAST_DUE_max",
    "install_late_payment_rate",
]


APPLICATION_CATEGORICAL_COLUMNS = [
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


def safe_divide(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    denominator = denominator.replace({0: np.nan})
    return numerator / denominator


def flatten_columns(frame: pd.DataFrame, prefix: str) -> pd.DataFrame:
    frame.columns = [
        prefix + "_" + "_".join(str(part) for part in col if str(part))
        if isinstance(col, tuple)
        else prefix + "_" + str(col)
        for col in frame.columns
    ]
    return frame


def reduce_memory(df: pd.DataFrame) -> pd.DataFrame:
    for column in df.columns:
        if pd.api.types.is_float_dtype(df[column]):
            df[column] = pd.to_numeric(df[column], downcast="float")
        elif pd.api.types.is_integer_dtype(df[column]):
            df[column] = pd.to_numeric(df[column], downcast="integer")
    return df


def _merge_feature_frames(
    base: pd.DataFrame,
    frames: Iterable[pd.DataFrame],
    group_key: str = "SK_ID_CURR",
) -> pd.DataFrame:
    merged = base
    for frame in frames:
        if frame.empty:
            continue
        merged = merged.merge(frame, on=group_key, how="left")
    return merged


def _top_k_aggregate(
    df: pd.DataFrame,
    group_key: str,
    order_col: str,
    numeric_aggs: dict[str, list[str]],
    prefix: str,
    windows: Iterable[int],
) -> list[pd.DataFrame]:
    ordered = df.sort_values([group_key, order_col], ascending=[True, False]).copy()
    ordered["_rank"] = ordered.groupby(group_key).cumcount() + 1
    frames = []
    for window in windows:
        window_df = ordered[ordered["_rank"] <= window].drop(columns="_rank")
        if window_df.empty:
            continue
        frames.append(_aggregate_numeric(window_df, group_key, numeric_aggs, f"{prefix}_last{window}"))
    return frames


def _threshold_aggregate(
    df: pd.DataFrame,
    group_key: str,
    numeric_aggs: dict[str, list[str]],
    prefix: str,
    windows: Iterable[int],
    filter_col: str,
) -> list[pd.DataFrame]:
    frames = []
    for window in windows:
        window_df = df[df[filter_col] >= -window]
        if window_df.empty:
            continue
        frames.append(_aggregate_numeric(window_df, group_key, numeric_aggs, f"{prefix}_{window}d"))
    return frames


def _latest_record_features(
    df: pd.DataFrame,
    group_key: str,
    sort_col: str,
    columns: Iterable[str],
    prefix: str,
) -> pd.DataFrame:
    latest = df.sort_values([group_key, sort_col], ascending=[True, False]).groupby(group_key).head(1)
    keep = [group_key, *[col for col in columns if col in latest.columns]]
    latest = latest[keep].copy()
    latest = latest.rename(columns={col: f"{prefix}_{col}" for col in keep if col != group_key})
    return reduce_memory(latest.reset_index(drop=True))


def _lag_numeric_features(
    df: pd.DataFrame,
    group_key: str,
    sort_col: str,
    columns: Iterable[str],
    prefix: str,
    max_lag: int,
) -> pd.DataFrame:
    ordered = df.sort_values([group_key, sort_col], ascending=[True, False]).copy()
    ordered["_lag"] = ordered.groupby(group_key).cumcount() + 1
    ordered = ordered[ordered["_lag"] <= max_lag]
    frames = []
    for col in columns:
        if col not in ordered.columns:
            continue
        pivot = ordered.pivot(index=group_key, columns="_lag", values=col)
        pivot.columns = [f"{prefix}_{col}_lag{int(lag)}" for lag in pivot.columns]
        frames.append(pivot)
    if not frames:
        return pd.DataFrame({group_key: ordered[group_key].drop_duplicates()})
    return reduce_memory(pd.concat(frames, axis=1).reset_index())


def _weighted_average(
    df: pd.DataFrame,
    group_key: str,
    value_col: str,
    weight_col: str,
    prefix: str,
) -> pd.DataFrame:
    valid = df[[group_key, value_col, weight_col]].dropna()
    if valid.empty:
        return pd.DataFrame(columns=[group_key, f"{prefix}_{value_col}_weighted_mean"])
    valid = valid.assign(_weighted_value=valid[value_col] * valid[weight_col])
    grouped = valid.groupby(group_key).agg({"_weighted_value": "sum", weight_col: "sum"}).reset_index()
    grouped[f"{prefix}_{value_col}_weighted_mean"] = safe_divide(grouped["_weighted_value"], grouped[weight_col])
    grouped = grouped[[group_key, f"{prefix}_{value_col}_weighted_mean"]]
    return reduce_memory(grouped)


def application_frame(config: PipelineConfig) -> pd.DataFrame:
    train, test = load_table(config, "application_train"), load_table(config, "application_test")
    test = test.assign(TARGET=np.nan)
    train = train.assign(dataset_split="train")
    test = test.assign(dataset_split="test")
    app = pd.concat([train, test], axis=0, ignore_index=True, sort=False)

    days_employed_anom = (app["DAYS_EMPLOYED"] == 365243).astype("int8")
    app.loc[app["DAYS_EMPLOYED"] == 365243, "DAYS_EMPLOYED"] = np.nan

    for col in ["DAYS_LAST_PHONE_CHANGE", "DAYS_FIRST_DRAWING", "DAYS_FIRST_DUE"]:
        if col in app.columns:
            app.loc[app[col] == 365243, col] = np.nan

    ext_source = app[["EXT_SOURCE_1", "EXT_SOURCE_2", "EXT_SOURCE_3"]]
    document_cols = [col for col in app.columns if col.startswith("FLAG_DOCUMENT_")]
    app = app.assign(
        DAYS_EMPLOYED_ANOM=days_employed_anom,
        PAYMENT_RATE=safe_divide(app["AMT_ANNUITY"], app["AMT_CREDIT"]),
        ANNUITY_INCOME_PCT=safe_divide(app["AMT_ANNUITY"], app["AMT_INCOME_TOTAL"]),
        CREDIT_INCOME_RATIO=safe_divide(app["AMT_CREDIT"], app["AMT_INCOME_TOTAL"]),
        INCOME_CREDIT_RATIO=safe_divide(app["AMT_INCOME_TOTAL"], app["AMT_CREDIT"]),
        INCOME_PER_PERSON=safe_divide(app["AMT_INCOME_TOTAL"], app["CNT_FAM_MEMBERS"]),
        EMPLOYED_BIRTH_RATIO=safe_divide(app["DAYS_EMPLOYED"], app["DAYS_BIRTH"]),
        CAR_TO_BIRTH_RATIO=safe_divide(app["OWN_CAR_AGE"], -app["DAYS_BIRTH"]),
        PHONE_TO_BIRTH_RATIO=safe_divide(app["DAYS_LAST_PHONE_CHANGE"], -app["DAYS_BIRTH"]),
        CREDIT_ANNUITY_RATIO=safe_divide(app["AMT_CREDIT"], app["AMT_ANNUITY"]),
        CREDIT_GOODS_RATIO=safe_divide(app["AMT_CREDIT"], app["AMT_GOODS_PRICE"]),
        DOWN_PAYMENT=app["AMT_GOODS_PRICE"] - app["AMT_CREDIT"],
        DOWN_PAYMENT_RATIO=safe_divide(
            app["AMT_GOODS_PRICE"] - app["AMT_CREDIT"],
            app["AMT_GOODS_PRICE"],
        ),
        EXT_SOURCE_MEAN=ext_source.mean(axis=1),
        EXT_SOURCE_STD=ext_source.std(axis=1),
        EXT_SOURCE_MIN=ext_source.min(axis=1),
        EXT_SOURCE_MAX=ext_source.max(axis=1),
        EXT_SOURCE_COUNT=ext_source.notna().sum(axis=1),
        CREDIT_EXT_SOURCE_3_RATIO=safe_divide(app["AMT_CREDIT"], app["EXT_SOURCE_3"]),
        ANNUITY_EXT_SOURCE_3_RATIO=safe_divide(app["AMT_ANNUITY"], app["EXT_SOURCE_3"]),
        GOODS_EXT_SOURCE_3_RATIO=safe_divide(app["AMT_GOODS_PRICE"], app["EXT_SOURCE_3"]),
        INCOME_EXT_SOURCE_3_RATIO=safe_divide(app["AMT_INCOME_TOTAL"], app["EXT_SOURCE_3"]),
        AGE_YEARS=-app["DAYS_BIRTH"] / 365.0,
        AGE_INT=(-app["DAYS_BIRTH"] // 365).astype("float32"),
        DOCUMENT_COUNT=app[document_cols].sum(axis=1),
    )
    return reduce_memory(app)


def _aggregate_numeric(
    df: pd.DataFrame,
    group_key: str,
    numeric_aggs: dict[str, list[str]],
    prefix: str,
) -> pd.DataFrame:
    grouped = df.groupby(group_key).agg(numeric_aggs)
    grouped = flatten_columns(grouped, prefix)
    grouped = grouped.reset_index()
    return reduce_memory(grouped)


def _aggregate_dummies(
    df: pd.DataFrame,
    group_key: str,
    categorical_cols: Iterable[str],
    prefix: str,
) -> pd.DataFrame:
    categorical_cols = [col for col in categorical_cols if col in df.columns]
    if not categorical_cols:
        return df[[group_key]].drop_duplicates()
    dummies = pd.get_dummies(df[categorical_cols], dummy_na=True)
    dummies[group_key] = df[group_key].values
    grouped = dummies.groupby(group_key).mean().reset_index()
    grouped.columns = [
        group_key if col == group_key else f"{prefix}_{col}"
        for col in grouped.columns
    ]
    return reduce_memory(grouped)


def bureau_balance_aggregate(config: PipelineConfig, force: bool = False) -> pd.DataFrame:
    cache_path = config.features_dir / "bureau_balance_agg.pkl"
    if cache_path.exists() and not force:
        return load_frame(cache_path)

    df = load_table(config, "bureau_balance", usecols=["SK_ID_BUREAU", "MONTHS_BALANCE", "STATUS"])
    status_dummies = pd.get_dummies(df["STATUS"], prefix="STATUS", dummy_na=True)
    status_dummies["SK_ID_BUREAU"] = df["SK_ID_BUREAU"]
    status_agg = status_dummies.groupby("SK_ID_BUREAU").mean()
    month_agg = df.groupby("SK_ID_BUREAU")["MONTHS_BALANCE"].agg(["min", "max", "size"])
    agg = pd.concat([month_agg, status_agg], axis=1).reset_index()
    agg.columns = [
        "SK_ID_BUREAU",
        "bureau_balance_MONTHS_BALANCE_min",
        "bureau_balance_MONTHS_BALANCE_max",
        "bureau_balance_MONTHS_BALANCE_size",
        *[f"bureau_balance_{col}" for col in agg.columns[4:]],
    ]
    agg = reduce_memory(agg)
    save_frame(agg, cache_path)
    return agg


def bureau_aggregate(config: PipelineConfig, force: bool = False) -> pd.DataFrame:
    cache_path = config.features_dir / "bureau_agg.pkl"
    if cache_path.exists() and not force:
        return load_frame(cache_path)

    bureau = load_table(
        config,
        "bureau",
        usecols=[
            "SK_ID_CURR",
            "SK_ID_BUREAU",
            "CREDIT_ACTIVE",
            "CREDIT_CURRENCY",
            "CREDIT_TYPE",
            "DAYS_CREDIT",
            "CREDIT_DAY_OVERDUE",
            "DAYS_CREDIT_ENDDATE",
            "DAYS_ENDDATE_FACT",
            "DAYS_CREDIT_UPDATE",
            "AMT_CREDIT_MAX_OVERDUE",
            "CNT_CREDIT_PROLONG",
            "AMT_CREDIT_SUM",
            "AMT_CREDIT_SUM_DEBT",
            "AMT_CREDIT_SUM_LIMIT",
            "AMT_CREDIT_SUM_OVERDUE",
            "AMT_ANNUITY",
        ],
    )
    bb = bureau_balance_aggregate(config, force=force)
    bureau = bureau.merge(bb, on="SK_ID_BUREAU", how="left")
    bureau["DEBT_RATIO"] = safe_divide(bureau["AMT_CREDIT_SUM_DEBT"], bureau["AMT_CREDIT_SUM"])
    bureau["OVERDUE_RATIO"] = safe_divide(bureau["AMT_CREDIT_SUM_OVERDUE"], bureau["AMT_CREDIT_SUM"])

    numeric_aggs = {
        "DAYS_CREDIT": ["min", "max", "mean"],
        "CREDIT_DAY_OVERDUE": ["max", "mean", "sum"],
        "DAYS_CREDIT_ENDDATE": ["min", "max", "mean"],
        "DAYS_ENDDATE_FACT": ["min", "max", "mean"],
        "DAYS_CREDIT_UPDATE": ["min", "max", "mean"],
        "AMT_CREDIT_MAX_OVERDUE": ["max", "mean"],
        "CNT_CREDIT_PROLONG": ["sum", "mean"],
        "AMT_CREDIT_SUM": ["sum", "mean", "max"],
        "AMT_CREDIT_SUM_DEBT": ["sum", "mean", "max"],
        "AMT_CREDIT_SUM_LIMIT": ["sum", "mean"],
        "AMT_CREDIT_SUM_OVERDUE": ["sum", "mean", "max"],
        "AMT_ANNUITY": ["mean", "max"],
        "DEBT_RATIO": ["mean", "max"],
        "OVERDUE_RATIO": ["mean", "max"],
    }
    for col in [
        "bureau_balance_MONTHS_BALANCE_min",
        "bureau_balance_MONTHS_BALANCE_max",
        "bureau_balance_MONTHS_BALANCE_size",
    ]:
        numeric_aggs[col] = ["mean", "max"]
    for col in [c for c in bureau.columns if c.startswith("bureau_balance_STATUS_")]:
        numeric_aggs[col] = ["mean"]

    overall = _aggregate_numeric(bureau, "SK_ID_CURR", numeric_aggs, "bureau")
    dummies = _aggregate_dummies(
        bureau,
        "SK_ID_CURR",
        ["CREDIT_ACTIVE", "CREDIT_CURRENCY", "CREDIT_TYPE"],
        "bureau",
    )
    active = bureau[bureau["CREDIT_ACTIVE"] == "Active"]
    active_agg = _aggregate_numeric(
        active,
        "SK_ID_CURR",
        {
            "AMT_CREDIT_SUM": ["sum", "mean"],
            "AMT_CREDIT_SUM_DEBT": ["sum", "mean"],
            "CREDIT_DAY_OVERDUE": ["max", "sum"],
        },
        "bureau_active",
    )
    closed = bureau[bureau["CREDIT_ACTIVE"] == "Closed"]
    closed_agg = _aggregate_numeric(
        closed,
        "SK_ID_CURR",
        {"AMT_CREDIT_SUM": ["sum", "mean"], "DAYS_ENDDATE_FACT": ["max", "mean"]},
        "bureau_closed",
    )
    bureau_totals = (
        bureau.groupby("SK_ID_CURR", as_index=False)[
            ["AMT_CREDIT_SUM", "AMT_CREDIT_SUM_DEBT", "AMT_CREDIT_SUM_OVERDUE"]
        ]
        .sum()
        .assign(
            bureau_total_debt_ratio=lambda frame: safe_divide(
                frame["AMT_CREDIT_SUM_DEBT"],
                frame["AMT_CREDIT_SUM"],
            ),
            bureau_total_overdue_ratio=lambda frame: safe_divide(
                frame["AMT_CREDIT_SUM_OVERDUE"],
                frame["AMT_CREDIT_SUM"],
            ),
        )
        [["SK_ID_CURR", "bureau_total_debt_ratio", "bureau_total_overdue_ratio"]]
    )
    recent_frames = _top_k_aggregate(
        bureau,
        "SK_ID_CURR",
        "DAYS_CREDIT",
        {
            "DAYS_CREDIT": ["max", "mean"],
            "AMT_CREDIT_SUM": ["sum", "mean"],
            "AMT_CREDIT_SUM_DEBT": ["sum", "mean"],
            "CREDIT_DAY_OVERDUE": ["max", "sum"],
            "DEBT_RATIO": ["mean", "max"],
        },
        "bureau_recent",
        windows=[3, 5],
    )

    merged = _merge_feature_frames(
        overall,
        [dummies, active_agg, closed_agg, bureau_totals, *recent_frames],
    )
    save_frame(reduce_memory(merged), cache_path)
    return merged


def previous_application_aggregate(config: PipelineConfig, force: bool = False) -> pd.DataFrame:
    cache_path = config.features_dir / "previous_application_agg.pkl"
    if cache_path.exists() and not force:
        return load_frame(cache_path)

    previous = load_table(
        config,
        "previous_application",
        usecols=[
            "SK_ID_PREV",
            "SK_ID_CURR",
            "NAME_CONTRACT_TYPE",
            "AMT_ANNUITY",
            "AMT_APPLICATION",
            "AMT_CREDIT",
            "AMT_DOWN_PAYMENT",
            "AMT_GOODS_PRICE",
            "RATE_DOWN_PAYMENT",
            "DAYS_DECISION",
            "CNT_PAYMENT",
            "NAME_CONTRACT_STATUS",
            "NFLAG_INSURED_ON_APPROVAL",
            "PRODUCT_COMBINATION",
        ],
    )
    previous["APP_CREDIT_PCT"] = safe_divide(previous["AMT_APPLICATION"], previous["AMT_CREDIT"])
    previous["DOWN_PAYMENT_CREDIT_PCT"] = safe_divide(previous["AMT_DOWN_PAYMENT"], previous["AMT_CREDIT"])
    previous["CREDIT_GOODS_RATIO"] = safe_divide(previous["AMT_CREDIT"], previous["AMT_GOODS_PRICE"])
    previous["ANNUITY_CREDIT_RATIO"] = safe_divide(previous["AMT_ANNUITY"], previous["AMT_CREDIT"])
    previous["TOTAL_REPAYMENT_RATIO"] = safe_divide(
        previous["AMT_ANNUITY"] * previous["CNT_PAYMENT"],
        previous["AMT_CREDIT"],
    )
    previous["ESTIMATED_INTEREST_RATE"] = previous["TOTAL_REPAYMENT_RATIO"] - 1.0
    previous["is_approved_flag"] = (previous["NAME_CONTRACT_STATUS"] == "Approved").astype("int8")
    previous["is_refused_flag"] = (previous["NAME_CONTRACT_STATUS"] == "Refused").astype("int8")

    overall = _aggregate_numeric(
        previous,
        "SK_ID_CURR",
        {
            "AMT_ANNUITY": ["mean", "max"],
            "AMT_APPLICATION": ["mean", "max"],
            "AMT_CREDIT": ["mean", "max"],
            "AMT_DOWN_PAYMENT": ["mean", "max"],
            "AMT_GOODS_PRICE": ["mean", "max"],
            "RATE_DOWN_PAYMENT": ["mean", "max"],
            "DAYS_DECISION": ["min", "max", "mean"],
            "CNT_PAYMENT": ["mean", "max"],
            "APP_CREDIT_PCT": ["mean", "max"],
            "DOWN_PAYMENT_CREDIT_PCT": ["mean", "max"],
            "CREDIT_GOODS_RATIO": ["mean", "max"],
            "ANNUITY_CREDIT_RATIO": ["mean", "max"],
            "TOTAL_REPAYMENT_RATIO": ["mean", "max"],
            "ESTIMATED_INTEREST_RATE": ["mean", "max"],
            "is_approved_flag": ["mean", "sum"],
            "is_refused_flag": ["mean", "sum"],
        },
        "previous",
    )
    dummies = _aggregate_dummies(
        previous,
        "SK_ID_CURR",
        ["NAME_CONTRACT_TYPE", "NAME_CONTRACT_STATUS", "PRODUCT_COMBINATION"],
        "previous",
    )
    approved = previous[previous["NAME_CONTRACT_STATUS"] == "Approved"]
    approved_agg = _aggregate_numeric(
        approved,
        "SK_ID_CURR",
        {
            "APP_CREDIT_PCT": ["mean", "max"],
            "AMT_CREDIT": ["mean", "max"],
            "CNT_PAYMENT": ["mean", "max"],
            "TOTAL_REPAYMENT_RATIO": ["mean", "max"],
            "ESTIMATED_INTEREST_RATE": ["mean", "max"],
        },
        "previous_approved",
    )
    refused = previous[previous["NAME_CONTRACT_STATUS"] == "Refused"]
    refused_count = refused.groupby("SK_ID_CURR").size().rename("previous_refused_count").reset_index()
    recent_frames = _top_k_aggregate(
        previous,
        "SK_ID_CURR",
        "DAYS_DECISION",
        {
            "AMT_CREDIT": ["mean", "max"],
            "AMT_ANNUITY": ["mean", "max"],
            "CNT_PAYMENT": ["mean", "max"],
            "APP_CREDIT_PCT": ["mean", "max"],
            "ESTIMATED_INTEREST_RATE": ["mean", "max"],
        },
        "previous_recent",
        windows=[1, 3, 5],
    )
    latest_features = _latest_record_features(
        previous,
        "SK_ID_CURR",
        "DAYS_DECISION",
        [
            "PRODUCT_COMBINATION",
            "NAME_CONTRACT_STATUS",
            "NAME_CONTRACT_TYPE",
            "AMT_CREDIT",
            "AMT_ANNUITY",
            "CNT_PAYMENT",
            "APP_CREDIT_PCT",
            "ESTIMATED_INTEREST_RATE",
        ],
        "previous_last",
    )
    lag_features = _lag_numeric_features(
        previous,
        "SK_ID_CURR",
        "DAYS_DECISION",
        [
            "AMT_CREDIT",
            "AMT_ANNUITY",
            "CNT_PAYMENT",
            "APP_CREDIT_PCT",
            "ESTIMATED_INTEREST_RATE",
        ],
        "previous",
        max_lag=5,
    )
    merged = _merge_feature_frames(
        overall,
        [dummies, approved_agg, refused_count, latest_features, lag_features, *recent_frames],
    )
    merged["previous_refused_count"] = merged["previous_refused_count"].fillna(0)
    save_frame(reduce_memory(merged), cache_path)
    return merged


def pos_cash_aggregate(config: PipelineConfig, force: bool = False) -> pd.DataFrame:
    cache_path = config.features_dir / "pos_cash_agg.pkl"
    if cache_path.exists() and not force:
        return load_frame(cache_path)

    pos = load_table(
        config,
        "pos_cash_balance",
        usecols=[
            "SK_ID_PREV",
            "SK_ID_CURR",
            "MONTHS_BALANCE",
            "CNT_INSTALMENT",
            "CNT_INSTALMENT_FUTURE",
            "SK_DPD",
            "SK_DPD_DEF",
            "NAME_CONTRACT_STATUS",
        ],
    )
    pos["late_payment_flag"] = (pos["SK_DPD"] > 0).astype("int8")
    pos["future_installment_ratio"] = safe_divide(pos["CNT_INSTALMENT_FUTURE"], pos["CNT_INSTALMENT"])
    pos["recency_weight"] = 1.0 / (pos["MONTHS_BALANCE"].abs() + 1.0)
    overall = _aggregate_numeric(
        pos,
        "SK_ID_CURR",
        {
            "MONTHS_BALANCE": ["min", "max", "mean"],
            "CNT_INSTALMENT": ["mean", "max"],
            "CNT_INSTALMENT_FUTURE": ["mean", "max"],
            "SK_DPD": ["max", "mean"],
            "SK_DPD_DEF": ["max", "mean"],
            "late_payment_flag": ["mean", "sum"],
            "future_installment_ratio": ["mean", "max"],
        },
        "pos",
    )
    dummies = _aggregate_dummies(pos, "SK_ID_CURR", ["NAME_CONTRACT_STATUS"], "pos")
    recent_frames = _top_k_aggregate(
        pos,
        "SK_ID_CURR",
        "MONTHS_BALANCE",
        {
            "SK_DPD": ["max", "mean"],
            "SK_DPD_DEF": ["max", "mean"],
            "late_payment_flag": ["mean"],
            "future_installment_ratio": ["mean"],
        },
        "pos_recent",
        windows=[3, 5, 10],
    )
    month_frames = _threshold_aggregate(
        pos,
        "SK_ID_CURR",
        {
            "SK_DPD": ["max", "mean"],
            "SK_DPD_DEF": ["max", "mean"],
            "late_payment_flag": ["mean"],
            "future_installment_ratio": ["mean"],
        },
        "pos_window",
        windows=[3, 6, 12],
        filter_col="MONTHS_BALANCE",
    )
    weighted_dpd = _weighted_average(pos, "SK_ID_CURR", "SK_DPD", "recency_weight", "pos")
    merged = _merge_feature_frames(overall, [dummies, weighted_dpd, *recent_frames, *month_frames])
    merged = merged.rename(columns={"pos_late_payment_flag_mean": "pos_late_payment_rate"})
    save_frame(reduce_memory(merged), cache_path)
    return merged


def credit_card_aggregate(config: PipelineConfig, force: bool = False) -> pd.DataFrame:
    cache_path = config.features_dir / "credit_card_agg.pkl"
    if cache_path.exists() and not force:
        return load_frame(cache_path)

    credit = load_table(
        config,
        "credit_card_balance",
        usecols=[
            "SK_ID_PREV",
            "SK_ID_CURR",
            "MONTHS_BALANCE",
            "AMT_BALANCE",
            "AMT_CREDIT_LIMIT_ACTUAL",
            "AMT_DRAWINGS_CURRENT",
            "AMT_INST_MIN_REGULARITY",
            "AMT_PAYMENT_TOTAL_CURRENT",
            "SK_DPD",
            "SK_DPD_DEF",
            "CNT_DRAWINGS_CURRENT",
        ],
    )
    credit["UTILIZATION"] = safe_divide(credit["AMT_BALANCE"], credit["AMT_CREDIT_LIMIT_ACTUAL"])
    credit["PAYMENT_RATIO"] = safe_divide(
        credit["AMT_PAYMENT_TOTAL_CURRENT"],
        credit["AMT_INST_MIN_REGULARITY"],
    )
    credit["DRAWING_LIMIT_RATIO"] = safe_divide(
        credit["AMT_DRAWINGS_CURRENT"],
        credit["AMT_CREDIT_LIMIT_ACTUAL"],
    )
    credit["recency_weight"] = 1.0 / (credit["MONTHS_BALANCE"].abs() + 1.0)
    agg = _aggregate_numeric(
        credit,
        "SK_ID_CURR",
        {
            "MONTHS_BALANCE": ["min", "max", "mean"],
            "AMT_BALANCE": ["mean", "max"],
            "AMT_CREDIT_LIMIT_ACTUAL": ["mean", "max"],
            "AMT_DRAWINGS_CURRENT": ["mean", "max", "sum"],
            "AMT_PAYMENT_TOTAL_CURRENT": ["mean", "max", "sum"],
            "SK_DPD": ["mean", "max"],
            "SK_DPD_DEF": ["mean", "max"],
            "CNT_DRAWINGS_CURRENT": ["mean", "max"],
            "UTILIZATION": ["mean", "max"],
            "PAYMENT_RATIO": ["mean", "max"],
            "DRAWING_LIMIT_RATIO": ["mean", "max"],
        },
        "credit",
    )
    recent_frames = _top_k_aggregate(
        credit,
        "SK_ID_CURR",
        "MONTHS_BALANCE",
        {
            "AMT_BALANCE": ["mean", "max"],
            "AMT_PAYMENT_TOTAL_CURRENT": ["mean", "sum"],
            "SK_DPD": ["max", "mean"],
            "UTILIZATION": ["mean", "max"],
            "PAYMENT_RATIO": ["mean", "max"],
        },
        "credit_recent",
        windows=[3, 5, 10],
    )
    month_frames = _threshold_aggregate(
        credit,
        "SK_ID_CURR",
        {
            "AMT_BALANCE": ["mean", "max"],
            "AMT_PAYMENT_TOTAL_CURRENT": ["mean", "sum"],
            "SK_DPD": ["max", "mean"],
            "UTILIZATION": ["mean", "max"],
            "PAYMENT_RATIO": ["mean", "max"],
        },
        "credit_window",
        windows=[3, 6, 12],
        filter_col="MONTHS_BALANCE",
    )
    weighted_utilization = _weighted_average(
        credit,
        "SK_ID_CURR",
        "UTILIZATION",
        "recency_weight",
        "credit",
    )
    merged = _merge_feature_frames(agg, [weighted_utilization, *recent_frames, *month_frames])
    save_frame(reduce_memory(merged), cache_path)
    return merged


def installments_aggregate(config: PipelineConfig, force: bool = False) -> pd.DataFrame:
    cache_path = config.features_dir / "installments_agg.pkl"
    if cache_path.exists() and not force:
        return load_frame(cache_path)

    installments = load_table(
        config,
        "installments_payments",
        usecols=[
            "SK_ID_PREV",
            "SK_ID_CURR",
            "NUM_INSTALMENT_VERSION",
            "NUM_INSTALMENT_NUMBER",
            "DAYS_INSTALMENT",
            "DAYS_ENTRY_PAYMENT",
            "AMT_INSTALMENT",
            "AMT_PAYMENT",
        ],
    )
    installments["PAYMENT_PCT"] = safe_divide(installments["AMT_PAYMENT"], installments["AMT_INSTALMENT"])
    installments["PAYMENT_DIFF"] = installments["AMT_INSTALMENT"] - installments["AMT_PAYMENT"]
    installments["DAYS_PAST_DUE"] = (
        installments["DAYS_ENTRY_PAYMENT"] - installments["DAYS_INSTALMENT"]
    ).clip(lower=0)
    installments["DAYS_EARLY"] = (
        installments["DAYS_INSTALMENT"] - installments["DAYS_ENTRY_PAYMENT"]
    ).clip(lower=0)
    installments["late_payment_flag"] = (installments["DAYS_PAST_DUE"] > 0).astype("int8")
    installments["severe_late_flag"] = (installments["DAYS_PAST_DUE"] >= 30).astype("int8")
    installments["recency_weight"] = 1.0 / (installments["DAYS_INSTALMENT"].abs() + 1.0)
    agg = _aggregate_numeric(
        installments,
        "SK_ID_CURR",
        {
            "NUM_INSTALMENT_VERSION": ["nunique"],
            "NUM_INSTALMENT_NUMBER": ["max"],
            "DAYS_INSTALMENT": ["min", "max", "mean"],
            "DAYS_ENTRY_PAYMENT": ["min", "max", "mean"],
            "AMT_INSTALMENT": ["mean", "max", "sum"],
            "AMT_PAYMENT": ["mean", "max", "sum"],
            "PAYMENT_PCT": ["mean", "max", "min"],
            "PAYMENT_DIFF": ["mean", "max", "sum"],
            "DAYS_PAST_DUE": ["mean", "max", "sum"],
            "DAYS_EARLY": ["mean", "max"],
            "late_payment_flag": ["mean", "sum"],
            "severe_late_flag": ["mean", "sum"],
        },
        "install",
    )
    recent_frames = _top_k_aggregate(
        installments,
        "SK_ID_CURR",
        "DAYS_INSTALMENT",
        {
            "AMT_INSTALMENT": ["mean", "sum"],
            "AMT_PAYMENT": ["mean", "sum"],
            "PAYMENT_PCT": ["mean", "max"],
            "PAYMENT_DIFF": ["mean", "sum"],
            "DAYS_PAST_DUE": ["mean", "max"],
            "late_payment_flag": ["mean"],
        },
        "install_recent",
        windows=[2, 3, 5],
    )
    day_frames = _threshold_aggregate(
        installments,
        "SK_ID_CURR",
        {
            "AMT_INSTALMENT": ["mean", "sum"],
            "AMT_PAYMENT": ["mean", "sum"],
            "PAYMENT_PCT": ["mean", "max"],
            "PAYMENT_DIFF": ["mean", "sum"],
            "DAYS_PAST_DUE": ["mean", "max"],
            "late_payment_flag": ["mean"],
            "severe_late_flag": ["mean"],
        },
        "install_window",
        windows=[60, 90, 180, 365],
        filter_col="DAYS_INSTALMENT",
    )
    installment_number_frames = []
    for installment_number in [1, 2, 3, 4]:
        installment_slice = installments[installments["NUM_INSTALMENT_NUMBER"] == installment_number]
        if installment_slice.empty:
            continue
        installment_number_frames.append(
            _aggregate_numeric(
                installment_slice,
                "SK_ID_CURR",
                {
                    "AMT_INSTALMENT": ["mean", "sum"],
                    "AMT_PAYMENT": ["mean", "sum"],
                    "PAYMENT_PCT": ["mean", "max"],
                    "DAYS_PAST_DUE": ["mean", "max"],
                },
                f"install_num{installment_number}",
            )
        )
    past_due = installments[installments["DAYS_PAST_DUE"] > 0]
    past_due_agg = _aggregate_numeric(
        past_due,
        "SK_ID_CURR",
        {
            "PAYMENT_DIFF": ["mean", "sum"],
            "DAYS_PAST_DUE": ["mean", "max", "sum"],
            "late_payment_flag": ["mean", "sum"],
            "severe_late_flag": ["mean", "sum"],
        },
        "install_past_due",
    )
    weighted_payment = _weighted_average(
        installments,
        "SK_ID_CURR",
        "PAYMENT_PCT",
        "recency_weight",
        "install",
    )
    agg = _merge_feature_frames(
        agg,
        [past_due_agg, weighted_payment, *recent_frames, *day_frames, *installment_number_frames],
    )
    agg = agg.rename(columns={"install_late_payment_flag_mean": "install_late_payment_rate"})
    save_frame(reduce_memory(agg), cache_path)
    return agg


@dataclass(slots=True)
class FeatureBundle:
    master: pd.DataFrame
    explainable_features: list[str]
    leaderboard_features: list[str]
    categorical_features: list[str]


def build_master_table(config: PipelineConfig, force: bool = False) -> FeatureBundle:
    config.ensure_directories()
    cache_path = config.features_dir / "master_table.pkl"
    if cache_path.exists() and not force:
        master = load_frame(cache_path)
        explainable = load_frame(config.features_dir / "explainable_features.csv")["feature"].tolist()
        leaderboard = load_frame(config.features_dir / "leaderboard_features.csv")["feature"].tolist()
        categoricals = load_frame(config.features_dir / "categorical_features.csv")["feature"].tolist()
        return FeatureBundle(master, explainable, leaderboard, categoricals)

    master = application_frame(config)
    aggregates = [
        bureau_aggregate(config, force=force),
        previous_application_aggregate(config, force=force),
        pos_cash_aggregate(config, force=force),
        credit_card_aggregate(config, force=force),
        installments_aggregate(config, force=force),
    ]
    for agg in aggregates:
        master = master.merge(agg, on="SK_ID_CURR", how="left")

    explainable = [
        col
        for col in EXPLAINABLE_NUMERIC_FEATURES + EXPLAINABLE_CATEGORICALS
        if col in master.columns
    ]

    leaderboard = [
        col
        for col in master.columns
        if col
        not in {
            "TARGET",
            "dataset_split",
            "SK_ID_CURR",
        }
    ]
    categoricals = [
        col
        for col in master.columns
        if not pd.api.types.is_numeric_dtype(master[col]) and col not in {"dataset_split"}
    ]

    master = reduce_memory(master)
    save_frame(master, cache_path)
    save_frame(pd.DataFrame({"feature": explainable}), config.features_dir / "explainable_features.csv")
    save_frame(pd.DataFrame({"feature": leaderboard}), config.features_dir / "leaderboard_features.csv")
    save_frame(pd.DataFrame({"feature": categoricals}), config.features_dir / "categorical_features.csv")
    return FeatureBundle(master, explainable, leaderboard, categoricals)


def build_folds(master: pd.DataFrame, config: PipelineConfig, force: bool = False) -> pd.DataFrame:
    path = config.artifacts_dir / "folds.csv"
    if path.exists() and not force:
        return load_frame(path)

    train = master[master["TARGET"].notna()][["SK_ID_CURR", "TARGET"]].copy()
    train["TARGET"] = train["TARGET"].astype(int)
    train["fold"] = -1
    splitter = StratifiedKFold(
        n_splits=config.n_folds,
        shuffle=True,
        random_state=config.random_state,
    )
    for fold, (_, valid_idx) in enumerate(splitter.split(train[["SK_ID_CURR"]], train["TARGET"])):
        train.iloc[valid_idx, train.columns.get_loc("fold")] = fold
    save_frame(train, path)
    return train


def leaderboard_matrix(
    bundle: FeatureBundle,
    config: PipelineConfig | None = None,
    force: bool = False,
) -> tuple[pd.DataFrame, list[str]]:
    if config is not None:
        matrix_cache = config.features_dir / "leaderboard_matrix.pkl"
        names_cache = config.features_dir / "leaderboard_matrix_features.csv"
        if matrix_cache.exists() and names_cache.exists() and not force:
            matrix = load_frame(matrix_cache)
            feature_names = load_frame(names_cache)["feature"].tolist()
            if all(pd.api.types.is_numeric_dtype(matrix[col]) for col in feature_names):
                return matrix, feature_names

    master = bundle.master.copy()
    categorical_cols = [
        col
        for col in bundle.leaderboard_features
        if col in master.columns and not pd.api.types.is_numeric_dtype(master[col])
    ]
    encoded = pd.get_dummies(
        master[bundle.leaderboard_features],
        columns=categorical_cols,
        dummy_na=True,
    )
    encoded = reduce_memory(encoded)
    feature_names = encoded.columns.tolist()
    encoded = pd.concat(
        [
            encoded,
            master[["SK_ID_CURR", "TARGET", "dataset_split"]].reset_index(drop=True),
        ],
        axis=1,
    )
    if config is not None:
        save_frame(encoded, config.features_dir / "leaderboard_matrix.pkl")
        save_frame(
            pd.DataFrame({"feature": feature_names}),
            config.features_dir / "leaderboard_matrix_features.csv",
        )
    return encoded, feature_names


def explainable_matrix(bundle: FeatureBundle) -> pd.DataFrame:
    cols = ["SK_ID_CURR", "TARGET", "dataset_split", *bundle.explainable_features]
    return bundle.master[cols].copy()

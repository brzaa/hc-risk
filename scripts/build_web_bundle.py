from __future__ import annotations

import json
import math
import re
import shutil
import sqlite3
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
from matplotlib import pyplot as plt

matplotlib.use("Agg")


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
LOOKUP_DB = DATA_DIR / "web_lookup.db"
OUTPUTS_DIR = ROOT / "outputs"
DATASET_DIR = ROOT / "dataset"
PLOTS_DIR = DATA_DIR / "plots"
BORROWERS_DIR = ROOT / "borrowers"

PROFILE_COLUMNS = [
    "SK_ID_CURR",
    "TARGET",
    "NAME_CONTRACT_TYPE",
    "CODE_GENDER",
    "NAME_INCOME_TYPE",
    "NAME_EDUCATION_TYPE",
    "NAME_FAMILY_STATUS",
    "NAME_HOUSING_TYPE",
    "CNT_CHILDREN",
    "CNT_FAM_MEMBERS",
    "AMT_INCOME_TOTAL",
    "AMT_CREDIT",
    "AMT_ANNUITY",
    "AMT_GOODS_PRICE",
    "DAYS_BIRTH",
    "DAYS_EMPLOYED",
    "EXT_SOURCE_1",
    "EXT_SOURCE_2",
    "EXT_SOURCE_3",
]

NOTEBOOK_FEATURE_SOURCES = {
    "payment_rate": "PAYMENT_RATE",
    "credit_income_ratio": "CREDIT_INCOME_RATIO",
    "annuity_income_pct": "ANNUITY_INCOME_PCT",
    "credit_annuity_ratio": "CREDIT_ANNUITY_RATIO",
    "income_per_person": "INCOME_PER_PERSON",
    "ext_source_mean": "EXT_SOURCE_MEAN",
    "bureau_total_debt_ratio": "bureau_total_debt_ratio",
    "install_late_payment_rate": "install_late_payment_rate",
    "previous_refused_count": "previous_refused_count",
}

DISPLAY_NAMES = {
    "payment_rate": "Payment Rate",
    "credit_income_ratio": "Credit / Income",
    "annuity_income_pct": "Annuity / Income",
    "credit_annuity_ratio": "Credit / Annuity",
    "income_per_person": "Income / Family Member",
    "ext_source_mean": "External Score Mean",
    "bureau_total_debt_ratio": "Bureau Debt / Credit",
    "install_late_payment_rate": "Installment Late Rate",
    "previous_refused_count": "Previous Refused Count",
}


def _to_builtin(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, (np.floating, float)):
        if math.isnan(float(value)) or math.isinf(float(value)):
            return None
        return round(float(value), 6)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if pd.isna(value):
        return None
    return value


def _load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text())


def _safe_divide(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    denom = denominator.replace(0, np.nan)
    return numerator / denom


def _interval_label(interval: pd.Interval | object) -> str:
    if not isinstance(interval, pd.Interval):
        return str(interval)
    left = "-inf" if not np.isfinite(interval.left) else f"{interval.left:.2f}"
    right = "inf" if not np.isfinite(interval.right) else f"{interval.right:.2f}"
    return f"[{left}, {right})"


def _enrich_application(frame: pd.DataFrame) -> pd.DataFrame:
    enriched = frame.copy()
    enriched["DAYS_EMPLOYED_ANOM"] = (enriched["DAYS_EMPLOYED"] == 365243).astype(int)
    enriched.loc[enriched["DAYS_EMPLOYED"] == 365243, "DAYS_EMPLOYED"] = np.nan
    ext = enriched[["EXT_SOURCE_1", "EXT_SOURCE_2", "EXT_SOURCE_3"]]
    enriched["payment_rate"] = _safe_divide(enriched["AMT_ANNUITY"], enriched["AMT_CREDIT"])
    enriched["credit_income_ratio"] = _safe_divide(enriched["AMT_CREDIT"], enriched["AMT_INCOME_TOTAL"])
    enriched["annuity_income_pct"] = _safe_divide(enriched["AMT_ANNUITY"], enriched["AMT_INCOME_TOTAL"])
    enriched["credit_annuity_ratio"] = _safe_divide(enriched["AMT_CREDIT"], enriched["AMT_ANNUITY"])
    enriched["credit_goods_ratio"] = _safe_divide(enriched["AMT_CREDIT"], enriched["AMT_GOODS_PRICE"])
    enriched["income_per_person"] = _safe_divide(enriched["AMT_INCOME_TOTAL"], enriched["CNT_FAM_MEMBERS"])
    enriched["age_years"] = -enriched["DAYS_BIRTH"] / 365.0
    enriched["employment_years"] = -enriched["DAYS_EMPLOYED"] / 365.0
    enriched["ext_source_mean"] = ext.mean(axis=1)
    enriched["ext_source_min"] = ext.min(axis=1)
    enriched["ext_source_max"] = ext.max(axis=1)
    enriched["ext_source_count"] = ext.notna().sum(axis=1)
    return enriched


def _risk_ladder(frame: pd.DataFrame, feature: str, bins: int = 5) -> pd.DataFrame:
    subset = frame[[feature, "TARGET"]].copy()
    subset = subset[subset["TARGET"].notna()]
    subset["TARGET"] = subset["TARGET"].astype(int)
    numeric = pd.to_numeric(subset[feature], errors="coerce")
    non_missing = numeric.notna()
    if non_missing.sum() < bins * 20:
        return pd.DataFrame(columns=["feature", "bucket", "default_rate", "count"])
    unique_values = numeric[non_missing].nunique()
    if unique_values < 2:
        return pd.DataFrame(columns=["feature", "bucket", "default_rate", "count"])
    bucket_count = int(min(bins, unique_values))
    buckets = pd.qcut(numeric[non_missing], q=bucket_count, duplicates="drop")
    bucketed = (
        subset.loc[non_missing]
        .assign(bucket=buckets)
        .groupby("bucket", observed=True)
        .agg(default_rate=("TARGET", "mean"), count=("TARGET", "size"))
        .reset_index()
    )
    bucketed["feature"] = feature
    bucketed["bucket"] = bucketed["bucket"].map(_interval_label)
    if (~non_missing).any():
        missing_rate = subset.loc[~non_missing, "TARGET"].mean()
        bucketed = pd.concat(
            [
                bucketed,
                pd.DataFrame(
                    [
                        {
                            "feature": feature,
                            "bucket": "Missing",
                            "default_rate": missing_rate,
                            "count": int((~non_missing).sum()),
                        }
                    ]
                ),
            ],
            axis=0,
            ignore_index=True,
        )
    return bucketed


def _kaplan_meier_curve(
    durations: pd.Series,
    events: pd.Series,
    max_time: int,
) -> pd.DataFrame:
    durations = pd.to_numeric(durations, errors="coerce").fillna(max_time).clip(lower=0, upper=max_time).astype(int)
    events = pd.to_numeric(events, errors="coerce").fillna(0).astype(int)
    survival_probability = 1.0
    at_risk = len(durations)
    rows = [{"month_on_book": 0, "survival_probability": 1.0, "n_at_risk": at_risk, "events": 0}]
    for month in range(1, max_time + 1):
        month_events = int(((durations == month) & (events == 1)).sum())
        month_exits = int((durations == month).sum())
        if at_risk > 0:
            survival_probability *= (1.0 - (month_events / at_risk))
        rows.append(
            {
                "month_on_book": month,
                "survival_probability": survival_probability,
                "n_at_risk": at_risk,
                "events": month_events,
            }
        )
        at_risk -= month_exits
    return pd.DataFrame(rows)


def _series_points(frame: pd.DataFrame, x_col: str, y_col: str, extra_cols: list[str] | None = None) -> list[dict[str, object]]:
    points: list[dict[str, object]] = []
    columns = [x_col, y_col, *(extra_cols or [])]
    for row in frame[columns].itertuples(index=False):
        payload = {
            x_col: _to_builtin(getattr(row, x_col)),
            y_col: _to_builtin(getattr(row, y_col)),
        }
        for column in extra_cols or []:
            payload[column] = _to_builtin(getattr(row, column))
        points.append(payload)
    return points


def _calibration_label(left: float, right: float) -> str:
    return f"{int(round(left * 100))}-{int(round(right * 100))}%"


def _calibration_summary(calibration_bins: list[dict[str, object]]) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    for item in calibration_bins:
        avg_prediction = float(item.get("avg_prediction", 0.0) or 0.0)
        observed_default_rate = float(item.get("observed_default_rate", 0.0) or 0.0)
        gap = observed_default_rate - avg_prediction
        rows.append(
            {
                "label": _calibration_label(float(item.get("bin_left", 0.0) or 0.0), float(item.get("bin_right", 0.0) or 0.0)),
                "bin_left": _to_builtin(item.get("bin_left")),
                "bin_right": _to_builtin(item.get("bin_right")),
                "avg_prediction": _to_builtin(avg_prediction),
                "observed_default_rate": _to_builtin(observed_default_rate),
                "count": _to_builtin(item.get("count")),
                "gap": _to_builtin(gap),
                "absolute_gap": _to_builtin(abs(gap)),
            }
        )
    if not rows:
        return {
            "bins": [],
            "mean_absolute_gap": None,
            "max_absolute_gap": None,
            "max_gap_bin": None,
        }
    max_gap_bin = max(rows, key=lambda item: float(item["absolute_gap"] or 0.0))
    mean_absolute_gap = float(np.mean([float(item["absolute_gap"] or 0.0) for item in rows]))
    return {
        "bins": rows,
        "mean_absolute_gap": _to_builtin(mean_absolute_gap),
        "max_absolute_gap": max_gap_bin["absolute_gap"],
        "max_gap_bin": max_gap_bin,
    }


def _weighted_average(frame: pd.DataFrame, value_col: str, weight_col: str) -> float | None:
    if frame.empty or value_col not in frame.columns or weight_col not in frame.columns:
        return None
    weights = frame[weight_col].fillna(0).to_numpy(dtype=float)
    values = frame[value_col].fillna(0).to_numpy(dtype=float)
    if weights.sum() <= 0:
        return None
    return float(np.average(values, weights=weights))


def _score_decile_summary(
    scorecard_predictions: pd.DataFrame,
    application_train: pd.DataFrame,
    lgd_assumption: float = 0.45,
) -> dict[str, object]:
    train_predictions = scorecard_predictions[scorecard_predictions["dataset_split"] == "train"].copy()
    train_predictions = train_predictions.dropna(subset=["scorecard_probability", "TARGET"])
    if train_predictions.empty:
        return {
            "deciles": [],
            "policy_bands": [],
            "assumptions": {
                "lgd": _to_builtin(lgd_assumption),
                "formula": "Expected loss proxy = PD x exposure x LGD",
                "sample_note": "No scorecard train predictions were available.",
            },
        }

    train_predictions["TARGET"] = train_predictions["TARGET"].astype(int)
    exposure_slice = application_train[["SK_ID_CURR", "AMT_CREDIT", "AMT_ANNUITY", "AMT_INCOME_TOTAL"]].copy()
    train_predictions = train_predictions.merge(exposure_slice, on="SK_ID_CURR", how="left")
    train_predictions["score_decile"] = pd.qcut(
        train_predictions["scorecard_probability"].rank(method="first"),
        q=10,
        labels=False,
    ).astype(int) + 1
    train_predictions["expected_loss_proxy"] = (
        train_predictions["scorecard_probability"].fillna(0)
        * train_predictions["AMT_CREDIT"].fillna(0)
        * lgd_assumption
    )

    deciles = (
        train_predictions.groupby("score_decile", as_index=False)
        .agg(
            borrowers=("SK_ID_CURR", "size"),
            avg_prediction=("scorecard_probability", "mean"),
            observed_default_rate=("TARGET", "mean"),
            avg_credit=("AMT_CREDIT", "mean"),
            avg_annuity=("AMT_ANNUITY", "mean"),
            avg_income=("AMT_INCOME_TOTAL", "mean"),
            total_credit=("AMT_CREDIT", "sum"),
            total_expected_loss_proxy=("expected_loss_proxy", "sum"),
        )
        .sort_values("score_decile")
        .reset_index(drop=True)
    )
    total_expected_loss = float(deciles["total_expected_loss_proxy"].sum() or 0.0)
    total_borrowers = int(deciles["borrowers"].sum())
    decile_records = []
    for row in deciles.itertuples(index=False):
        decile_records.append(
            {
                "score_decile": int(row.score_decile),
                "label": f"D{int(row.score_decile)}",
                "borrowers": int(row.borrowers),
                "share_of_sample": _to_builtin(row.borrowers / max(total_borrowers, 1)),
                "avg_prediction": _to_builtin(row.avg_prediction),
                "observed_default_rate": _to_builtin(row.observed_default_rate),
                "avg_credit": _to_builtin(row.avg_credit),
                "avg_annuity": _to_builtin(row.avg_annuity),
                "avg_income": _to_builtin(row.avg_income),
                "total_credit": _to_builtin(row.total_credit),
                "total_expected_loss_proxy": _to_builtin(row.total_expected_loss_proxy),
                "loss_share": _to_builtin(row.total_expected_loss_proxy / total_expected_loss) if total_expected_loss > 0 else None,
            }
        )

    band_specs = [
        {
            "decision": "Approve",
            "state": "approve",
            "deciles": [1, 2, 3, 4],
            "decile_range": "D1-D4",
            "rule": "Fast-track approvals when the borrower is in the safest score bands and no hard policy flag overrides the score.",
        },
        {
            "decision": "Manual Review",
            "state": "review",
            "deciles": [5, 6, 7],
            "decile_range": "D5-D7",
            "rule": "Route mid-risk borrowers to analyst review, income verification, or tighter affordability checks.",
        },
        {
            "decision": "Decline",
            "state": "decline",
            "deciles": [8, 9, 10],
            "decile_range": "D8-D10",
            "rule": "Decline or require a challenger review when the score falls in the riskiest bands and adverse signals cluster together.",
        },
    ]
    policy_bands = []
    for spec in band_specs:
        band_frame = train_predictions[train_predictions["score_decile"].isin(spec["deciles"])].copy()
        decile_frame = deciles[deciles["score_decile"].isin(spec["deciles"])].copy()
        if band_frame.empty or decile_frame.empty:
            continue
        policy_bands.append(
            {
                "decision": spec["decision"],
                "state": spec["state"],
                "decile_range": spec["decile_range"],
                "rule": spec["rule"],
                "borrowers": int(len(band_frame)),
                "share_of_sample": _to_builtin(len(band_frame) / max(len(train_predictions), 1)),
                "avg_prediction": _to_builtin(band_frame["scorecard_probability"].mean()),
                "observed_default_rate": _to_builtin(band_frame["TARGET"].mean()),
                "avg_credit": _to_builtin(band_frame["AMT_CREDIT"].mean()),
                "total_expected_loss_proxy": _to_builtin(band_frame["expected_loss_proxy"].sum()),
                "loss_share": _to_builtin(decile_frame["total_expected_loss_proxy"].sum() / total_expected_loss) if total_expected_loss > 0 else None,
            }
        )

    return {
        "deciles": decile_records,
        "policy_bands": policy_bands,
        "assumptions": {
            "lgd": _to_builtin(lgd_assumption),
            "formula": "Expected loss proxy = PD x exposure x LGD",
            "sample_note": "Deciles are based on the prepared scorecard train sample, not the full Home Credit training population.",
        },
    }


def _vintage_trigger(vintage_curves: list[dict[str, object]]) -> dict[str, object]:
    cohort_rows = []
    for curve in vintage_curves:
        try:
            cohort_num = int(str(curve["cohort"]).split("-")[1])
        except (IndexError, ValueError, KeyError):
            continue
        points = {int(point["month_on_book"]): float(point["cumulative_default_rate"]) for point in curve.get("points", [])}
        cohort_rows.append(
            {
                "cohort": curve["cohort"],
                "cohort_num": cohort_num,
                "mob6_rate": points.get(6, 0.0),
            }
        )
    if len(cohort_rows) < 6:
        return {
            "title": "Vintage deterioration trigger",
            "state": "neutral",
            "threshold": "Latest three cohorts 6-MOB severe delinquency exceeds 120% of the prior three cohorts.",
            "current_value": "Not enough cohorts in the prepared bundle.",
            "action": "Track seasoning monthly before changing policy.",
        }
    ordered = sorted(cohort_rows, key=lambda item: item["cohort_num"])
    latest = ordered[:3]
    prior = ordered[3:6]
    latest_avg = float(np.mean([item["mob6_rate"] for item in latest]))
    prior_avg = float(np.mean([item["mob6_rate"] for item in prior]))
    ratio = latest_avg / prior_avg if prior_avg > 0 else 0.0
    state = "watch" if ratio >= 1.2 else "healthy"
    return {
        "title": "Vintage deterioration trigger",
        "state": state,
        "threshold": "Latest three cohorts 6-MOB severe delinquency exceeds 120% of the prior three cohorts.",
        "current_value": (
            f"Latest avg {latest_avg:.3%} vs prior avg {prior_avg:.3%} "
            f"({ratio:.2f}x)."
        ),
        "action": (
            "Tighten origination and refresh collections segmentation if recent vintages season materially worse."
            if state == "watch"
            else "Recent vintages are not deteriorating faster than the trailing reference cohorts."
        ),
    }


def _strategy_payload(
    scorecard: dict[str, object],
    leaderboard: dict[str, object],
    feature_diag: pd.DataFrame,
    vintage_curves: list[dict[str, object]],
    decile_summary: dict[str, object],
) -> dict[str, object]:
    scorecard_calibration = _calibration_summary(scorecard.get("calibration_bins", []))
    blend_calibration = _calibration_summary(leaderboard.get("blend", {}).get("calibration_bins", []))

    max_psi_row = (
        feature_diag.sort_values("psi_train_test", ascending=False).iloc[0].to_dict()
        if not feature_diag.empty
        else {}
    )
    max_psi = float(max_psi_row.get("psi_train_test", 0.0) or 0.0)
    psi_state = "healthy" if max_psi < 0.1 else "watch" if max_psi < 0.25 else "breach"

    auc_uplift = float(leaderboard.get("blend", {}).get("roc_auc", 0.0) or 0.0) - float(scorecard.get("roc_auc", 0.0) or 0.0)
    scorecard_gap = float(scorecard_calibration.get("mean_absolute_gap") or 0.0)
    blend_gap = float(blend_calibration.get("mean_absolute_gap") or 0.0)
    challenger_ready = auc_uplift >= 0.02 and blend_gap <= scorecard_gap + 0.01

    policy_triggers = [
        {
            "title": "PSI trigger",
            "state": psi_state,
            "threshold": "Any scorecard feature with PSI >= 0.10 enters watch; PSI >= 0.25 blocks policy changes until re-binning.",
            "current_value": (
                f"Max observed PSI {max_psi:.3f} on {str(max_psi_row.get('feature', 'n/a')).replace('_', ' ')}."
            ),
            "action": (
                "Escalate to feature review, inspect bucket coverage, and cut a replacement binning plan."
                if psi_state != "healthy"
                else "Keep the feature on watch, but current train-vs-test drift is below the review threshold."
            ),
        },
        _vintage_trigger(vintage_curves),
        {
            "title": "Challenger launch condition",
            "state": "ready" if challenger_ready else "not-ready",
            "threshold": "Launch a challenger only if AUC improves by at least 0.02 and calibration does not worsen.",
            "current_value": (
                f"Benchmark AUC delta {auc_uplift:+.3f}; calibration gap "
                f"{blend_gap:.3f} vs scorecard {scorecard_gap:.3f}."
            ),
            "action": (
                "Promote the challenger into parallel monitoring."
                if challenger_ready
                else "Keep the explainable scorecard as the operating surface; the current benchmark does not clear the governance gate."
            ),
        },
    ]

    return {
        "policy_bands": decile_summary.get("policy_bands", []),
        "policy_triggers": policy_triggers,
    }


def _governance_payload(
    proxy_review: dict[str, object],
    feature_diag: pd.DataFrame,
) -> dict[str, object]:
    excluded = [str(value) for value in proxy_review.get("scorecard_exclusions", [])]
    top_psi_row = (
        feature_diag.sort_values("psi_train_test", ascending=False).iloc[0].to_dict()
        if not feature_diag.empty
        else {}
    )
    proxy_notes = [
        {
            "title": "Occupation and employer labels stay out of scorecard policy.",
            "body": "OCCUPATION_TYPE and ORGANIZATION_TYPE are excluded to reduce proxying for socio-economic segments and to avoid unstable employer taxonomies becoming approval logic.",
        },
        {
            "title": "Application timestamp fields are treated as process artifacts.",
            "body": "WEEKDAY_APPR_PROCESS_START and HOUR_APPR_PROCESS_START are excluded because they reflect channel operations and staffing patterns more than borrower quality.",
        },
        {
            "title": "Sparse document flags are kept out of policy-facing modeling.",
            "body": "Low-frequency FLAG_DOCUMENT_* fields are excluded because they are brittle, hard to challenge, and easy to over-interpret in manual review.",
        },
    ]
    missingness_notes = [
        {
            "title": "Sentinel anomaly handling",
            "body": (
                f"{format(int(proxy_review.get('days_employed_anomalies', 0)), ',')} "
                "DAYS_EMPLOYED sentinel values are surfaced as an explicit anomaly flag before score generation."
            ),
        },
        {
            "title": "Coverage-sensitive feature families stay on watch",
            "body": "The heaviest missingness sits in revolving-credit payment and utilization windows, so coverage shifts are treated as governance events rather than silent imputations.",
        },
        {
            "title": "Current maximum PSI feature",
            "body": (
                f"{str(top_psi_row.get('feature', 'n/a')).replace('_', ' ')} is the most drift-sensitive monitored feature "
                f"at PSI {float(top_psi_row.get('psi_train_test', 0.0) or 0.0):.3f}."
            ),
        },
    ]
    fraud_extension = [
        {
            "title": "Application velocity",
            "body": "Count repeated applications, rapid resubmits, and bursty bureau pulls inside short time windows before approval.",
        },
        {
            "title": "Identity consistency",
            "body": "Cross-check applicant identity fields, employer history, and declared income consistency across prior records and bureau touchpoints.",
        },
        {
            "title": "Bureau inquiry bursts",
            "body": "Add high-frequency recent inquiry features as a fraud-and-distress overlay, especially when they arrive with thin repayment history.",
        },
        {
            "title": "Device and session anomalies",
            "body": "In a production stack, join device, IP, and session behavior to the credit score so synthetic applications can be routed to fraud review before booking.",
        },
    ]
    return {
        "max_feature_psi": _to_builtin(top_psi_row.get("psi_train_test")),
        "max_psi_feature": _to_builtin(top_psi_row.get("feature")),
        "excluded_features": excluded,
        "proxy_notes": proxy_notes,
        "missingness_watch": proxy_review.get("top_missing_features", [])[:8],
        "missingness_notes": missingness_notes,
        "days_employed_anomalies": _to_builtin(proxy_review.get("days_employed_anomalies")),
        "fraud_extension": fraud_extension,
    }


def _write_static_plots(summary: dict[str, object]) -> None:
    analysis_plots = summary["analysis_plots"]
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)

    target_distribution = pd.DataFrame(analysis_plots["target_distribution"])
    portfolio_profile = pd.DataFrame(analysis_plots["portfolio_profile"])
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))
    axes[0].bar(target_distribution["label"], target_distribution["value"], color=["#61674b", "#b74b47"])
    axes[0].set_title("Target Distribution")
    axes[0].set_ylabel("Borrowers")
    axes[0].grid(axis="y", alpha=0.2)
    portfolio_profile.set_index("dataset")[["avg_income", "avg_credit", "avg_annuity"]].plot(kind="bar", ax=axes[1])
    axes[1].set_title("Train vs Test Portfolio Profile")
    axes[1].set_ylabel("Amount")
    axes[1].tick_params(axis="x", rotation=0)
    axes[1].grid(axis="y", alpha=0.2)
    plt.tight_layout()
    fig.savefig(PLOTS_DIR / "portfolio_overview.svg", format="svg", bbox_inches="tight")
    plt.close(fig)

    capacity_ladders = analysis_plots["capacity_ladders"]
    willingness_ladders = analysis_plots["willingness_ladders"]
    max_cols = max(1, len(capacity_ladders), len(willingness_ladders))
    fig, axes = plt.subplots(2, max_cols, figsize=(4.2 * max_cols, 8.2), squeeze=False)
    for index, item in enumerate(capacity_ladders):
        plot_df = pd.DataFrame(item["points"])
        ax = axes[0, index]
        ax.plot(range(len(plot_df)), plot_df["default_rate"], marker="o", color="#9a5c39", linewidth=2.5)
        ax.set_title(item["display_name"])
        ax.set_xticks(range(len(plot_df)))
        ax.set_xticklabels([str(i + 1) for i in range(len(plot_df))], rotation=0)
        ax.set_ylabel("Default Rate")
        ax.grid(axis="y", alpha=0.2)
    for index in range(len(capacity_ladders), max_cols):
        axes[0, index].axis("off")
    for index, item in enumerate(willingness_ladders):
        plot_df = pd.DataFrame(item["points"])
        ax = axes[1, index]
        ax.plot(range(len(plot_df)), plot_df["default_rate"], marker="o", color="#40667a", linewidth=2.5)
        ax.set_title(item["display_name"])
        ax.set_xticks(range(len(plot_df)))
        ax.set_xticklabels([str(i + 1) for i in range(len(plot_df))], rotation=0)
        ax.set_ylabel("Default Rate")
        ax.grid(axis="y", alpha=0.2)
    for index in range(len(willingness_ladders), max_cols):
        axes[1, index].axis("off")
    axes[0, 0].text(-0.08, 1.08, "Capacity", transform=axes[0, 0].transAxes, fontsize=12, fontweight="bold")
    axes[1, 0].text(-0.08, 1.08, "Willingness", transform=axes[1, 0].transAxes, fontsize=12, fontweight="bold")
    plt.tight_layout()
    fig.savefig(PLOTS_DIR / "capacity_willingness.svg", format="svg", bbox_inches="tight")
    plt.close(fig)

    vintage_curves = analysis_plots["vintage_curves"]
    fig, ax = plt.subplots(figsize=(10, 6))
    for item in vintage_curves:
        plot_df = pd.DataFrame(item["points"])
        ax.plot(plot_df["month_on_book"], plot_df["cumulative_default_rate"], marker="o", linewidth=1.8, label=item["cohort"])
    ax.set_title("Vintage Analysis: Severe 30+ DPD by Relative Cohort")
    ax.set_xlabel("Months on Book")
    ax.set_ylabel("Cumulative Severe Delinquency Rate")
    ax.grid(alpha=0.2)
    ax.legend(loc="upper left", ncol=2, frameon=False)
    plt.tight_layout()
    fig.savefig(PLOTS_DIR / "vintage_analysis.svg", format="svg", bbox_inches="tight")
    plt.close(fig)

    survival_curve = pd.DataFrame(analysis_plots["survival_curve"])
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.step(survival_curve["month_on_book"], survival_curve["survival_probability"], where="post", color="#61674b", linewidth=2.5)
    ax.set_title("Kaplan-Meier Style Survival Curve")
    ax.set_xlabel("Months on Book")
    ax.set_ylabel("Survival Probability")
    ax.set_ylim(bottom=max(0.7, survival_curve["survival_probability"].min() - 0.02), top=1.01)
    ax.grid(alpha=0.2)
    plt.tight_layout()
    fig.savefig(PLOTS_DIR / "survival_curve.svg", format="svg", bbox_inches="tight")
    plt.close(fig)

    missing_top = pd.DataFrame(analysis_plots["missing_top"]).sort_values("missing_fraction", ascending=True)
    fig, ax = plt.subplots(figsize=(8.5, 5.5))
    ax.barh(missing_top["feature"], missing_top["missing_fraction"], color="#9a5c39")
    ax.set_title("Top Missing Features")
    ax.set_xlabel("Missing Fraction")
    ax.grid(axis="x", alpha=0.2)
    plt.tight_layout()
    fig.savefig(PLOTS_DIR / "missingness.svg", format="svg", bbox_inches="tight")
    plt.close(fig)

    top_iv = pd.DataFrame(summary["scorecard"]["top_iv"]).sort_values("iv", ascending=True).tail(8)
    top_psi = pd.DataFrame(summary["scorecard"]["top_psi"]).sort_values("psi_train_test", ascending=True).tail(8)
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.5))
    axes[0].barh(top_iv["feature"], top_iv["iv"], color="#40667a")
    axes[0].set_title("Top Scorecard Features by IV")
    axes[0].set_xlabel("Information Value")
    axes[0].grid(axis="x", alpha=0.2)
    axes[1].barh(top_psi["feature"], top_psi["psi_train_test"], color="#b74b47")
    axes[1].set_title("Top Train/Test PSI Features")
    axes[1].set_xlabel("Population Stability Index")
    axes[1].grid(axis="x", alpha=0.2)
    plt.tight_layout()
    fig.savefig(PLOTS_DIR / "scorecard_diagnostics.svg", format="svg", bbox_inches="tight")
    plt.close(fig)


def _write_borrower_pages(summary: dict[str, object]) -> None:
    import importlib.util

    module_path = ROOT / "api" / "borrower.py"
    spec = importlib.util.spec_from_file_location("borrower_lookup", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load borrower lookup module from {module_path}")
    borrower_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(borrower_module)
    lookup_borrower = borrower_module.lookup_borrower

    BORROWERS_DIR.mkdir(parents=True, exist_ok=True)
    borrower_ids = {
        182619,
        *summary["featured_borrowers"]["highest_scorecard_risk_train"],
        *summary["featured_borrowers"]["lowest_scorecard_risk_train"],
        *summary["featured_borrowers"]["sample_test_ids"],
    }

    for borrower_id in borrower_ids:
        payload = lookup_borrower(int(borrower_id))
        if payload is None:
            continue
        reasons_html = "".join(
            f"""
            <div class="reason-item">
              <span>{reason['feature']}</span>
              <strong>{reason['contribution'] if reason['contribution'] is not None else '—'}</strong>
              <span>Raw: {reason['raw_value'] if reason['raw_value'] is not None else '—'}</span>
              <span>Bin: {reason['matched_bin'] if reason['matched_bin'] is not None else '—'}</span>
              <span>Points: {reason['points'] if reason['points'] is not None else '—'}</span>
            </div>
            """
            for reason in payload["reasons"]
        )
        detail_rows = [
            ("Contract Type", payload["profile"]["contract_type"]),
            ("Income Type", payload["profile"]["income_type"]),
            ("Family Status", payload["profile"]["family_status"]),
            ("Housing", payload["profile"]["housing_type"]),
            ("Income", payload["profile"]["income_total"]),
            ("Credit", payload["profile"]["credit_amount"]),
            ("Annuity", payload["profile"]["annuity_amount"]),
            ("Bureau Rows", payload["activity"]["bureau_rows"]),
            ("Previous Applications", payload["activity"]["previous_rows"]),
            ("Late Rate", payload["activity"]["installment_late_rate"]),
            ("Scorecard Probability", payload["scorecard"]["probability"]),
            ("Leaderboard Blend", payload["leaderboard"]["blend"]),
        ]
        details_html = "".join(
            f"<div class='detail-item'><span>{label}</span><strong>{_to_builtin(value) if _to_builtin(value) is not None else '—'}</strong></div>"
            for label, value in detail_rows
        )
        html = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Borrower {borrower_id}</title>
    <link rel="stylesheet" href="../styles.css" />
  </head>
  <body>
    <main class="site-main" style="padding-top:32px;">
      <section class="borrower-shell">
        <div class="borrower-hero">
          <div class="borrower-hero-copy">
            <span class="panel-tag">{payload['split'].title()} Borrower</span>
            <span class="owner-line">Portfolio by Bramastya Zaki</span>
            <h3>SK_ID_CURR {borrower_id}</h3>
            <p>A borrower-level trace connecting application context, credit history, explainable score contributions, and final model outputs.</p>
            <div class="hero-actions">
              <a class="ghost-button" href="/">Back to project</a>
            </div>
          </div>
          <div class="borrower-scoreboard">
            <div class="score-chip"><span>Observed Target</span><strong>{payload['target'] if payload['target'] is not None else 'Test'}</strong></div>
            <div class="score-chip"><span>Scorecard Probability</span><strong>{_to_builtin(payload['scorecard']['probability'])}</strong></div>
            <div class="score-chip"><span>Leaderboard Blend</span><strong>{_to_builtin(payload['leaderboard']['blend'])}</strong></div>
          </div>
        </div>
        <div class="borrower-grid">
          <article class="panel panel-span">
            <span class="panel-tag">Profile and Activity</span>
            <div class="detail-grid">{details_html}</div>
          </article>
          <article class="panel panel-span">
            <span class="panel-tag">Reason Codes</span>
            <div class="reason-list">{reasons_html}</div>
          </article>
        </div>
      </section>
    </main>
  </body>
</html>"""
        (BORROWERS_DIR / f"{borrower_id}.html").write_text(html)


def _parse_interval_label(label: str) -> dict[str, object] | None:
    match = re.match(r"^([\[(])\s*([^,]+),\s*([^\])]+)([\])])$", str(label))
    if not match:
        return None
    left_bracket, left_raw, right_raw, right_bracket = match.groups()
    left = -np.inf if left_raw.strip() == "-inf" else float(left_raw)
    right = np.inf if right_raw.strip() == "inf" else float(right_raw)
    return {
        "left": left,
        "right": right,
        "left_closed": left_bracket == "[",
        "right_closed": right_bracket == "]",
    }


def _match_bin(value: object, feature_bins: pd.DataFrame) -> dict[str, object] | None:
    if feature_bins.empty:
        return None
    if value is None or pd.isna(value):
        hit = feature_bins[feature_bins["label"] == "__MISSING__"]
        return hit.iloc[0].to_dict() if not hit.empty else None
    if feature_bins["feature_type"].iloc[0] == "categorical":
        hit = feature_bins[feature_bins["label"] == str(value)]
        if hit.empty:
            hit = feature_bins[feature_bins["label"] == "__OTHER__"]
        return hit.iloc[0].to_dict() if not hit.empty else None
    numeric_value = float(value)
    for _, row in feature_bins.iterrows():
        interval = _parse_interval_label(str(row["label"]))
        if interval is None:
            continue
        left_ok = numeric_value >= interval["left"] if interval["left_closed"] else numeric_value > interval["left"]
        right_ok = numeric_value <= interval["right"] if interval["right_closed"] else numeric_value < interval["right"]
        if left_ok and right_ok:
            return row.to_dict()
    return None


def _leaderboard_frame() -> pd.DataFrame:
    oof_path = OUTPUTS_DIR / "predictions" / "leaderboard_oof.csv"
    test_path = OUTPUTS_DIR / "predictions" / "leaderboard_test_predictions.csv"
    parts = []
    if oof_path.exists():
        oof = pd.read_csv(oof_path)
        parts.append(
            oof.rename(
                columns={
                    "lightgbm_gbdt": "lightgbm",
                    "xgboost": "xgboost",
                    "catboost": "catboost",
                    "stack_logit": "stack_logit",
                    "leaderboard_blend": "leaderboard_blend",
                }
            )[["SK_ID_CURR", "leaderboard_blend", "stack_logit", "lightgbm", "xgboost", "catboost"]]
        )
    if test_path.exists():
        test = pd.read_csv(test_path)
        parts.append(
            test.rename(
                columns={
                    "lightgbm_gbdt_pred": "lightgbm",
                    "xgboost_pred": "xgboost",
                    "catboost_pred": "catboost",
                }
            )[["SK_ID_CURR", "leaderboard_blend", "stack_logit", "lightgbm", "xgboost", "catboost"]]
        )
    if not parts:
        return pd.DataFrame(columns=["SK_ID_CURR", "leaderboard_blend", "stack_logit", "lightgbm", "xgboost", "catboost"])
    return pd.concat(parts, axis=0, ignore_index=True)


def _summary_payload() -> dict[str, object]:
    analysis = _load_json(OUTPUTS_DIR / "reports" / "analysis_baseline_metrics.json")
    target = _load_json(OUTPUTS_DIR / "reports" / "target_analysis.json")
    scorecard = _load_json(OUTPUTS_DIR / "reports" / "scorecard_metrics.json")
    leaderboard = _load_json(OUTPUTS_DIR / "reports" / "leaderboard_metrics.json")
    drift = _load_json(OUTPUTS_DIR / "reports" / "train_test_drift.json")
    comparison = _load_json(OUTPUTS_DIR / "reports" / "model_comparison.json")
    proxy_review = _load_json(OUTPUTS_DIR / "reports" / "leakage_and_proxy_review.json")
    feature_diag = pd.read_csv(OUTPUTS_DIR / "explainability" / "scorecard_feature_diagnostics.csv")
    bin_monitoring = pd.read_csv(OUTPUTS_DIR / "explainability" / "scorecard_bin_monitoring.csv")
    scorecard_predictions = pd.read_csv(OUTPUTS_DIR / "predictions" / "scorecard_predictions.csv")

    app_train = pd.read_csv(DATASET_DIR / "application_train.csv", usecols=PROFILE_COLUMNS)
    app_test = pd.read_csv(DATASET_DIR / "application_test.csv", usecols=[col for col in PROFILE_COLUMNS if col != "TARGET"])
    train = _enrich_application(app_train)
    test = _enrich_application(app_test)

    portfolio_snapshot = [
        {
            "dataset": "Train",
            "avg_income": _to_builtin(train["AMT_INCOME_TOTAL"].mean()),
            "avg_credit": _to_builtin(train["AMT_CREDIT"].mean()),
            "avg_annuity": _to_builtin(train["AMT_ANNUITY"].mean()),
        },
        {
            "dataset": "Test",
            "avg_income": _to_builtin(test["AMT_INCOME_TOTAL"].mean()),
            "avg_credit": _to_builtin(test["AMT_CREDIT"].mean()),
            "avg_annuity": _to_builtin(test["AMT_ANNUITY"].mean()),
        },
    ]

    target_distribution = [
        {"label": "Non-default", "value": _to_builtin((train["TARGET"] == 0).sum())},
        {"label": "Default", "value": _to_builtin((train["TARGET"] == 1).sum())},
    ]

    master = pd.read_pickle(OUTPUTS_DIR / "features" / "master_table.pkl")
    master_train = master[master["TARGET"].notna()].copy()
    master_train["TARGET"] = master_train["TARGET"].astype(int)
    for alias, source in NOTEBOOK_FEATURE_SOURCES.items():
        if source in master_train.columns:
            master_train[alias] = master_train[source]

    capacity_features = [
        feature
        for feature in [
            "payment_rate",
            "credit_income_ratio",
            "annuity_income_pct",
            "credit_annuity_ratio",
            "income_per_person",
        ]
        if feature in master_train.columns
    ]
    willingness_features = [
        feature
        for feature in [
            "ext_source_mean",
            "bureau_total_debt_ratio",
            "install_late_payment_rate",
            "previous_refused_count",
        ]
        if feature in master_train.columns
    ]

    capacity_ladders = []
    for feature in capacity_features:
        ladder = _risk_ladder(master_train, feature)
        if ladder.empty:
            continue
        capacity_ladders.append(
            {
                "feature": feature,
                "display_name": DISPLAY_NAMES.get(feature, feature),
                "points": _series_points(ladder, "bucket", "default_rate", ["count"]),
            }
        )

    willingness_ladders = []
    for feature in willingness_features:
        ladder = _risk_ladder(master_train, feature)
        if ladder.empty:
            continue
        willingness_ladders.append(
            {
                "feature": feature,
                "display_name": DISPLAY_NAMES.get(feature, feature),
                "points": _series_points(ladder, "bucket", "default_rate", ["count"]),
            }
        )

    previous = pd.read_csv(
        DATASET_DIR / "previous_application.csv",
        usecols=["SK_ID_PREV", "SK_ID_CURR", "NAME_CONTRACT_STATUS", "DAYS_DECISION"],
    )
    installments = pd.read_csv(
        DATASET_DIR / "installments_payments.csv",
        usecols=["SK_ID_PREV", "SK_ID_CURR", "DAYS_INSTALMENT", "DAYS_ENTRY_PAYMENT", "NUM_INSTALMENT_NUMBER"],
    )
    installments["days_past_due"] = (installments["DAYS_ENTRY_PAYMENT"] - installments["DAYS_INSTALMENT"]).clip(lower=0)
    severe_dpd = (
        installments[installments["days_past_due"] >= 30]
        .groupby("SK_ID_PREV", as_index=True)["NUM_INSTALMENT_NUMBER"]
        .min()
        .rename("first_severe_dpd_mob")
    )
    loan_horizon = (
        installments.groupby("SK_ID_PREV", as_index=True)["NUM_INSTALMENT_NUMBER"]
        .max()
        .rename("last_observed_mob")
    )
    loan_perf = pd.concat([loan_horizon, severe_dpd], axis=1).reset_index()
    loan_perf["event_observed"] = loan_perf["first_severe_dpd_mob"].notna().astype(int)
    loan_perf["time_to_event"] = loan_perf["first_severe_dpd_mob"].fillna(loan_perf["last_observed_mob"]).astype(int)

    approved_prev = previous[previous["NAME_CONTRACT_STATUS"] == "Approved"].copy()
    approved_prev["decision_month"] = (-approved_prev["DAYS_DECISION"] // 30).astype(int)
    approved_prev = approved_prev[approved_prev["decision_month"].between(1, 12)]
    approved_prev = approved_prev.merge(loan_perf, on="SK_ID_PREV", how="inner")

    vintage_rows = []
    for cohort in sorted(approved_prev["decision_month"].unique())[:8]:
        cohort_df = approved_prev[approved_prev["decision_month"] == cohort]
        if len(cohort_df) < 200:
            continue
        for mob in range(1, 13):
            cumulative_default = ((cohort_df["event_observed"] == 1) & (cohort_df["time_to_event"] <= mob)).mean()
            vintage_rows.append(
                {
                    "cohort": f"M-{cohort}",
                    "month_on_book": mob,
                    "cumulative_default_rate": cumulative_default,
                    "loan_count": len(cohort_df),
                }
            )
    vintage_df = pd.DataFrame(vintage_rows)
    vintage_curves = []
    if not vintage_df.empty:
        for cohort, cohort_df in vintage_df.groupby("cohort", observed=True):
            vintage_curves.append(
                {
                    "cohort": cohort,
                    "loan_count": _to_builtin(cohort_df["loan_count"].iloc[0]),
                    "points": _series_points(cohort_df, "month_on_book", "cumulative_default_rate"),
                }
            )

    survival_input = approved_prev.copy()
    survival_input["duration_12m"] = survival_input["time_to_event"].clip(upper=12)
    survival_input["event_12m"] = (
        (survival_input["event_observed"] == 1) & (survival_input["time_to_event"] <= 12)
    ).astype(int)
    km = _kaplan_meier_curve(survival_input["duration_12m"], survival_input["event_12m"], max_time=12)

    special_value_summary = [
        {
            "item": "DAYS_EMPLOYED == 365243 sentinel",
            "value": _to_builtin((app_train["DAYS_EMPLOYED"] == 365243).sum()),
            "kind": "count",
        },
        {
            "item": "EXT_SOURCE_1 missing share",
            "value": _to_builtin(app_train["EXT_SOURCE_1"].isna().mean()),
            "kind": "percent",
        },
        {
            "item": "EXT_SOURCE_2 missing share",
            "value": _to_builtin(app_train["EXT_SOURCE_2"].isna().mean()),
            "kind": "percent",
        },
        {
            "item": "EXT_SOURCE_3 missing share",
            "value": _to_builtin(app_train["EXT_SOURCE_3"].isna().mean()),
            "kind": "percent",
        },
        {
            "item": "AMT_INCOME_TOTAL p99",
            "value": _to_builtin(app_train["AMT_INCOME_TOTAL"].quantile(0.99)),
            "kind": "currency",
        },
        {
            "item": "AMT_CREDIT p99",
            "value": _to_builtin(app_train["AMT_CREDIT"].quantile(0.99)),
            "kind": "currency",
        },
    ]

    missing_top = (
        app_train.isna()
        .mean()
        .sort_values(ascending=False)
        .head(12)
        .rename("missing_fraction")
        .reset_index()
        .rename(columns={"index": "feature"})
    )

    featured_ids = scorecard_predictions.sort_values("scorecard_probability", ascending=False)

    top_risk = featured_ids[featured_ids["dataset_split"] == "train"].head(3)["SK_ID_CURR"].astype(int).tolist()
    lowest_risk = (
        featured_ids[featured_ids["dataset_split"] == "train"]
        .sort_values("scorecard_probability", ascending=True)
        .head(3)["SK_ID_CURR"]
        .astype(int)
        .tolist()
    )
    sample_test = featured_ids[featured_ids["dataset_split"] == "test"].head(3)["SK_ID_CURR"].astype(int).tolist()

    scorecard_calibration = _calibration_summary(scorecard.get("calibration_bins", []))
    decile_summary = _score_decile_summary(scorecard_predictions, app_train)
    strategy = _strategy_payload(scorecard, leaderboard, feature_diag, vintage_curves, decile_summary)
    governance = _governance_payload(proxy_review, feature_diag)

    comparison_payload = {}
    for key, value in comparison.items():
        candidate = value.get("blend", value) if isinstance(value, dict) else {}
        comparison_payload[key] = {
            "roc_auc": _to_builtin(candidate.get("roc_auc")),
            "pr_auc": _to_builtin(candidate.get("pr_auc")),
            "ks": _to_builtin(candidate.get("ks")),
            "brier": _to_builtin(candidate.get("brier")),
        }
    if "leaderboard_ensemble" in comparison_payload:
        comparison_payload["leaderboard_ensemble"]["roc_auc"] = _to_builtin(
            comparison_payload["leaderboard_ensemble"]["roc_auc"] or leaderboard.get("blend", {}).get("roc_auc")
        )
        comparison_payload["leaderboard_ensemble"]["pr_auc"] = _to_builtin(
            comparison_payload["leaderboard_ensemble"]["pr_auc"] or leaderboard.get("blend", {}).get("pr_auc")
        )
        comparison_payload["leaderboard_ensemble"]["ks"] = _to_builtin(
            comparison_payload["leaderboard_ensemble"]["ks"] or leaderboard.get("blend", {}).get("ks")
        )
        comparison_payload["leaderboard_ensemble"]["brier"] = _to_builtin(
            comparison_payload["leaderboard_ensemble"]["brier"] or leaderboard.get("blend", {}).get("brier")
        )

    return {
        "headline": {
            "title": "Consumer Lending Risk Case Study",
            "subtitle": "A public-dataset lending book reframed around origination policy, monitoring triggers, calibration, and borrower-level traceability.",
        },
        "portfolio": {
            "train_rows": int(target["target_summary"]["row_count"]),
            "default_rate": _to_builtin(target["target_summary"]["default_rate"]),
        },
        "analysis": {
            "roc_auc": _to_builtin(analysis["roc_auc"]),
            "pr_auc": _to_builtin(analysis["pr_auc"]),
            "ks": _to_builtin(analysis["ks"]),
            "top_numeric_predictors": target["top_numeric_predictors"][:8],
        },
        "analysis_plots": {
            "target_distribution": target_distribution,
            "portfolio_profile": portfolio_snapshot,
            "capacity_ladders": capacity_ladders,
            "willingness_ladders": willingness_ladders,
            "vintage_curves": vintage_curves,
            "survival_curve": _series_points(km, "month_on_book", "survival_probability", ["n_at_risk", "events"]),
            "special_values": special_value_summary,
            "missing_top": missing_top.to_dict(orient="records"),
        },
        "scorecard": {
            "roc_auc": _to_builtin(scorecard["roc_auc"]),
            "pr_auc": _to_builtin(scorecard["pr_auc"]),
            "ks": _to_builtin(scorecard["ks"]),
            "brier": _to_builtin(scorecard.get("brier")),
            "selected_features": scorecard["selected_features"],
            "selected_feature_count": len(scorecard.get("selected_features", [])),
            "monitoring_sample_rows": scorecard.get("monitoring_sample_rows", {}),
            "score_range": scorecard["score_range"],
            "top_iv": feature_diag.sort_values("iv", ascending=False).head(8).to_dict(orient="records"),
            "top_psi": feature_diag.sort_values("psi_train_test", ascending=False).head(8).to_dict(orient="records"),
            "bin_monitoring": bin_monitoring.sort_values("psi_component", ascending=False).head(24).to_dict(orient="records"),
            "calibration_bins": scorecard_calibration["bins"],
            "calibration_mean_absolute_gap": scorecard_calibration["mean_absolute_gap"],
            "calibration_max_gap": scorecard_calibration["max_absolute_gap"],
            "worst_calibration_bin": scorecard_calibration["max_gap_bin"],
            "score_deciles": decile_summary["deciles"],
            "expected_loss_assumption": decile_summary["assumptions"],
        },
        "leaderboard": {
            "model_names": leaderboard["model_names"],
            "feature_count": int(leaderboard["feature_count"]),
            "sample_rows": int(leaderboard["sample_rows"]),
            "blend_auc": _to_builtin(leaderboard["blend"]["roc_auc"]),
            "base_blend_auc": _to_builtin(leaderboard["base_blend"]["roc_auc"]),
            "blend_brier": _to_builtin(leaderboard["blend"]["brier"]),
        },
        "drift": {
            "adversarial_auc": _to_builtin(drift["adversarial_auc"]),
            "top_drift_features": drift["top_drift_features"][:10],
        },
        "strategy": strategy,
        "governance": governance,
        "model_comparison": comparison_payload,
        "featured_borrowers": {
            "highest_scorecard_risk_train": top_risk,
            "lowest_scorecard_risk_train": lowest_risk,
            "sample_test_ids": sample_test,
        },
    }


def _build_lookup_database() -> None:
    print("[web] loading source tables")
    app_train = pd.read_csv(DATASET_DIR / "application_train.csv", usecols=PROFILE_COLUMNS)
    app_train["dataset_split"] = "train"
    app_test = pd.read_csv(DATASET_DIR / "application_test.csv", usecols=[col for col in PROFILE_COLUMNS if col != "TARGET"])
    app_test["TARGET"] = np.nan
    app_test["dataset_split"] = "test"
    applications = pd.concat([app_train, app_test], axis=0, ignore_index=True)

    bureau = pd.read_csv(
        DATASET_DIR / "bureau.csv",
        usecols=["SK_ID_CURR", "CREDIT_ACTIVE", "AMT_CREDIT_SUM", "AMT_CREDIT_SUM_DEBT", "AMT_CREDIT_SUM_OVERDUE"],
    )
    bureau_summary = (
        bureau.assign(active=(bureau["CREDIT_ACTIVE"] == "Active").astype(int))
        .groupby("SK_ID_CURR", as_index=False)
        .agg(
            bureau_rows=("SK_ID_CURR", "size"),
            active_loans=("active", "sum"),
            bureau_total_credit=("AMT_CREDIT_SUM", "sum"),
            bureau_total_debt=("AMT_CREDIT_SUM_DEBT", "sum"),
            bureau_total_overdue=("AMT_CREDIT_SUM_OVERDUE", "sum"),
        )
    )

    previous = pd.read_csv(
        DATASET_DIR / "previous_application.csv",
        usecols=["SK_ID_CURR", "NAME_CONTRACT_STATUS"],
    )
    previous_summary = (
        previous.assign(
            approved=(previous["NAME_CONTRACT_STATUS"] == "Approved").astype(int),
            refused=(previous["NAME_CONTRACT_STATUS"] == "Refused").astype(int),
        )
        .groupby("SK_ID_CURR", as_index=False)
        .agg(
            previous_rows=("SK_ID_CURR", "size"),
            previous_approved=("approved", "sum"),
            previous_refused=("refused", "sum"),
        )
    )

    installments = pd.read_csv(
        DATASET_DIR / "installments_payments.csv",
        usecols=["SK_ID_CURR", "DAYS_INSTALMENT", "DAYS_ENTRY_PAYMENT", "AMT_PAYMENT", "AMT_INSTALMENT"],
    )
    installments["days_past_due"] = (installments["DAYS_ENTRY_PAYMENT"] - installments["DAYS_INSTALMENT"]).clip(lower=0)
    installments_summary = (
        installments.assign(late=(installments["days_past_due"] > 0).astype(int))
        .groupby("SK_ID_CURR", as_index=False)
        .agg(
            installment_rows=("SK_ID_CURR", "size"),
            installment_late_rate=("late", "mean"),
            installment_max_dpd=("days_past_due", "max"),
            installment_avg_payment=("AMT_PAYMENT", "mean"),
            installment_avg_amount=("AMT_INSTALMENT", "mean"),
        )
    )

    scorecard_predictions = pd.read_csv(OUTPUTS_DIR / "predictions" / "scorecard_predictions.csv")
    reason_codes = pd.read_csv(OUTPUTS_DIR / "explainability" / "reason_codes.csv")
    scorecard_bins = pd.read_csv(OUTPUTS_DIR / "explainability" / "scorecard_bins.csv")
    leaderboard = _leaderboard_frame()
    scorecard_metrics = _load_json(OUTPUTS_DIR / "reports" / "scorecard_metrics.json")

    selected_features = scorecard_metrics["selected_features"]
    reason_feature_pool = set(scorecard_bins["feature"].astype(str).unique())

    print("[web] loading compact master feature slice")
    master = pd.read_pickle(OUTPUTS_DIR / "features" / "master_table.pkl")
    needed_master_cols = ["SK_ID_CURR", *sorted(reason_feature_pool)]
    needed_master_cols = [col for col in needed_master_cols if col in master.columns]
    master = master[needed_master_cols].copy()
    master = master.rename(columns={col: f"F__{col}" for col in master.columns if col != "SK_ID_CURR"})

    base = (
        applications.merge(bureau_summary, on="SK_ID_CURR", how="left")
        .merge(previous_summary, on="SK_ID_CURR", how="left")
        .merge(installments_summary, on="SK_ID_CURR", how="left")
        .merge(scorecard_predictions, on=["SK_ID_CURR", "TARGET", "dataset_split"], how="left")
        .merge(reason_codes, on="SK_ID_CURR", how="left")
        .merge(leaderboard, on="SK_ID_CURR", how="left")
        .merge(master, on="SK_ID_CURR", how="left")
    )

    numeric_fill_zero = [
        "bureau_rows",
        "active_loans",
        "bureau_total_credit",
        "bureau_total_debt",
        "bureau_total_overdue",
        "previous_rows",
        "previous_approved",
        "previous_refused",
        "installment_rows",
        "installment_late_rate",
        "installment_max_dpd",
        "installment_avg_payment",
        "installment_avg_amount",
    ]
    for column in numeric_fill_zero:
        if column in base.columns:
            base[column] = base[column].fillna(0)

    bin_map = {
        feature: frame.copy()
        for feature, frame in scorecard_bins.groupby("feature", observed=True)
    }

    if LOOKUP_DB.exists():
        LOOKUP_DB.unlink()
    if (DATA_DIR / "borrowers").exists():
        shutil.rmtree(DATA_DIR / "borrowers")

    print("[web] writing borrower lookup database")
    conn = sqlite3.connect(LOOKUP_DB)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE borrowers (
            id INTEGER PRIMARY KEY,
            split TEXT,
            target REAL,
            contract_type TEXT,
            income_type TEXT,
            family_status TEXT,
            housing_type TEXT,
            income_total REAL,
            credit_amount REAL,
            annuity_amount REAL,
            ext_source_2 REAL,
            bureau_rows REAL,
            active_loans REAL,
            previous_rows REAL,
            previous_approved REAL,
            previous_refused REAL,
            installment_rows REAL,
            installment_late_rate REAL,
            installment_max_dpd REAL,
            bureau_total_debt REAL,
            bureau_total_overdue REAL,
            scorecard_probability REAL,
            scorecard_score REAL,
            leaderboard_blend REAL,
            stack_logit REAL,
            reason1_feature TEXT,
            reason1_contribution REAL,
            reason1_raw_value TEXT,
            reason1_matched_bin TEXT,
            reason1_points REAL,
            reason1_bad_rate REAL,
            reason2_feature TEXT,
            reason2_contribution REAL,
            reason2_raw_value TEXT,
            reason2_matched_bin TEXT,
            reason2_points REAL,
            reason2_bad_rate REAL,
            reason3_feature TEXT,
            reason3_contribution REAL,
            reason3_raw_value TEXT,
            reason3_matched_bin TEXT,
            reason3_points REAL,
            reason3_bad_rate REAL
        )
        """
    )

    insert_sql = """
        INSERT INTO borrowers VALUES (
            ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
        )
    """
    batch: list[tuple[object, ...]] = []
    for row in base.itertuples(index=False):
        row_dict = row._asdict()
        reasons: list[object] = []
        for idx in range(1, 4):
            feature_name = row_dict.get(f"reason_code_{idx}")
            if not feature_name or pd.isna(feature_name):
                reasons.extend([None, None, None, None, None, None])
                continue
            raw_value = row_dict.get(f"F__{feature_name}")
            if raw_value is None:
                raw_value = row_dict.get(feature_name)
            matched = _match_bin(raw_value, bin_map.get(str(feature_name), pd.DataFrame()))
            reasons.extend(
                [
                    str(feature_name),
                    _to_builtin(row_dict.get(f"reason_contribution_{idx}")),
                    None if _to_builtin(raw_value) is None else str(_to_builtin(raw_value)),
                    None if matched is None else matched["label"],
                    None if matched is None else _to_builtin(matched.get("points")),
                    None if matched is None else _to_builtin(matched.get("bad_rate")),
                ]
            )

        batch.append(
            (
                int(row_dict["SK_ID_CURR"]),
                row_dict["dataset_split"],
                _to_builtin(row_dict.get("TARGET")),
                _to_builtin(row_dict.get("NAME_CONTRACT_TYPE")),
                _to_builtin(row_dict.get("NAME_INCOME_TYPE")),
                _to_builtin(row_dict.get("NAME_FAMILY_STATUS")),
                _to_builtin(row_dict.get("NAME_HOUSING_TYPE")),
                _to_builtin(row_dict.get("AMT_INCOME_TOTAL")),
                _to_builtin(row_dict.get("AMT_CREDIT")),
                _to_builtin(row_dict.get("AMT_ANNUITY")),
                _to_builtin(row_dict.get("EXT_SOURCE_2")),
                _to_builtin(row_dict.get("bureau_rows")),
                _to_builtin(row_dict.get("active_loans")),
                _to_builtin(row_dict.get("previous_rows")),
                _to_builtin(row_dict.get("previous_approved")),
                _to_builtin(row_dict.get("previous_refused")),
                _to_builtin(row_dict.get("installment_rows")),
                _to_builtin(row_dict.get("installment_late_rate")),
                _to_builtin(row_dict.get("installment_max_dpd")),
                _to_builtin(row_dict.get("bureau_total_debt")),
                _to_builtin(row_dict.get("bureau_total_overdue")),
                _to_builtin(row_dict.get("scorecard_probability")),
                _to_builtin(row_dict.get("scorecard_score")),
                _to_builtin(row_dict.get("leaderboard_blend")),
                _to_builtin(row_dict.get("stack_logit")),
                *reasons,
            )
        )

        if len(batch) >= 5000:
            cursor.executemany(insert_sql, batch)
            conn.commit()
            batch.clear()

    if batch:
        cursor.executemany(insert_sql, batch)
        conn.commit()

    cursor.execute("CREATE INDEX idx_borrowers_split ON borrowers(split)")
    conn.commit()
    conn.close()


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    summary = _summary_payload()
    (DATA_DIR / "summary.json").write_text(json.dumps(summary, separators=(",", ":")))
    _write_static_plots(summary)
    _build_lookup_database()
    _write_borrower_pages(summary)
    print("[web] bundle complete")


if __name__ == "__main__":
    main()

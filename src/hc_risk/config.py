from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class PipelineConfig:
    root_dir: Path = field(default_factory=lambda: Path(__file__).resolve().parents[2])
    dataset_dir: Path = field(init=False)
    outputs_dir: Path = field(init=False)
    random_state: int = 42
    n_folds: int = 5
    explainable_top_features: int = 24
    explainable_min_bin_size: float = 0.05
    explainable_bootstrap_rounds: int = 60
    explainable_permutation_rounds: int = 60
    explainable_monitoring_sample_rows: int | None = 20000
    explainable_pdo: float = 20.0
    explainable_base_score: float = 600.0
    explainable_base_odds: float = 50.0
    leaderboard_tuning_trials: int = 10
    analysis_baseline_sample_rows: int | None = None
    scorecard_sample_rows: int | None = None
    leaderboard_sample_rows: int | None = None

    def __post_init__(self) -> None:
        self.dataset_dir = self.root_dir / "dataset"
        self.outputs_dir = self.root_dir / "outputs"

    @property
    def artifacts_dir(self) -> Path:
        return self.outputs_dir / "artifacts"

    @property
    def reports_dir(self) -> Path:
        return self.outputs_dir / "reports"

    @property
    def features_dir(self) -> Path:
        return self.outputs_dir / "features"

    @property
    def predictions_dir(self) -> Path:
        return self.outputs_dir / "predictions"

    @property
    def explainability_dir(self) -> Path:
        return self.outputs_dir / "explainability"

    @property
    def submission_path(self) -> Path:
        return self.outputs_dir / "submission.csv"

    def ensure_directories(self) -> None:
        for path in (
            self.outputs_dir,
            self.artifacts_dir,
            self.reports_dir,
            self.features_dir,
            self.predictions_dir,
            self.explainability_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


TABLE_FILENAMES = {
    "application_train": "application_train.csv",
    "application_test": "application_test.csv",
    "bureau": "bureau.csv",
    "bureau_balance": "bureau_balance.csv",
    "previous_application": "previous_application.csv",
    "pos_cash_balance": "POS_CASH_balance.csv",
    "credit_card_balance": "credit_card_balance.csv",
    "installments_payments": "installments_payments.csv",
    "column_descriptions": "HomeCredit_columns_description.csv",
    "sample_submission": "sample_submission.csv",
}

TABLE_GRAINS = {
    "application_train": ["SK_ID_CURR"],
    "application_test": ["SK_ID_CURR"],
    "bureau": ["SK_ID_BUREAU"],
    "bureau_balance": ["SK_ID_BUREAU", "MONTHS_BALANCE"],
    "previous_application": ["SK_ID_PREV"],
    "pos_cash_balance": ["SK_ID_PREV", "MONTHS_BALANCE"],
    "credit_card_balance": ["SK_ID_PREV", "MONTHS_BALANCE"],
    "installments_payments": [
        "SK_ID_PREV",
        "NUM_INSTALMENT_VERSION",
        "NUM_INSTALMENT_NUMBER",
    ],
}

EXPLAINABLE_CATEGORICALS = [
    "CODE_GENDER",
    "FLAG_OWN_CAR",
    "FLAG_OWN_REALTY",
    "NAME_INCOME_TYPE",
    "NAME_EDUCATION_TYPE",
    "NAME_FAMILY_STATUS",
    "NAME_HOUSING_TYPE",
]

from __future__ import annotations

import argparse
from pprint import pprint

from .analysis import run_analysis
from .config import PipelineConfig
from .leaderboard import run_leaderboard
from .scorecard import run_explainable


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Home Credit default risk pipeline")
    parser.add_argument(
        "stage",
        choices=["analysis", "explainable", "leaderboard", "full-run"],
        help="Pipeline stage to execute",
    )
    parser.add_argument("--force", action="store_true", help="Rebuild cached artifacts")
    parser.add_argument(
        "--tuning-trials",
        type=int,
        default=10,
        help="Random search trials for each leaderboard model",
    )
    parser.add_argument(
        "--analysis-baseline-sample-rows",
        type=int,
        default=None,
        help="Optional stratified sample size for the analysis baseline CV",
    )
    parser.add_argument(
        "--scorecard-sample-rows",
        type=int,
        default=None,
        help="Optional stratified sample size for the explainable scorecard stage",
    )
    parser.add_argument(
        "--leaderboard-sample-rows",
        type=int,
        default=None,
        help="Optional stratified sample size for the leaderboard training stage",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    config = PipelineConfig(
        leaderboard_tuning_trials=args.tuning_trials,
        analysis_baseline_sample_rows=args.analysis_baseline_sample_rows,
        scorecard_sample_rows=args.scorecard_sample_rows,
        leaderboard_sample_rows=args.leaderboard_sample_rows,
    )
    if args.stage == "analysis":
        result = run_analysis(config, force=args.force)
        pprint(
            {
                "outputs_dir": str(config.outputs_dir),
                "train_rows": int((result.master_bundle.master["dataset_split"] == "train").sum()),
                "test_rows": int((result.master_bundle.master["dataset_split"] == "test").sum()),
            }
        )
        return

    if args.stage == "explainable":
        pprint(run_explainable(config, force=args.force))
        return

    if args.stage == "leaderboard":
        pprint(run_leaderboard(config, force=args.force))
        return

    analysis_artifacts = run_analysis(config, force=args.force)
    pprint(run_explainable(config, force=args.force, analysis_artifacts=analysis_artifacts))
    pprint(run_leaderboard(config, force=args.force, analysis_artifacts=analysis_artifacts))


if __name__ == "__main__":
    main()

# Consumer Lending Risk Case Study

This repo turns the Home Credit public dataset into a consumer lending risk
case study focused on:

- origination policy bands (`approve / manual review / decline`)
- explainable scorecards and borrower-level reason codes
- calibration and bad-rate-by-decile review
- portfolio monitoring through PSI, vintage curves, and survival views
- governance through proxy-risk exclusions and missingness controls

Live site:

- portfolio home: [https://hc-risk-eight.vercel.app](https://hc-risk-eight.vercel.app)
- full analysis: [https://hc-risk-eight.vercel.app/analysis](https://hc-risk-eight.vercel.app/analysis)
- sample borrower trace: [https://hc-risk-eight.vercel.app/borrowers/182619](https://hc-risk-eight.vercel.app/borrowers/182619)

The web surfaces are split on purpose:

- `/` is a hiring-oriented portfolio summary
- `/analysis` is the full interactive risk review
- `/borrowers/<id>` opens prepared borrower traces

## Lifecycle framing

The project is organized around the lending lifecycle rather than around a
competition workflow.

1. `pre-loan`: application, bureau, and prior-loan features for origination
   ranking and reviewable policy bands
2. `in-loan`: capacity-vs-willingness framing, PSI, vintage curves, and
   survival analysis for portfolio monitoring
3. `post-loan`: borrower traces, late-payment behavior, and refusal history for
   collections or manual review discussion

## Pipeline stages

Three linked stages are implemented around the dataset in `dataset/`:

1. `analysis`: audit, target analysis, baseline CV, and train/test drift checks
2. `explainable`: WoE scorecard with logistic regression, points, and reason codes
3. `leaderboard`: wide feature factory, ensemble benchmark, and OOF predictions

Run from the repo root:

```bash
PYTHONPATH=src python3 -m hc_risk.cli analysis
PYTHONPATH=src python3 -m hc_risk.cli explainable
PYTHONPATH=src python3 -m hc_risk.cli leaderboard
PYTHONPATH=src python3 -m hc_risk.cli full-run
python3 scripts/build_web_bundle.py
```

Artifacts are written to `outputs/` and the web bundle is refreshed into
`data/` and `borrowers/`.

Optional packages (`lightgbm`, `xgboost`, `catboost`, `optuna`, `shap`) are
used automatically if installed. Otherwise the leaderboard stage falls back to
sklearn-based ensembles.

## Supporting artifacts

The repo includes a few non-code artifacts to make the case study read more
like risk operations work:

- `docs/risk-memo.md`: short risk memo with lifecycle and policy framing
- `sql/vintage_monitor.sql`: cohort seasoning / early-delinquency monitor
- `sql/portfolio_kri.sql`: key risk indicator query for approvals, exposure,
  PSI, and calibration-facing metrics
- `infra/architecture.md`: architecture note for ingestion, feature jobs,
  score generation, monitoring, and borrower traces

## Fraud extension

The main case study is credit-risk focused, but the repo also calls out the
next fraud overlay a rotating team would care about:

- application velocity
- identity consistency checks
- bureau inquiry bursts
- device and session anomalies

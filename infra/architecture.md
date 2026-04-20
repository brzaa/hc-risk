# Architecture Note

## Purpose

This repo is deliberately presented like a small lending-risk stack instead of a
single notebook. The architecture is simple, but each layer maps to a real risk
team concern.

## Layers

### 1. Source data

- application data
- bureau history
- previous applications
- installment behavior
- POS and revolving credit tables

These are joined into a borrower-level master table plus a wider challenger
matrix.

### 2. Feature and analysis layer

- `src/hc_risk/features.py` builds the borrower-level feature base
- `src/hc_risk/analysis.py` writes audit, target analysis, drift, and proxy-review outputs
- `outputs/reports/` stores monitoring-ready JSON artifacts

The key design choice is to keep analysis artifacts reusable by both the web UI
and downstream review docs.

### 3. Scoring layer

- `src/hc_risk/scorecard.py` builds the WoE scorecard
- reason codes, bins, PSI diagnostics, and calibration outputs are written into
  `outputs/explainability/`
- `src/hc_risk/leaderboard.py` trains the benchmark challenger stack

The explainable scorecard is the operating surface. The ensemble is a challenger
and benchmark.

### 4. Presentation layer

- `scripts/build_web_bundle.py` compiles summary JSON, plots, borrower pages,
  and the lookup database
- `index.html` is the hiring-facing portfolio surface
- `analysis.html` is the deeper interactive review
- `borrowers/<id>.html` provides borrower-level drilldowns

## Monitoring loop

The intended operating loop is:

1. score borrowers with the explainable model
2. monitor PSI, vintage, survival, calibration, and bad rate by decile
3. inspect borrower traces for manual review or collections discussion
4. re-bin, challenge, or refresh policy when thresholds are breached

## Fraud extension

If extended for a blended credit/fraud team, add an upstream fraud decision
layer before approval:

- application velocity service
- identity consistency checks
- bureau inquiry burst features
- device / IP / session anomaly signals

That fraud layer should feed into the same borrower trace surface so reviewers
can inspect both credit and fraud evidence in one place.

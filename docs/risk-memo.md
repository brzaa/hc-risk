# Risk Memo

## Objective

Use the Home Credit public dataset as a proxy consumer lending book and show how
an explainable scorecard can support:

- origination policy
- portfolio monitoring
- borrower-level review

The intent is not to present a Kaggle submission story. The intent is to show
what a practical lending-risk stack looks like when translated into policy and
governance language.

## Lifecycle view

### Pre-loan

- rank applications with an explainable scorecard
- map scores into `approve / manual review / decline`
- keep top reason codes available for analyst review or adverse-action style explanation

### In-loan

- monitor PSI on scorecard features
- track cohort seasoning through vintage curves
- watch calibration and bad rate by score decile

### Post-loan

- use borrower traces to inspect late-payment history, refusal patterns, and
  bureau stress
- translate stressed profiles into collections or hardship-review discussion

## Policy stance

- `Approve`: lower-risk score bands, subject to hard-policy checks outside the model
- `Manual review`: mid-risk bands, missing-document review, or affordability verification
- `Decline`: highest-risk bands unless a challenger or analyst override justifies a second look

## Monitoring triggers

- PSI watch at `0.10`, escalation at `0.25`
- recent vintage deterioration review when latest cohorts season materially worse than the trailing reference book
- challenger launch only when benchmark uplift is material and calibration does not worsen

## Governance

- reason codes come from the same bins used for scoring
- occupation, organization, application-time, and sparse document features are
  excluded from the policy-facing scorecard
- missingness is treated as portfolio structure, not just preprocessing noise
- `DAYS_EMPLOYED = 365243` stays visible as a sentinel anomaly

## Fraud extension

If this were extended for a rotating credit/fraud team, the next layer would
add:

- application velocity
- identity consistency checks
- bureau inquiry bursts
- device and session anomalies

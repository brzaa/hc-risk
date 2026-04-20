-- Portfolio KRI snapshot for policy and monitoring review.
-- Uses warehouse-style mart tables instead of the raw Kaggle files directly.

WITH current_scores AS (
    SELECT
        score_date,
        borrower_id,
        decision_band,
        score_decile,
        score_probability,
        expected_loss_proxy,
        approved_amount
    FROM risk.daily_score_snapshot
    WHERE score_date = CURRENT_DATE - INTERVAL '1 day'
),
portfolio_perf AS (
    SELECT
        perf.borrower_id,
        perf.booked_30dpd_flag,
        perf.booked_90dpd_flag,
        perf.current_dpd,
        perf.outstanding_principal
    FROM risk.portfolio_performance_daily AS perf
    WHERE perf.snapshot_date = CURRENT_DATE - INTERVAL '1 day'
),
psi_watch AS (
    SELECT
        monitor.feature_name,
        monitor.psi_value,
        ROW_NUMBER() OVER (ORDER BY monitor.psi_value DESC) AS psi_rank
    FROM risk.scorecard_feature_monitor AS monitor
    WHERE monitor.snapshot_date = CURRENT_DATE - INTERVAL '1 day'
),
calibration_view AS (
    SELECT
        decile,
        AVG(predicted_pd) AS avg_predicted_pd,
        AVG(observed_bad_flag) AS observed_bad_rate
    FROM risk.score_decile_monitor
    WHERE snapshot_date >= CURRENT_DATE - INTERVAL '30 days'
    GROUP BY decile
)
SELECT
    scores.score_date,
    scores.decision_band,
    COUNT(*) AS borrowers,
    AVG(scores.score_probability) AS avg_score_probability,
    AVG(scores.expected_loss_proxy) AS avg_expected_loss_proxy,
    SUM(scores.expected_loss_proxy) AS total_expected_loss_proxy,
    AVG(scores.approved_amount) AS avg_approved_amount,
    SUM(scores.approved_amount) AS booked_exposure,
    AVG(COALESCE(perf.booked_30dpd_flag, 0)) AS booked_30dpd_rate,
    AVG(COALESCE(perf.booked_90dpd_flag, 0)) AS booked_90dpd_rate,
    AVG(COALESCE(perf.current_dpd, 0)) AS avg_current_dpd,
    MAX(CASE WHEN psi.psi_rank = 1 THEN psi.psi_value END) AS max_feature_psi,
    MAX(CASE WHEN psi.psi_rank = 1 THEN psi.feature_name END) AS max_psi_feature,
    AVG(CASE WHEN cal.decile = scores.score_decile THEN cal.avg_predicted_pd END) AS calibration_predicted_pd,
    AVG(CASE WHEN cal.decile = scores.score_decile THEN cal.observed_bad_rate END) AS calibration_observed_bad_rate
FROM current_scores AS scores
LEFT JOIN portfolio_perf AS perf
    ON scores.borrower_id = perf.borrower_id
LEFT JOIN psi_watch AS psi
    ON psi.psi_rank = 1
LEFT JOIN calibration_view AS cal
    ON cal.decile = scores.score_decile
GROUP BY
    scores.score_date,
    scores.decision_band
ORDER BY
    CASE scores.decision_band
        WHEN 'Approve' THEN 1
        WHEN 'Manual Review' THEN 2
        WHEN 'Decline' THEN 3
        ELSE 4
    END;

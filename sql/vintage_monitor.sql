-- Vintage monitor for a warehouse-style lending stack.
-- Assumes origination and repayment events have already been normalized into
-- borrower / loan level tables.

WITH booked_loans AS (
    SELECT
        loan_id,
        borrower_id,
        DATE_TRUNC('month', booked_at) AS booked_month,
        booked_at,
        approved_amount
    FROM risk.loan_originations
    WHERE booked_at >= CURRENT_DATE - INTERVAL '18 months'
),
first_severe_dpd AS (
    SELECT
        repayment.loan_id,
        MIN(repayment.mob) AS first_30dpd_mob
    FROM risk.repayment_events AS repayment
    WHERE repayment.days_past_due >= 30
    GROUP BY repayment.loan_id
),
loan_perf AS (
    SELECT
        loans.loan_id,
        loans.borrower_id,
        loans.booked_month,
        loans.approved_amount,
        COALESCE(events.first_30dpd_mob, 999) AS first_30dpd_mob,
        CASE WHEN events.first_30dpd_mob IS NULL THEN 0 ELSE 1 END AS severe_dpd_event
    FROM booked_loans AS loans
    LEFT JOIN first_severe_dpd AS events
        ON loans.loan_id = events.loan_id
),
mob_curve AS (
    SELECT
        perf.booked_month,
        mob.mob,
        COUNT(*) AS loans_in_cohort,
        AVG(
            CASE
                WHEN perf.severe_dpd_event = 1
                     AND perf.first_30dpd_mob <= mob.mob THEN 1.0
                ELSE 0.0
            END
        ) AS cumulative_30dpd_rate
    FROM loan_perf AS perf
    CROSS JOIN (
        SELECT 1 AS mob UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4 UNION ALL
        SELECT 5 UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL SELECT 8 UNION ALL
        SELECT 9 UNION ALL SELECT 10 UNION ALL SELECT 11 UNION ALL SELECT 12
    ) AS mob
    GROUP BY perf.booked_month, mob.mob
)
SELECT
    booked_month,
    mob,
    loans_in_cohort,
    cumulative_30dpd_rate,
    LAG(cumulative_30dpd_rate) OVER (
        PARTITION BY booked_month
        ORDER BY mob
    ) AS prior_mob_rate,
    AVG(cumulative_30dpd_rate) OVER (
        PARTITION BY booked_month
        ORDER BY mob
        ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
    ) AS trailing_3mob_avg
FROM mob_curve
ORDER BY booked_month DESC, mob;

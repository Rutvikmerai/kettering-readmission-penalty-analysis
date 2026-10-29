-- =====================================================================
-- 02_analysis.sql
-- Ohio Readmissions Project: which conditions drive Kettering Health's
-- excess readmissions?
--
-- Data: data/clean/hrrp_clean.csv (FY 2026 HRRP, discharges 7/2021-6/2024)
-- Tool: DuckDB. Run from the project folder.
--
-- Key terms:
--   ERR (Excess Readmission Ratio) = predicted rate / expected rate.
--     Above 1.0 = more readmissions than expected for that hospital's patients.
--   Excess readmissions (estimated) = discharges x (predicted rate - expected rate) / 100.
--     A count of "extra" readmissions. Rates in the file are percentages.
-- =====================================================================


-- ---------------------------------------------------------------------
-- Q0. Load the clean data into a table
-- ---------------------------------------------------------------------
CREATE OR REPLACE TABLE hrrp AS
SELECT *
FROM read_csv_auto('data/clean/hrrp_clean.csv', types = {'facility_id': 'VARCHAR'});


-- ---------------------------------------------------------------------
-- Q1. Sanity check: row counts should match the cleaning script output
--     Expected: Ohio 708 rows / 481 valid ERR, Kettering 42 / 27
-- ---------------------------------------------------------------------
SELECT
    'Ohio'      AS scope, COUNT(*) AS total_rows, SUM(CASE WHEN err_valid THEN 1 ELSE 0 END) AS valid_err_rows
FROM hrrp WHERE state = 'OH'
UNION ALL
SELECT
    'Kettering', COUNT(*), SUM(CASE WHEN err_valid THEN 1 ELSE 0 END)
FROM hrrp WHERE health_system = 'Kettering Health';


-- ---------------------------------------------------------------------
-- Q2. Kettering scorecard: every hospital x condition with a valid ERR,
--     worst first
-- ---------------------------------------------------------------------
SELECT
    facility_name,
    condition,
    discharges,
    ROUND(err, 4)                                        AS err,
    CASE WHEN err > 1 THEN 'Above expected' ELSE 'At/below expected' END AS status,
    ROUND(discharges * (predicted_rate - expected_rate) / 100, 1) AS est_excess_readmissions
FROM hrrp
WHERE health_system = 'Kettering Health'
  AND err_valid
ORDER BY err DESC;


-- ---------------------------------------------------------------------
-- Q3. Condition summary for Kettering (system level)
--     This is the core question: which conditions drive excess readmissions?
--     Note: est_excess only sums rows where discharges are reported
--     (rows with "Too Few to Report" have no discharge count).
-- ---------------------------------------------------------------------
SELECT
    condition,
    COUNT(*)                                             AS hospitals_measured,
    SUM(CASE WHEN err > 1 THEN 1 ELSE 0 END)             AS hospitals_above_1,
    SUM(discharges)                                      AS total_discharges,
    ROUND(SUM(err * discharges) / SUM(discharges), 4)    AS discharge_weighted_err,
    ROUND(SUM(discharges * (predicted_rate - expected_rate) / 100), 1) AS est_excess_readmissions
FROM hrrp
WHERE health_system = 'Kettering Health'
  AND err_valid
GROUP BY condition
ORDER BY est_excess_readmissions DESC;


-- ---------------------------------------------------------------------
-- Q4. Benchmarks: Kettering vs. Ohio vs. national median ERR by condition
--     Note: CMS actually compares each hospital to the median of its
--     PEER GROUP (based on dual-eligible share). Peer group is not in this
--     file, so national and Ohio medians are used as a proxy for now.
-- ---------------------------------------------------------------------
WITH benchmarks AS (
    SELECT
        condition,
        MEDIAN(err)                                           AS national_median,
        MEDIAN(CASE WHEN state = 'OH' THEN err END)           AS ohio_median,
        MEDIAN(CASE WHEN health_system = 'Kettering Health' THEN err END) AS kettering_median
    FROM hrrp
    WHERE err_valid
    GROUP BY condition
)
SELECT
    condition,
    ROUND(kettering_median, 4) AS kettering_median,
    ROUND(ohio_median, 4)      AS ohio_median,
    ROUND(national_median, 4)  AS national_median,
    ROUND(kettering_median - national_median, 4) AS gap_vs_national
FROM benchmarks
ORDER BY gap_vs_national DESC;


-- ---------------------------------------------------------------------
-- Q5. Where does each Kettering hospital rank in Ohio for each condition?
--     Rank 1 = highest (worst) ERR in Ohio.
-- ---------------------------------------------------------------------
WITH ohio_ranked AS (
    SELECT
        facility_name,
        health_system,
        condition,
        err,
        RANK()  OVER (PARTITION BY condition ORDER BY err DESC) AS ohio_rank,
        COUNT(*) OVER (PARTITION BY condition)                  AS ohio_hospitals_measured
    FROM hrrp
    WHERE state = 'OH' AND err_valid
)
SELECT
    facility_name,
    condition,
    ROUND(err, 4) AS err,
    ohio_rank || ' of ' || ohio_hospitals_measured AS ohio_position
FROM ohio_ranked
WHERE health_system = 'Kettering Health'
ORDER BY condition, ohio_rank;


-- ---------------------------------------------------------------------
-- Q6. Hospital-level summary: which Kettering hospitals carry the most
--     excess readmissions overall?
-- ---------------------------------------------------------------------
SELECT
    facility_name,
    COUNT(*)                                       AS conditions_measured,
    SUM(CASE WHEN err > 1 THEN 1 ELSE 0 END)       AS conditions_above_1,
    ROUND(MAX(err), 4)                             AS worst_err,
    ROUND(SUM(discharges * (predicted_rate - expected_rate) / 100), 1) AS est_excess_readmissions
FROM hrrp
WHERE health_system = 'Kettering Health'
  AND err_valid
GROUP BY facility_name
ORDER BY est_excess_readmissions DESC;

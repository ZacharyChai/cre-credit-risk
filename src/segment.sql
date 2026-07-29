-- Risk segmentation: tiered refinance-risk flag (Low / Watch / Elevated / Acute).
--
-- Scope note on maturity timing: pool profiling established that 100% of this pool's
-- active real-estate balance already matures in 2027 -- there is no later-maturity,
-- has-runway cohort in this data to differentiate on. Every loan IS the wall; that's
-- a pool-level finding (stated in findings.md), not a per-loan scoring input here.
--
-- DSCR and rate gap are combined into ONE forward-looking metric, pro-forma DSCR --
-- what today's DSCR becomes if the loan refinances at the estimated takeout rate,
-- holding cash flow constant (an interest-only-equivalent approximation; real
-- amortization schedules would shift this slightly, noted in findings.md's limits):
--
--     pro_forma_dscr = reported_dscr * (current_coupon / takeout_rate)
--
-- Scoring DSCR and rate gap as two separate additive points double-counts the same
-- pool-wide rate exposure and washes out loan-level differentiation, since nearly
-- every loan in this pool feels some rate-driven payment shock. Combining them into
-- one ratio avoids that.
--
-- This is deliberately NOT computed as NOI / (current_balance * takeout_rate). For
-- pari-passu note pieces (is_pari_passu), current_balance in this table is only the
-- TRUST'S SLICE of the loan, while NOI/valuation are for the WHOLE property --
-- dividing whole-property NOI by a partial balance would understate risk for a large
-- share of the pool. Rescaling the ALREADY-RELIABLE reported DSCR by the rate ratio
-- sidesteps this: the balance term cancels out of the ratio entirely, so the
-- pari-passu distortion never enters the calculation. reported_dscr is confirmed
-- whole-loan-correct even for pari-passu pieces.
--
-- The four inputs that vary loan-to-loan and drive the tier:
--   Pro-forma DSCR   -- can the property cover debt service AT THE NEW RATE (primary driver)
--   LTV              -- would refinance proceeds cover the payoff balance (escalator)
--   Property type    -- office/lodging carry structural/cyclical risk beyond the above (escalator)
--
-- Base tier from pro-forma DSCR (bands a credit person would recognize -- 1.10x is
-- the common CREFC watchlist DSCR trigger):
--   < 1.00x        -> Acute   (cannot cover debt service at the new rate on cash flow alone)
--   1.00x - 1.10x  -> Elevated (covers, but thin/fragile)
--   1.10x - 1.25x  -> Watch    (adequate but tight)
--   >= 1.25x       -> Low      (healthy cushion)
--
-- One-step escalation (capped at Acute, and only ever +1 -- no double-escalation) if
-- EITHER: LTV > 80% (non-pari-passu; per-slice LTV is excluded here for the same
-- reason as above) OR property type is Office/Lodging (structural/cyclical overlay).

DROP VIEW IF EXISTS loan_risk_tiers;

CREATE VIEW loan_risk_tiers AS
WITH scored AS (
    SELECT
        deal_id,
        loan_id,
        property_name,
        property_type,
        state,
        current_balance,
        maturity_date,
        dscr AS dscr_current,
        dscr_basis,
        dscr * (coupon_pct / takeout_rate_pct) AS pro_forma_dscr,
        ltv,
        is_pari_passu,
        rate_gap_pct,
        loan_status,
        is_defeased,

        CASE
            WHEN dscr IS NULL OR takeout_rate_pct IS NULL THEN NULL
            WHEN dscr * (coupon_pct / takeout_rate_pct) < 1.00 THEN 3
            WHEN dscr * (coupon_pct / takeout_rate_pct) < 1.10 THEN 2
            WHEN dscr * (coupon_pct / takeout_rate_pct) < 1.25 THEN 1
            ELSE 0
        END AS base_tier_idx,

        CASE
            WHEN (NOT is_pari_passu AND ltv IS NOT NULL AND ltv > 0.80)
                OR property_type IN ('Office', 'Lodging')
            THEN 1 ELSE 0
        END AS escalate,

        TRIM(
            (CASE WHEN dscr IS NULL THEN 'dscr,' ELSE '' END) ||
            (CASE WHEN ltv IS NULL AND NOT is_pari_passu THEN 'ltv,' ELSE '' END) ||
            (CASE WHEN rate_gap_pct IS NULL THEN 'rate_gap,' ELSE '' END),
            ','
        ) AS missing_inputs

    FROM loans
    WHERE loan_status = 'active' AND NOT is_defeased
)
SELECT
    *,
    MIN(COALESCE(base_tier_idx, 1) + escalate, 3) AS risk_score,
    CASE MIN(COALESCE(base_tier_idx, 1) + escalate, 3)
        WHEN 3 THEN 'Acute'
        WHEN 2 THEN 'Elevated'
        WHEN 1 THEN 'Watch'
        ELSE 'Low'
    END AS risk_tier
FROM scored;

-- === Console output when run via `sqlite3 loans.db < segment.sql` ===============

.headers on
.mode column

SELECT '=== Every active real-estate loan is tiered (should equal 49) ===' AS section;
SELECT COUNT(*) AS loans_tiered FROM loan_risk_tiers;

SELECT '=== Share of pool balance by risk tier (THE headline table) ===' AS section;
SELECT
    risk_tier,
    COUNT(*) AS loans,
    printf('$%.1fM', SUM(current_balance) / 1e6) AS balance,
    printf('%.1f%%', 100.0 * SUM(current_balance) /
        (SELECT SUM(current_balance) FROM loan_risk_tiers)) AS pct_of_pool
FROM loan_risk_tiers
GROUP BY risk_tier
ORDER BY CASE risk_tier
    WHEN 'Acute' THEN 1 WHEN 'Elevated' THEN 2 WHEN 'Watch' THEN 3 ELSE 4
END;

SELECT '=== Acute loans, ranked by pro-forma DSCR (weakest first) ===' AS section;
SELECT
    deal_id, loan_id, property_type, state,
    printf('$%.1fM', current_balance / 1e6) AS balance,
    printf('%.2fx', dscr_current) AS dscr_today,
    printf('%.2fx', pro_forma_dscr) AS pro_forma_dscr,
    printf('%.0f%%', ltv * 100) AS ltv,
    printf('%.2f pts', rate_gap_pct) AS rate_gap,
    risk_tier
FROM loan_risk_tiers
WHERE risk_tier = 'Acute'
ORDER BY pro_forma_dscr ASC;

SELECT '=== Data-quality: loans tiered with a missing core input ===' AS section;
SELECT loan_id, property_type, missing_inputs
FROM loan_risk_tiers
WHERE missing_inputs != '';

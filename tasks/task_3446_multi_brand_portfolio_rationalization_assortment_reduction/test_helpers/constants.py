"""Domain constants — every value quoted from the PRD (§2, §3).

Only constants the PRD pins are declared here. Worked-example expected values
that tests assert verbatim are also pinned from the PRD text.
"""

# ─── Logical clock (PRD §2.4) ────────────────────────────────────────────────
# "At startup ... the logical clock reads exactly 2026-09-01T00:00:00Z"
CLOCK_START_ISO = "2026-09-01T00:00:00Z"
# PRD §2.5: created_at is "an ISO 8601 UTC timestamp with three fractional digits"
CLOCK_START_ISO_MILLIS = "2026-09-01T00:00:00.000Z"
# Decide at the clock default yields this sell-through deadline (+90 days).
DEFAULT_APPROVAL_DEADLINE_ISO = "2026-11-30T00:00:00Z"

# ─── Pagination (PRD §2.3) ───────────────────────────────────────────────────
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}

# ─── Rationalization composite score (PRD §3.2) ─────────────────────────────
THRESHOLDS = {
    # "a reference volume of 50,000 units per year (the constant 50000)"
    "VOLUME_REF_UNITS": 50000,
    # "a reference margin of 35 percent (the constant 0.35 expressed as a fraction)"
    "MARGIN_REF_PCT": 0.35,
    # "a reference share of 20 percent"
    "SHELF_SHARE_REF_PCT": 0.20,
    # "a reference brand scale of 10,000,000,000 cents (the constant 10000000000)"
    "BACKLASH_REV_REF_CENTS": 10000000000,
    # "0.5 plus 0.005 times the brand's private_label_share_pct"
    "PL_DAMPING_BASE": 0.5,
    "PL_DAMPING_SLOPE": 0.005,
    # "0.30 times volume_score, plus 0.25 times margin_score, plus 0.20 times
    #  shelf_resilience_score, plus 0.25 times backlash_resilience_score"
    "W_VOLUME": 0.30,
    "W_MARGIN": 0.25,
    "W_SHELF": 0.20,
    "W_BACKLASH": 0.25,
    # "a composite_score of at least 65 yields a recommendation of CUT"
    "CUT_RECOMMEND_THRESHOLD": 65,
    # "stamping the item's sell_through_deadline as the logical-clock timestamp
    #  of the decision plus exactly 90 days"
    "SELL_THROUGH_DAYS": 90,
    # "the months remaining are the days remaining divided by 30 days per
    #  penalty month and rounded up"
    "DAYS_PER_PENALTY_MONTH": 30,
    # "multiplied by the TSA's monthly_fee_cents and by the penalty rate of
    #  0.25 (25 percent)"
    "EARLY_TERM_PENALTY_RATE": 0.25,
    # "Under the SALVAGE variant (salvageable true), 20 percent of the cost is
    #  recovered, so the charge is 80 percent of the full cost"
    "SALVAGE_RECOVERY_PCT": 0.20,
    # "a year-3 reference revenue of 2,000,000,000 cents (the constant 2000000000)"
    "REVENUE_REF_CENTS_YEAR3": 2000000000,
    # "weighted at 0.40, plus the strategic_fit_score weighted at 0.60"
    "W_STRATEGIC_FIT": 0.60,
    "W_REVENUE": 0.40,
    # "a bonus of exactly 10 points is added after the rounding, and the result
    #  is then capped at 100"
    "CORE_PRIORITY_BONUS": 10,
    "PRIORITY_SCORE_CAP": 100,
    # "allows the transfer only if the projected figure does not exceed
    #  110 percent of the target's quarterly_capacity_units"
    "TRANSFER_MAX_UTILIZATION_PCT": 110,
    # "a reject rate of at most 250 basis points ... exactly 250 basis points passes"
    "QUAL_MAX_REJECT_RATE_BP": 250,
    # "When a PASS brings consecutive_pass_count to 2, the transfer auto-executes"
    "QUAL_REQUIRED_CONSECUTIVE_PASSES": 2,
    # "an expires_at stamped as its created_at plus exactly 30 days"
    "NEGOTIATION_TTL_DAYS": 30,
}

# ─── Worked-example expected values (pinned by PRD prose) ───────────────────
WORKED = {
    # PRD §3.2 composite worked example:
    # brand revenue 1,000,000,000 / pl 40; item 10,000 units, rev 2,000, cost 1,700
    "COMPOSITE_VOLUME_SCORE": 80.00,
    "COMPOSITE_MARGIN_SCORE": 57.14,
    "COMPOSITE_SHELF_SCORE": 90.00,
    "COMPOSITE_BACKLASH_SCORE": 63.00,
    "COMPOSITE_SCORE": 72.04,
    # PRD §3.2 obsolescence worked example: 100 units at 500 cents
    "OBSOLESCENCE_STANDARD_CENTS": 50000,
    "OBSOLESCENCE_SALVAGE_CENTS": 40000,
    # PRD §3.5 penalty worked example: fee 120,010, 3 months remaining
    "TSA_PENALTY_WORKED_CENTS": 90008,
    "TSA_PENALTY_FORBIDDEN_ORDER_CENTS": 90009,
    # PRD §3.7 priority worked example: fit 80, year-3 revenue 1,000,000,000
    "PRIORITY_STANDARD_WORKED": 68.00,
    "PRIORITY_CORE_BRAND_WORKED": 78.00,
}

# ─── Factory defaults (chosen fixture inputs, not PRD-pinned rules) ─────────
TEST_DEFAULTS = {
    "BRAND_CATEGORY": "storage",
    "BRAND_PL_SHARE_PCT": 40,
    "BRAND_ANNUAL_NET_REVENUE_CENTS": 1000000000,
    "PLANT_CAPACITY_UNITS": 1000000,
    "RETAILER_RISK_RATING": "LOW",
    "ITEM_ANNUAL_UNITS": 4000,
    "ITEM_UNIT_NET_REVENUE_CENTS": 2000,
    "ITEM_UNIT_COST_CENTS": 1700,
    "ITEM_UNITS_ON_HAND": 0,
    "ACQUIRER_NAME": "Acq Co",
    "HEADLINE_PRICE_CENTS": 500000000,
    "EXPECTED_CLOSE_DATE": "2026-10-01T00:00:00Z",
    "TSA_MONTHLY_FEE_CENTS": 100000,
    "TSA_START_DATE": "2026-09-01T00:00:00Z",
    "TSA_END_DATE": "2027-09-01T00:00:00Z",
    "CLOSURE_DATE": "2027-03-01T00:00:00Z",
    "RUN_DATE": "2026-09-02T00:00:00Z",
    "RUN_UNITS_PRODUCED": 10000,
    "RUN_UNITS_REJECTED_PASS": 250,     # exactly 250bp: passes
    "RUN_UNITS_REJECTED_CLEAR_PASS": 100,
    "NEGOTIATION_PERIOD_CODE": "2027-H1",
    "NEGOTIATION_EFFECTIVE_FROM": "2027-01-01T00:00:00Z",
    "NEGOTIATION_EFFECTIVE_TO": "2027-06-30T00:00:00Z",
    "CYCLE_PERIOD_CODE": "2027-H1",
    "CYCLE_TOTAL_CAPITAL_CENTS": 1000000000,
    "CYCLE_WINDOW_START": "2026-09-01T00:00:00Z",
    "CYCLE_WINDOW_END": "2027-03-01T00:00:00Z",
    "PROJECT_TITLE": "Innovation Project",
    "PROJECT_REQUESTED_CAPITAL_CENTS": 1000,
    "PROJECT_EXPECTED_REVENUE_Y3_CENTS": 1000000000,
    "PROJECT_STRATEGIC_FIT_SCORE": 80,
}

# Opaque user-id strings used where the PRD records but does not compare them
# (case proposer / decider segregation of duties).
USER_IDS = {
    "PROPOSER_1": "pm-proposer-1",
    "PROPOSER_2": "pm-proposer-2",
    "DECIDER_1": "pm-decider-1",
    "DECIDER_2": "pm-decider-2",
    "SYSTEM_MARKER": "system",
}

# A well-formed UUID that resolves to nothing (for 404 tests).
ABSENT_UUID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"

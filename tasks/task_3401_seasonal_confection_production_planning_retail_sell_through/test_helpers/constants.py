"""Domain constants — every value below is pinned verbatim by PRD.md prose.

Each constant carries the PRD section that names or fixes its value. Nothing
here is invented: if a threshold or rate is not stated in PRD.md, it does not
appear in this module.
"""

# --- Logical clock ---------------------------------------------------------
# PRD §2.5: "On startup, before any client has set it, the logical clock is
# exactly 2026-09-01T00:00:00Z; the clock must never silently fall back to
# wall-clock time."
CLOCK_START_DEFAULT_ISO = "2026-09-01T00:00:00Z"

# --- Seasonal program lifecycle --------------------------------------------
# PRD §3.4: "the program supports a single sanctioned reopen from LOCKED back
# to OPEN_FOR_COMMITMENTS, usable at most once — the reopen budget MAX_REOPEN
# is 1."
MAX_REOPEN = 1

# --- Supply waterfall / shortfall credit ------------------------------------
# PRD §3.5: "the unmet units times the program's retail_price_cents, times the
# shortfall-credit rate of 0.10 (ten percent), rounded half-up to whole cents".
SHORTFALL_CREDIT_PCT = 0.10

# PRD §3.5: "Eligible commitments are sorted by retailer tier first, using the
# fixed rank order GOLD (rank 0), then SILVER (rank 1), then BRONZE (rank 2)".
TIER_RANK = {"GOLD": 0, "SILVER": 1, "BRONZE": 2}

# --- Cannibalization index ---------------------------------------------------
# PRD §3.7: "the lift constant is 1.10 for a VALENTINES program, 1.15 for
# EASTER, 1.25 for HALLOWEEN, and 1.20 for CHRISTMAS."
SEASONAL_LIFT = {
    "VALENTINES": 1.10,
    "EASTER": 1.15,
    "HALLOWEEN": 1.25,
    "CHRISTMAS": 1.20,
}

# PRD §3.9: "the average of cannibalization_raw over those reports must be at
# least 0.85 — the cannibalization floor".
CANNIBALIZATION_FLOOR = 0.85

# --- Disposition -------------------------------------------------------------
# PRD §3.9: "a MARKDOWN order must carry a markdown_pct — a fraction no lower
# than 0.10 and no higher than 0.70".
MIN_MARKDOWN_PCT = 0.10
MAX_MARKDOWN_PCT = 0.70

# PRD §3.9: "the recovered value is the disposed units times the program's
# retail_price_cents times the secondary-channel recovery fraction, a system
# constant fixed at 0.25 (25%)".
SECONDARY_RECOVERY_PCT = 0.25

# --- Heat claims -------------------------------------------------------------
# PRD §3.8: "the shipment's ship_on falls in a summer month — June, July, or
# August (months 6, 7, and 8)".
SUMMER_MONTHS = (6, 7, 8)

# PRD §3.8 settlement branch fractions, in pinned top-to-bottom order:
#   temp_controlled -> 1.00; declined -> 0.50; auto-approve -> 1.00; else 0.25.
HEAT_CLAIM_PCT_TEMP_CONTROLLED = 1.00
HEAT_CLAIM_PCT_DECLINED = 0.50
HEAT_CLAIM_PCT_AUTO_APPROVE = 1.00
HEAT_CLAIM_PCT_GOODWILL = 0.25

# --- Warehouse posture -------------------------------------------------------
# PRD §2.9: "if in_use_units is at least the floor of 85% of capacity_units
# (the congestion threshold is the constant 0.85, applied with a floor before
# comparison), posture is CONGESTED".
CONGESTED_PCT = 0.85

# --- Production line scheduling ----------------------------------------------
# PRD §2.10: "the new run must start at least 8 hours after the prior run's
# scheduled_end_on ... The 8-hour buffer is inclusive: a gap of exactly 8
# hours passes."
CHANGEOVER_HOURS = 8

# --- Pagination ---------------------------------------------------------------
# PRD §2.3: "The limit parameter defaults to 10, must be at least 1, and must
# not exceed 100. The offset parameter defaults to 0."
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

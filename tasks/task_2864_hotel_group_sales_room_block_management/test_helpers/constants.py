"""Domain constants and thresholds declared by the PRD.

Every value here is quoted from the PRD so that the test suite never
re-derives a threshold the specification already fixes.
"""

# --- PRD 2.4: the logical clock -------------------------------------------
# "Before any client moves it, the logical clock reads exactly
#  2026-08-01T00:00:00Z; this is a mandated startup default".
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"
CLOCK_DEFAULT_MINTED = "2026-08-01T00:00:00.000Z"

# --- PRD 2.3: pagination --------------------------------------------------
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0

# --- PRD 3.2: qualification scoring --------------------------------------
QUALIFICATION_FLOOR = 30              # "A qualification_score of 30 or more"
ROOM_NIGHT_VOLUME_CAP = 40            # "the smaller of 40 and ... / 10"
ROOM_NIGHT_VOLUME_DIVISOR = 10
PEAK_SIZE_CAP = 25                    # "the smaller of 25 and peak_rooms / 4"
PEAK_SIZE_DIVISOR = 4
SPACE_INTENSITY_TIGHT_RATIO = 30.0    # "30.0 or less ... contributes 15 points"
SPACE_INTENSITY_TIGHT_POINTS = 15
SPACE_INTENSITY_MID_RATIO = 60.0      # "greater than 30.0 but 60.0 or less ... 8"
SPACE_INTENSITY_MID_POINTS = 8
SPACE_INTENSITY_HUNGRY_POINTS = 0
LEAD_TIME_LONG_DAYS = 180             # "180 days or more contributes 20 points"
LEAD_TIME_LONG_POINTS = 20
LEAD_TIME_MID_DAYS = 90               # "90 days or more contributes 12"
LEAD_TIME_MID_POINTS = 12
LEAD_TIME_SHORT_POINTS = 5
SCORE_CAP = 100                       # "the result is capped at 100"

# "1.20 for CORPORATE, 1.00 for ASSOCIATION, 0.85 for GOVERNMENT, 0.75 for SMERF"
SEGMENT_MULTIPLIER = {
    "CORPORATE": 1.20,
    "ASSOCIATION": 1.00,
    "GOVERNMENT": 0.85,
    "SMERF": 0.75,
}

# "multiplied by the group-rate factor of 0.82"
GROUP_RATE_FACTOR = 0.82

# --- PRD 3.2 / 3.3: meeting space and displacement -----------------------
# "every existing hold ... is notionally extended by 45 minutes at its end"
TURNOVER_MINUTES = 45
# "multiplied by 4,500 cents - forty-five dollars per room night"
ANCILLARY_PER_ROOM_NIGHT_CENTS = 4500

# --- PRD 3.7: attrition --------------------------------------------------
# "multiplied by the attrition damage factor of 0.85"
ATTRITION_DAMAGE_FACTOR = 0.85

# --- PRD 3.9: settlement waterfall --------------------------------------
REBATE_CAP_PCT = 0.25                 # "the rebate cap percentage of 0.25"
SIZE_BONUS_PCT = 0.02                 # "The size bonus is 0.02 when ..."
SIZE_BONUS_FLOOR_CENTS = 2_000_000    # "the size-bonus floor of 2,000,000 cents"
INCENTIVE_RATE_CAP = 0.05             # "the incentive rate cap of 0.05"

# --- PRD 3.1 / 3.9: rebooking ladder ------------------------------------
REBOOKING_TIER_BASE = 0.01            # "starting at 0.01"
REBOOKING_TIER_MID = 0.03
REBOOKING_TIER_TOP = 0.05
REBOOKING_TOP_CONTRACTS = 3           # "at least 3 contracts"
REBOOKING_TOP_ROOM_NIGHTS = 1500      # "at least 1500 lifetime actualized room nights"
REBOOKING_MID_CONTRACTS = 1
REBOOKING_MID_ROOM_NIGHTS = 400
LAPSE_DAYS = 730                      # "more than 730"

# --- PRD 3.9: cancellation tiers ----------------------------------------
CANCEL_TIER_180_PCT = 0.25
CANCEL_TIER_90_PCT = 0.50
CANCEL_TIER_30_PCT = 0.75
CANCEL_TIER_LATE_PCT = 1.00
CANCEL_TIER_180_DAYS = 180
CANCEL_TIER_90_DAYS = 90
CANCEL_TIER_30_DAYS = 30
FM_NO_CLAUSE_FACTOR = 0.50            # "the no-clause factor of 0.50"

# --- PRD 3.8: ancillary -------------------------------------------------
INTERNET_DISCOUNT_PCT = 0.0           # "exactly 0.0 for an INTERNET charge"

# --- Canonical calendar used by the golden path -------------------------
ARRIVAL_DATE = "2026-11-09"
DEPARTURE_DATE = "2026-11-12"
STAY_DATES = ["2026-11-09", "2026-11-10", "2026-11-11"]
NIGHTS_COUNT = 3
CUTOFF_DAYS_BEFORE_ARRIVAL = 21
CUTOFF_DATE = "2026-10-19"            # arrival less 21 whole days
POST_DEPARTURE_CLOCK = "2026-11-12T10:00:00Z"
CUTOFF_CLOCK = "2026-10-19T08:00:00Z"

# Inventory-day figures the design work is pinned to.
INV_TOTAL_ROOMS = 400
INV_GROUP_CEILING_ROOMS = 250
INV_TRANSIENT_DEMAND_ROOMS = 398
INV_TRANSIENT_ADR_CENTS = 21000
INV_HISTORICAL_PICKUP_ROOMS = 390
INV_HISTORICAL_ADR_CENTS = 19500

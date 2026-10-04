"""Domain thresholds — numeric constants from the PRD calculations."""

# --- host_effective_capacity / host_committed_sites -----------------------
# No numeric constants; capacity is a site count or a window override.

# --- host_posture_derivation ---------------------------------------------
LIMITED_BAND_PCT = 0.20

# --- stay_ancillary_charge ------------------------------------------------
ELECTRIC_30A_PER_NIGHT_CENTS = 700
ELECTRIC_50A_PER_NIGHT_CENTS = 1200
ELECTRIC_50A_PER_NIGHT_CENTS_TRAILER = 900
ELECTRIC_NIGHT_CEILING_CENTS = 1200
GUEST_PASS_PURCHASE_CENTS = 500
ANCILLARY_HARD_CAP_CENTS = 25000

# --- host_patronization_credit -------------------------------------------
PATRONIZATION_RATE = 0.05
PER_RECORD_CREDIT_CAP_CENTS = 1500

# --- late_cancellation_fee -----------------------------------------------
FREE_CANCEL_DAYS = 7
TIER_LOW_MAX_CENTS = 2000
TIER_MID_MAX_CENTS = 5000
TIER_MID_PCT = 0.15
TIER_MID_FLAT_CENTS = 500
TIER_HIGH_PCT = 0.25
TIER_HIGH_FLAT_CENTS = 1500

# --- member_standing_score ------------------------------------------------
BASE_SCORE = 100
PENALTY_MINOR = 5
PENALTY_MAJOR = 15
PENALTY_SEVERE = 40
SCORE_FLOOR = 0
STRIKE_REMOVAL_THRESHOLD = 3

# --- guest_pass_allotment -------------------------------------------------
ALLOTMENT_CLASSIC = 0
ALLOTMENT_PLUS = 2
ALLOTMENT_PREMIER = 4

# --- ordinance_compliance -------------------------------------------------
ORDINANCE_PROFILES = {
    ("OR", "WINERY"): {"max_sites": 2, "self_containment": True},
    ("OR", "FARM"): {"max_sites": 6, "self_containment": True},
    ("CA", "WINERY"): {"max_sites": 4, "self_containment": True},
    ("CA", "BREWERY"): {"max_sites": 3, "self_containment": False},
    ("TX", "FARM"): {"max_sites": 8, "self_containment": False},
    ("TX", "ATTRACTION"): {"max_sites": 10, "self_containment": False},
}

# --- temporal guards ------------------------------------------------------
LEAD_TIME_HOURS = 48
APPROACH_BUFFER_HOURS = 2

# --- review aggregates ----------------------------------------------------
RATING_PRECISION = 2

THRESHOLDS = {
    "LIMITED_BAND_PCT": LIMITED_BAND_PCT,
    "ELECTRIC_NIGHT_CEILING_CENTS": ELECTRIC_NIGHT_CEILING_CENTS,
    "ANCILLARY_HARD_CAP_CENTS": ANCILLARY_HARD_CAP_CENTS,
    "PER_RECORD_CREDIT_CAP_CENTS": PER_RECORD_CREDIT_CAP_CENTS,
    "FREE_CANCEL_DAYS": FREE_CANCEL_DAYS,
    "STRIKE_REMOVAL_THRESHOLD": STRIKE_REMOVAL_THRESHOLD,
    "LEAD_TIME_HOURS": LEAD_TIME_HOURS,
    "APPROACH_BUFFER_HOURS": APPROACH_BUFFER_HOURS,
}

TEST_DEFAULTS = {
    "CLOCK_START": "2026-09-01T00:00:00Z",
    "ARRIVAL_WINDOW_START_HOUR": 14,
    "ARRIVAL_WINDOW_END_HOUR": 11,
}
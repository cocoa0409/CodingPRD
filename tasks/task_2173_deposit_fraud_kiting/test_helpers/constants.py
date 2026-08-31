"""Domain thresholds and constants stated in the PRD narrative."""

# --- New-account risk score (PRD §3.1) --------------------------------------
KYC_TIER_POINTS = {"TIER_1": 0, "TIER_2": 15, "TIER_3": 35}
FUNDING_POINTS = {"VERIFIED": 0, "PENDING": 20, "NONE": 30}
CHANNEL_POINTS = {"BRANCH": 0, "ONLINE": 12, "MOBILE": 18}
WATCHLIST_POINTS = 40
LINK_POINTS_PER_RISK_LINK = 5
LINK_POINTS_CAP = 25
LINK_CONFIDENCE_MIN_BPS = 6000
RISK_BAND_HIGH_MIN = 60
RISK_BAND_ELEVATED_MIN = 35

# --- Account-takeover scoring (PRD §3.5) ------------------------------------
INDICATOR_WEIGHTS = {
    "NEW_DEVICE": 15,
    "GEO_VELOCITY": 25,
    "CREDENTIAL_STUFFING": 30,
    "PROFILE_CHANGE": 20,
    "DORMANT_REACTIVATION": 18,
    "PAYEE_ADDED": 12,
}
ATO_STEP_UP_MIN = 40
ATO_LOCK_MIN = 75
STEP_UP_MAX_FAILURES = 3

# --- Availability ladder (PRD §3.3) -----------------------------------------
IMMEDIATE_AVAIL_CENTS = 22500
LARGE_DEPOSIT_CENTS = 552500
NEW_ACCOUNT_DAYS = 30
HOLD_DAYS = {
    "STANDARD": 2,
    "EXCEPTION_RISK": 5,
    "EXCEPTION_LARGE_DEPOSIT": 7,
    "EXCEPTION_NEW_ACCOUNT": 9,
    "EXCEPTION_FRAUD": 0,
}

# --- Early-release loss exposure (PRD §3.4) ---------------------------------
RETURN_RATE_BPS = {"CHECK": 275, "ACH": 120, "CASH": 0}
RISK_MULT_BPS = {"STANDARD": 10000, "ELEVATED": 12500, "HIGH": 16000}
SUPERVISOR_APPROVAL_LIMIT_CENTS = 500000

# --- Kiting detection (PRD §3.6) --------------------------------------------
CYCLE_MAX_DEPTH = 4
CYCLE_BASE = {2: 40, 3: 55, 4: 60}
VELOCITY_WEIGHT = 6
UNCOLLECTED_WEIGHT = 30
KITING_OPEN_THRESHOLD = 70

# --- Charge-off pricing and recovery (PRD §3.8) -----------------------------
RECOVERY_FEE_TIER_1_MAX_CENTS = 100000
RECOVERY_FEE_TIER_1_BPS = 500
RECOVERY_FEE_TIER_2_MAX_CENTS = 500000
RECOVERY_FEE_TIER_2_BPS = 350
RECOVERY_FEE_TIER_3_BPS = 200
RECOVERY_REFERRAL_MIN_CENTS = 25000

# --- Cross-cutting (PRD §3.2, §3.7, §3.9, §2.5) -----------------------------
FUNDING_MAX_TOTAL_ATTEMPTS = 5
MULE_CLOSURE_NOTICE_DAYS = 10
PRESERVATION_BUFFER_DAYS = 3
DEFAULT_LOGICAL_CLOCK_UTC = "2026-08-01T00:00:00Z"

# --- Pagination (PRD §2.3) --------------------------------------------------
DEFAULT_PAGE_LIMIT = 10
MAX_PAGE_LIMIT = 100

# --- Convenience test values ------------------------------------------------
TEST_DEFAULTS = {
    # A 30000-cent CHECK splits 22500 immediate / 7500 held.
    "STANDARD_CHECK_CENTS": 30000,
    "STANDARD_HELD_CENTS": 7500,
    "MICRO_DEPOSIT_MISMATCH": 0,
}

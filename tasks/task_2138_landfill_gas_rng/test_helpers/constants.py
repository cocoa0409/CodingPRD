"""Domain thresholds and numeric constants named by the PRD."""

# ─── Logical clock ────────────────────────────────────
# Before the clock is ever set it reads exactly this instant.
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# The instant nearly every scenario in this suite pins its clock to.
BASE_CLOCK_UTC = "2026-08-10T00:00:00Z"
# A clock past the end of August, used when a 2026-08 settlement month
# must have fully elapsed.
SEPTEMBER_CLOCK_UTC = "2026-09-05T00:00:00Z"


# ─── Gas quality scoring and classification (PRD §3.2) ─
QUALITY = {
    "OXYGEN_WEIGHT": 4.0,
    "NITROGEN_WEIGHT": 0.35,
    "METHANE_CREDIT_WEIGHT": 0.05,
    "TEMPERATURE_PENALTY_BASE_F": 130.0,
    "TEMPERATURE_PENALTY_PER_DEGREE": 0.25,
    "OXYGEN_ALARM_PCT": 5.00,
    "TEMPERATURE_ALARM_F": 145.0,
    "AIR_INTRUSION_ALARM": 24.00,
    "OXYGEN_WATCH_PCT": 2.00,
    "METHANE_WATCH_FLOOR_PCT": 45.00,
    "AIR_INTRUSION_WATCH": 6.00,
}

# A throttled well is credited at most this fraction of its target flow.
THROTTLE_CAP_FRACTION = 0.60

# Consecutive GOOD readings required to leave each state.
RECOVERY_READINGS_FROM_ISOLATED = 2
RECOVERY_READINGS_FROM_THROTTLED = 3


# ─── Maintenance lockout geometry (PRD §2.10, §3.3) ───
LOCKOUT_BUFFER_MINUTES = 120


# ─── Injection batch energy content (PRD §3.7) ────────
METHANE_HEATING_VALUE_MMBTU_PER_MSCF = 1.0122


# ─── Environmental attributes (PRD §3.8) ──────────────
ATTRIBUTES = {
    "RIN_PER_MMBTU": 11.727,
    "LCFS_BASELINE_CI": 44.000,
    "LCFS_FLARE_PENALTY_FACTOR": 60.000,
    "LCFS_BENCHMARK_CI": 91.980,
    "LCFS_ENERGY_ECONOMY_RATIO": 0.90,
    "MJ_PER_MMBTU": 1055.06,
    "AVOIDED_TIER_A": 22.500,   # pre-credit intensity below 20.000
    "AVOIDED_TIER_B": 15.000,   # pre-credit intensity below 40.000
    "AVOIDED_TIER_C": 7.500,    # pre-credit intensity at or above 40.000
    "AVOIDED_TIER_A_CEILING": 20.000,
    "AVOIDED_TIER_B_CEILING": 40.000,
}


# ─── Royalty settlement prices (PRD §3.9) ─────────────
RIN_PRICE_USD = 2.85
LCFS_CREDIT_PRICE_USD = 62.00


# ─── Pagination (PRD §2.3) ────────────────────────────
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}


# ─── Values the scenarios in this suite share ─────────
TEST_DEFAULTS = {
    "SITE_NAME": "Rolling Hills Landfill",
    "SITE_STATE_CODE": "CA",
    "HOST_ROYALTY_PCT": 0.12,
    "PERMIT_NMOC_LIMIT_LB_PER_HR": 3.5,
    "ROYALTY_FLOOR_USD_PER_MMBTU": 0.25,
    "PLANT_CODE": "P1",
    "RECEIPT_POINT_CODE": "RP-7",
    "RECEIPT_POINT_MDQ_DTH_PER_DAY": 4800.0,
    "MIN_FEED_SCFM": 900.0,
    "WELL_TARGET_FLOW_SCFM": 500.0,
    "COUNTERPARTY_NAME": "Bluewater Energy",
    "CONTRACT_MDQ_DTH_PER_DAY": 3000.0,
    "PRICE_USD_PER_DTH": 5.25,
    "TERM_START": "2026-08-01T00:00:00Z",
    "TERM_END": "2027-08-01T00:00:00Z",
    "NOMINATED_DTH": 2400.0,
}

# The canonical three-hour block: [115.0, 115.0, 115.0] mscf at 97.4 % methane.
# Rounding each hour before summing gives 340.14 MMBtu.
CANONICAL_BATCH_GROSS_MMBTU = 340.14
CANONICAL_BATCH_METERED_MMBTU = 352.40

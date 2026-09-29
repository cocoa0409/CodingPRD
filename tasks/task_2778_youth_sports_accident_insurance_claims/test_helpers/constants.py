"""Domain thresholds and rating constants used by the program's calculations."""

# Logical clock -------------------------------------------------------------
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# Hazard class loads, in basis points, folded into every band line ----------
HAZARD_LOAD_BPS = {
    "CLASS_1_LOW": 0,
    "CLASS_2_MODERATE": 1150,
    "CLASS_3_HIGH": 2625,
    "CLASS_4_CONTACT": 4075,
}

# Head-count bands and their rate factors, in basis points ------------------
PREMIUM_BAND_FACTOR_BPS = {
    "BAND_1_TO_75": 10000,
    "BAND_76_TO_400": 9250,
    "BAND_ABOVE_400": 8500,
}
PREMIUM_BAND_1_UPPER = 75
PREMIUM_BAND_2_UPPER = 400

# Catastrophic layer charge and volume credit ------------------------------
CAT_LAYER_CHARGE_BPS = 850
VOLUME_CREDIT_TIERS_BPS = {
    "UNDER_500000": 0,
    "500000_TO_1499999": 300,
    "1500000_TO_4999999": 550,
    "5000000_AND_ABOVE": 800,
}
MINIMUM_ANNUAL_PREMIUM_CENTS = 25000

# Case reserves by severity tier ------------------------------------------
RESERVE_BY_SEVERITY_CENTS = {
    "MINOR": 50000,
    "MODERATE": 250000,
    "SEVERE": 1500000,
    "CATASTROPHIC": 7500000,
}

# Severity factors applied to the benefit schedule cap, in basis points ----
SEVERITY_CAP_FACTOR_BPS = {
    "MINOR": 10000,
    "MODERATE": 10000,
    "SEVERE": 11500,
    "CATASTROPHIC": 12500,
}

# Repricing ---------------------------------------------------------------
OUT_OF_NETWORK_FEE_SCHEDULE_FACTOR_BPS = 14000
OUT_OF_NETWORK_FAMILY_RESPONSIBILITY_CAP_CENTS = 15000

# Coordination ------------------------------------------------------------
FULL_EXCESS_DEDUCTIBLE_FACTOR_BPS = 20000
EOB_WAIVER_DAYS = 45

# Injury reporting --------------------------------------------------------
FILING_WINDOW_DAYS = 90
VERIFICATION_WINDOW_DAYS = 30
MAX_CORRECTION_ROUNDS = 2

# Coverage posture --------------------------------------------------------
CLAIMS_REVIEW_OPEN_CLAIM_COUNT = 3
CLAIMS_REVIEW_INCURRED_LOSS_RATIO_BPS = 6500
OPEN_CLAIM_ADJUDICATION_STATUSES = (
    "PENDING_COORDINATION",
    "UNDER_ADJUDICATION",
    "APPROVED",
)

# Loss experience tiers, keyed on the elected loss ratio in basis points ---
EXPERIENCE_TIER_BOUNDS_BPS = {
    "PREFERRED": (0, 3499),
    "STANDARD": (3500, 6499),
    "ADVERSE": (6500, 9999),
    "DECLINE": (10000, None),
}
RENEWAL_EXPERIENCE_MODIFIER_BPS = {
    "PREFERRED": -1500,
    "STANDARD": 0,
    "ADVERSE": 2750,
    "DECLINE": 6000,
}

# Activity types that are covered exposure --------------------------------
UNCOVERED_ACTIVITY_TYPE = "TEAM_SOCIAL"

# Benefit schedule categories --------------------------------------------
SERVICE_CATEGORIES = (
    "EMERGENCY_ROOM",
    "SURGERY",
    "DIAGNOSTIC_IMAGING",
    "PHYSICAL_THERAPY",
    "DENTAL",
    "AMBULANCE",
    "PHYSICIAN_OFFICE",
)

# Benefit schedules reused across the pinned fixtures ---------------------
BASEBALL_U12_CAPS = {
    "EMERGENCY_ROOM": 500000,
    "SURGERY": 3000000,
    "DIAGNOSTIC_IMAGING": 300000,
    "PHYSICAL_THERAPY": 20000,
    "DENTAL": 350000,
    "AMBULANCE": 200000,
    "PHYSICIAN_OFFICE": 50000,
}
CHEER_U12_CAPS = {
    "EMERGENCY_ROOM": 250000,
    "SURGERY": 400000,
    "DIAGNOSTIC_IMAGING": 150000,
    "PHYSICAL_THERAPY": 15000,
    "DENTAL": 150000,
    "AMBULANCE": 100000,
    "PHYSICIAN_OFFICE": 35000,
}
SWIM_U14_CAPS = {
    "EMERGENCY_ROOM": 200000,
    "SURGERY": 600000,
    "DIAGNOSTIC_IMAGING": 120000,
    "PHYSICAL_THERAPY": 15000,
    "DENTAL": 100000,
    "AMBULANCE": 80000,
    "PHYSICIAN_OFFICE": 30000,
}

# Pinned premium build-ups for the 404-participant BASEBALL_U12 term -------
BASEBALL_404_GROSS_PREMIUM_CENTS = 781833
BASEBALL_404_CAT_CHARGE_CENTS = 66456
BASEBALL_404_SUBTOTAL_CENTS = 848289
BASEBALL_404_VOLUME_CREDIT_CENTS = 25449
BASEBALL_404_ANNUAL_PREMIUM_CENTS = 822840

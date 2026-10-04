"""Domain thresholds and test defaults drawn from the PRD's numeric rules.

Only constants the PRD states in prose live here. Windows whose length the PRD
deliberately leaves to configuration (the authorization, reversal, amendment and
appeal windows; the submission-expiry, pregnancy-test, late-submission,
pre-route lead and storage-retention intervals) are NOT hard-coded — tests
assert their boundaries relative to the instant the PRD fixes them to.
"""

# --- Clinical appropriateness scoring (PRD §3.5) --------------------------------
APPROVAL_FLOOR = 70  # inclusive
AGE_35_37_PENALTY = 20
AGE_38_40_PENALTY = 40
AGE_41_PLUS_PENALTY = 60
AMH_UNDER_0_5_PENALTY = 20
AMH_UNDER_1_0_PENALTY = 10
PRIOR_LIVE_BIRTH_BONUS = 15
PRIOR_CYCLES_2_PENALTY = 15
PRIOR_CYCLES_3_PLUS_PENALTY = 25
FSH_OVER_12_PENALTY = 10
CRITERIA_BASE = 100

# --- Member cost share (PRD §3.9) -----------------------------------------------
MEMBER_OOP_MAX_CENTS = 250000
SPECIALTY_DIFFERENTIAL_PCT = 12
COST_DIFFERENCE_CAP_CENTS = 15000

# --- Claim allowance slices (PRD §3.9) ------------------------------------------
ANCILLARY_SHARE_PCT = {
    "LAB": 12,
    "STORAGE": 4,
    "DONOR_MATERIAL": 18,
    "SURROGACY_FEE": 25,
}

# --- Clinic quality score (PRD §3.3) --------------------------------------------
LIVE_BIRTH_WEIGHT_BPS = 60
MULTIPLE_BIRTH_PENALTY_BPS = 45
MATURITY_BONUS_BPS = 20
MATURITY_CAP = 5

# --- Specialty pharmacy pool (PRD §3.7) -----------------------------------------
INGREDIENT_PCT = 82

# --- Pagination (PRD §2.3) -------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MAX_LIMIT = 100

# --- Scenario clock and default shapes ------------------------------------------
# The logical clock reads this instant at server startup and holds it until set.
DEFAULT_CLOCK = "2026-09-01T00:00:00Z"

TEST_DEFAULTS = {
    "PLAN_YEAR": 2026,
    "ENROLLMENT_LIMIT": 50,
    "LIFETIME_MAX_CYCLES": 6,
    "MAX_CYCLES_PER_YEAR": 6,
    "MAX_TRANSFERS_PER_CYCLE": 2,
    "PHARMACY_POOL_CENTS": 1000000,
    "BUNDLE_EFFECTIVE_FROM": "2026-01-01T00:00:00Z",
    "BUNDLE_EFFECTIVE_TO": "2028-01-01T00:00:00Z",
    "BUNDLE_RATE_IVF": 1450000,
    "MEMBER_COST_SHARE_PCT": 20,
    "CASELOAD_LIMIT": 5,
    "CREDENTIALS_EXPIRE_ON": "2027-12-31T00:00:00Z",
    "MATURITY_REPORT_THRESHOLD": 2,
}

# Criteria profile that scores 100 (all-neutral inputs).
NEUTRAL_CRITERIA = {
    "age_years": 33,
    "amh_ng_ml": 2.0,
    "prior_cycles": 0,
    "prior_live_birth": False,
    "fsh_iu_l": 6,
}

# Criteria profile that scores exactly 69 (one band below the 70 floor).
# A profile whose five bands net to 35, leaving 100 - 35 = 65 — comfortably under
# the 70 floor, and the same reading whether the penalties are summed before one
# clamp or applied one band at a time.
CRITERIA_BELOW_FLOOR = {
    "age_years": 34,            #   0
    "amh_ng_ml": 2.0,           #   0
    "prior_live_birth": False,  #   0
    "prior_cycles": 3,          # -25
    "fsh_iu_l": 13,             # -10
}

# The inclusive floor, and the profile the PRD singles out: the five bands total
# exactly 74, which approves at 70 whether the penalties are summed before the
# clamp or applied one band at a time.
CRITERIA_SCORE_70 = {
    "age_years": 34,            #   0
    "amh_ng_ml": 0.8,           # -10
    "prior_live_birth": True,   # +15
    "prior_cycles": 3,          # -25
    "fsh_iu_l": 13,             # -10
}

# Criteria profile that scores 0 (every penalty band at maximum).
CRITERIA_SCORE_0 = {
    "age_years": 41,
    "amh_ng_ml": 0.4,
    "prior_cycles": 3,
    "prior_live_birth": False,
    "fsh_iu_l": 14,
}
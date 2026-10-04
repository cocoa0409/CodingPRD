"""Domain thresholds — numeric constants copied from PRD.md prose.

Every value below appears literally in the PRD:
- Logical clock startup default (section 2.5): "At startup the clock is
  exactly 2026-09-01T00:00:00Z."
- Acuity weights and tier thresholds (section 3.3).
- Statutory rate table, dependent allowances, COLA multiplier (section 3.4).
- Appeal window 90 days + 7-day close grace = 97 days (sections 2.5 / 3.4).
- Recovery buffer 7 days (section 3.5).
- Per-registration travel cap 50000 cents (section 3.7).
- Survey windows: baseline 14 days, exit 30 days, followup 90 +/- 7 days
  (section 3.8).
- ITT missing-baseline imputation 50 (section 3.8).
"""

# ---- Logical clock ------------------------------------------------------
CLOCK_START_ISO = "2026-09-01T00:00:00Z"

# ---- Acuity scoring (PRD section 3.3) -----------------------------------
ACUITY_WEIGHTS_VETERAN = {"PSYCH": 0.4, "PHYS": 0.3, "VOC": 0.2, "SOC": 0.1}
ACUITY_WEIGHTS_FAMILY_SUPPORT = {"PSYCH": 0.5, "PHYS": 0.1, "VOC": 0.2, "SOC": 0.2}
ACUITY_TIER_ENHANCED_MIN = 40
ACUITY_TIER_INTENSIVE_MIN = 70

# ---- Compensation (PRD section 3.4 statutory rate table) -----------------
RATING_BASE_CENTS = {
    0: 0,
    10: 17500,
    20: 34600,
    30: 52400,
    40: 75500,
    50: 105700,
    60: 134000,
    70: 166100,
    80: 193200,
    90: 217200,
    100: 373700,
}
DEPENDENT_RATING_FLOOR_PCT = 30
DEPENDENT_ALLOWANCE_ONE_CENTS = 16000
DEPENDENT_ALLOWANCE_TWO_CENTS = 31000
DEPENDENT_ALLOWANCE_EXTRA_CENTS = 9000
COLA_MULTIPLIER = 1.025  # "multiplied by 1.025 — the statutory cost-of-living adjustment of 2.5 percent"

# ---- Appeal / claim-close windows (PRD sections 2.5 and 3.4) -------------
APPEAL_WINDOW_DAYS = 90
CLAIM_CLOSE_GRACE_DAYS = 7
CLAIM_CLOSE_TOTAL_DAYS = 97  # "more than 97 days before the clock — that is, the 90-day appeal window plus a further 7-day close grace"

# ---- Referral treatment windows (PRD section 3.5) ------------------------
RECOVERY_BUFFER_DAYS = 7

# ---- Event travel support (PRD section 3.7) ------------------------------
PER_REGISTRATION_TRAVEL_CAP_CENTS = 50000

# ---- Survey windows (PRD section 3.8) ------------------------------------
BASELINE_WINDOW_DAYS = 14
EXIT_WINDOW_DAYS = 30
FOLLOWUP_90_OFFSET_DAYS = 90
FOLLOWUP_GRACE_DAYS = 7

# ---- Donor reporting (PRD section 3.8) -----------------------------------
BASELINE_IMPUTE_SCORE = 50

# ---- Placement milestones (PRD section 3.6) ------------------------------
MILESTONE_DAY_30_DAYS = 30
MILESTONE_DAY_90_DAYS = 90
MILESTONE_DAY_180_DAYS = 180

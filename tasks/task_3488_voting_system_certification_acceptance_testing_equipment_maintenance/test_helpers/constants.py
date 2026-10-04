"""Domain constants — every literal here is pinned by a PRD sentence.

Nothing in this module is derived or invented; each value cites the PRD
passage that fixes it. Test-data defaults (names, dates chosen to satisfy
PRD windows) live in factories.py, not here.
"""

# --- Logical clock ---------------------------------------------------------
# PRD §2.4: "The server must boot with its logical clock fixed at
# 2026-09-01T00:00:00Z and must not fall back to wall-clock time".
BOOT_CLOCK_ISO = "2026-09-01T00:00:00Z"

# --- Pagination (PRD §2.3) -------------------------------------------------
# "limit ... defaults to 10, with a minimum of 1 and a maximum of 100.
# offset ... defaults to 0."
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0

# --- Certificates (PRD §3.3) ----------------------------------------------
# "expires_at is exactly 730 days after issued_at."
CERT_TTL_DAYS = 730

# --- Campaign conformity scoring (PRD §3.2) --------------------------------
# Screening variant: "starts from 10000 and subtracts 1200 per open critical
# deficiency, 300 per open major, 75 per open minor, and 250 per completed
# resubmission."
SCREEN_CRITICAL_WEIGHT = 1200
SCREEN_MAJOR_WEIGHT = 300
SCREEN_MINOR_WEIGHT = 75
SCREEN_RESUBMISSION_PENALTY = 250
# Final-audit variant: "starts from 10000 and subtracts 1500 per open critical
# deficiency, 250 per open major, 50 per open minor, 400 per completed
# resubmission, and an aging term of 10 basis points per full week elapsed
# since last_submitted_at".
FINAL_CRITICAL_WEIGHT = 1500
FINAL_MAJOR_WEIGHT = 250
FINAL_MINOR_WEIGHT = 50
FINAL_RESUBMISSION_PENALTY = 400
FINAL_AGING_BP_PER_WEEK = 10
# Certification gate: "the freshly evaluated final-audit conformity must be at
# least 8000 basis points".
CONFORMITY_PASS_BP = 8000

# --- Acceptance deficiency index (PRD §3.4) --------------------------------
# "the smaller of 100 and a weighted sum ... HARDWARE_DIAGNOSTIC weighs
# critical, major, and minor defects at 25, 8, and 2; BALLOT_SCAN_CALIBRATION
# at 30, 10, and 3; LOGIC_VERIFICATION at 40, 12, and 4."
ACCEPTANCE_INDEX_CLAMP = 100
ACCEPTANCE_WEIGHTS = {
    "HARDWARE_DIAGNOSTIC": (25, 8, 2),
    "BALLOT_SCAN_CALIBRATION": (30, 10, 3),
    "LOGIC_VERIFICATION": (40, 12, 4),
}
# "PASS if and only if critical_defects is zero and the deficiency_index is at
# most 20".
ACCEPTANCE_INDEX_MAX = 20

# --- Ballot print estimation (PRD §3.5) ------------------------------------
# "ballots_per_precinct divided by 500 sheets per ream, rounded up ...
# 100 reams or fewer prices at 4200 cents per ream, 101 through 500 reams at
# 3900 cents per ream, and more than 500 reams at 3500 cents per ream."
REAM_SHEETS = 500
TIER1_MAX_REAMS = 100
TIER1_PRICE_CENTS = 4200
TIER2_MAX_REAMS = 500
TIER2_PRICE_CENTS = 3900
TIER3_PRICE_CENTS = 3500

# --- Paper stock envelope (PRD §3.5) ---------------------------------------
# "weight within 80 to 120 gsm and thickness within 60 to 250 microns".
PAPER_WEIGHT_MIN_GSM = 80
PAPER_WEIGHT_MAX_GSM = 120
PAPER_THICKNESS_MIN_MICRONS = 60
PAPER_THICKNESS_MAX_MICRONS = 250

# --- Election calendar (PRD §3.5) ------------------------------------------
# "the election_date must be at least 30 days after the current logical date
# at creation".
ELECTION_MIN_LEAD_DAYS = 30
# "the election_date must be at least 14 days after the current logical date"
# (locking freeze window).
ELECTION_FREEZE_DAYS = 14

# --- Logic-and-accuracy verification (PRD §3.6) ----------------------------
# "result is PASS if and only if 10000 times total_discrepancy is less than or
# equal to 50 times total_expected".
LA_DISCREPANCY_MAX_BP = 50

# --- Equipment fleet (PRD §3.7) --------------------------------------------
# Deploy "requires battery_cycles strictly below 500 — exactly 500 is
# rejected".
BATTERY_CYCLE_MAX = 500
# Storage band: "a temperature outside 10 to 35 degrees Celsius or a humidity
# outside 20 to 70 percent increments storage_excursion_count by 1".
STORAGE_TEMP_MIN_C = 10
STORAGE_TEMP_MAX_C = 35
STORAGE_HUMIDITY_MIN_PCT = 20
STORAGE_HUMIDITY_MAX_PCT = 70

# --- Software modification lead times (PRD §3.9) ---------------------------
# "start from a base of 30 days; if component_codes touches
# TABULATION_FIRMWARE or BALLOT_LAYOUT_ENGINE, add 60 days; if the system has
# a certificate with scope FEDERAL in ACTIVE or SUSPENDED status ... add 45
# days."
MOD_BASE_LEAD_DAYS = 30
MOD_SCOPE_TOUCHING_ADD_DAYS = 60
MOD_FEDERAL_CERT_ADD_DAYS = 45
SCOPE_TOUCHING_COMPONENTS = ("TABULATION_FIRMWARE", "BALLOT_LAYOUT_ENGINE")

# --- Test laboratory capacity (PRD §3.1) -----------------------------------
# "an optional max_concurrent_campaigns that defaults to 3 and must lie
# between 1 and 10 inclusive".
DEFAULT_LAB_CAPACITY = 3
LAB_CAPACITY_MIN = 1
LAB_CAPACITY_MAX = 10

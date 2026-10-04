"""Domain constants — every contract value pinned to a verbatim PRD statement.

Sections below cite the PRD passage that pins each value. ``TEST_DEFAULTS``
entries are NOT contract values; they are the conventional fixture inputs
shared across tests (baseline 1000 tests, 100000c monthly minimum, ...).
"""

__all__ = [
    "CLOCK_START_ISO", "CLOCK_2026_09_01_20H", "CLOCK_2026_09_02_09H",
    "CLOCK_2026_10_01", "CLOCK_2026_10_01_1S", "CLOCK_2026_10_02",
    "CLOCK_2026_10_05", "CLOCK_2026_11_01", "CLOCK_2027_01_15",
    "CLOCK_2028_09_02",
    "MAX_DISCOUNT_PCT", "PRICE_TABLE", "KNOWN_SKUS", "QC_MATERIAL_SKUS",
    "ALLOWED_TERM_MONTHS", "MIN_MONTHLY_MINIMUM_CENTS",
    "SHORTFALL_BILLING_RATE", "SHORTFALL_BREACH_THRESHOLD_CENTS",
    "RENEGOTIATION_CASELOAD_DELTA_PCT",
    "PROFICIENCY_TOLERANCE_PCT", "QC_VALIDITY_DAYS",
    "RESPONSE_SLA_HOURS", "UPTIME_WINDOW_DAYS", "UPTIME_WINDOW_HOURS",
    "UPTIME_BREACH_THRESHOLD_PCT", "CALIBRATION_FREE_HOURS_PER_YEAR",
    "UPTIME_SERVICE_CREDIT_CENTS",
    "DEFAULT_LIMIT", "MIN_LIMIT", "MAX_LIMIT", "DEFAULT_OFFSET",
    "ALL_ROLES", "UNKNOWN_UUID_1", "UNKNOWN_UUID_2", "TEST_DEFAULTS",
]

# --- Logical clock (PRD §2.4) -------------------------------------------------
# "At server startup the logical clock reads exactly 2026-09-01T00:00:00Z."
CLOCK_START_ISO = "2026-09-01T00:00:00Z"

# Common clock targets used by fixtures and tests. Every value below is
# STRICTLY AFTER CLOCK_START_ISO, so advancing from the startup default to any
# one of them (in ascending order within a test) is always a legal
# strictly-forward set (PRD §2.4). Never invent dates earlier than these.
CLOCK_2026_09_01_20H = "2026-09-01T20:00:00Z"    # +20h calibration window
CLOCK_2026_09_02_09H = "2026-09-02T09:00:00Z"    # +33h repair-breach window
CLOCK_2026_10_01 = "2026-10-01T00:00:00Z"        # QC boundary: 2026-09-01 PASS + 30d
CLOCK_2026_10_01_1S = "2026-10-01T00:00:01Z"     # one second past the QC boundary
CLOCK_2026_10_02 = "2026-10-02T00:00:00Z"        # Sept-2026 period is closable
CLOCK_2026_10_05 = "2026-10-05T00:00:00Z"        # mid-October fulfillment point
CLOCK_2026_11_01 = "2026-11-01T00:00:00Z"        # Sept + Oct periods closable
CLOCK_2027_01_15 = "2027-01-15T00:00:00Z"        # Sep..Dec 2026 periods closable
CLOCK_2028_09_02 = "2028-09-02T00:00:00Z"        # past a 2026-09-01 + 24mo end_date

# --- Pricing (PRD §3.2, §3.4) -------------------------------------------------
# "must lie between 0 and 0.40 inclusive — the platform ceiling MAX_DISCOUNT_PCT"
MAX_DISCOUNT_PCT = 0.40

# "the platform price table PRICE_TABLE" (PRD §3.4, verbatim prices/families)
PRICE_TABLE = {
    "VC300_CHEM_SLIDE":  {"family": "SLIDE",       "list_price_cents": 420},
    "VC300_LYTE_CART":   {"family": "CARTRIDGE",   "list_price_cents": 760},
    "VH500_CBC_CART":    {"family": "CARTRIDGE",   "list_price_cents": 890},
    "VH500_DIFF_SLIDE":  {"family": "SLIDE",       "list_price_cents": 385},
    "VU200_URINE_STRIP": {"family": "SLIDE",       "list_price_cents": 153},
    "QC_LEVEL_1":        {"family": "QC_MATERIAL", "list_price_cents": 3000},
    "QC_LEVEL_2":        {"family": "QC_MATERIAL", "list_price_cents": 3000},
    "CAL_KIT_STANDARD":  {"family": "CALIBRATOR",  "list_price_cents": 12500},
}
KNOWN_SKUS = sorted(PRICE_TABLE)
QC_MATERIAL_SKUS = sorted(
    sku for sku, row in PRICE_TABLE.items() if row["family"] == "QC_MATERIAL"
)

# --- Placement agreements (PRD §2.7, §3.3) ------------------------------------
# "term_months must be one of 24, 36, 48, or 60 (ALLOWED_TERM_MONTHS)"
ALLOWED_TERM_MONTHS = [24, 36, 48, 60]
# "must carry monthly_minimum_cents of at least 50000 cents — the platform
#  floor MIN_MONTHLY_MINIMUM_CENTS"
MIN_MONTHLY_MINIMUM_CENTS = 50000

# --- Commitment billing (PRD §3.5) --------------------------------------------
# "multiplied by the platform's shortfall billing rate of 0.80
#  (SHORTFALL_BILLING_RATE)"
SHORTFALL_BILLING_RATE = 0.80
# "at or above the breach threshold of 250000 cents
#  (SHORTFALL_BREACH_THRESHOLD_CENTS)"
SHORTFALL_BREACH_THRESHOLD_CENTS = 250000

# --- Renegotiation (PRD §3.6) -------------------------------------------------
# "must reach at least 0.30 of the snapshot (RENEGOTIATION_CASELOAD_DELTA_PCT)"
RENEGOTIATION_CASELOAD_DELTA_PCT = 0.30

# --- Proficiency / QC (PRD §3.9) ----------------------------------------------
# "must be at most 0.05 of the expected value (PROFICIENCY_TOLERANCE_PCT)"
PROFICIENCY_TOLERANCE_PCT = 0.05
# "extends qc_valid_until to thirty days (QC_VALIDITY_DAYS, 30 days)"
QC_VALIDITY_DAYS = 30

# --- Uptime and field service (PRD §3.7, §3.9) --------------------------------
# "computes response_due_at as twenty-four hours later (RESPONSE_SLA_HOURS, 24 hours)"
RESPONSE_SLA_HOURS = 24
# "the logical clock minus ninety days (UPTIME_WINDOW_DAYS, 90 days)"
UPTIME_WINDOW_DAYS = 90
# "the window's length is 2160 hours (UPTIME_WINDOW_HOURS)"
UPTIME_WINDOW_HOURS = 2160
# "strictly below 0.985 (UPTIME_BREACH_THRESHOLD_PCT)"
UPTIME_BREACH_THRESHOLD_PCT = 0.985
# "the smaller of the calibration downtime and sixteen hours
#  (CALIBRATION_FREE_HOURS_PER_YEAR, 16 hours)"
CALIBRATION_FREE_HOURS_PER_YEAR = 16
# "credited 25000 cents (UPTIME_SERVICE_CREDIT_CENTS)"
UPTIME_SERVICE_CREDIT_CENTS = 25000

# --- Pagination (PRD §2.3) -----------------------------------------------------
# "defaults to 10, with a minimum of 1 and a maximum of 100. offset ... 0"
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --- Roles (PRD §2.1) ----------------------------------------------------------
ALL_ROLES = [
    "PlatformAdmin",
    "FinanceReviewer",
    "ClinicManager",
    "FieldServiceEngineer",
    "LaboratoryTechnician",
]

# --- Never-allocated UUIDs for 404 / FK-order tests ----------------------------
# Distinct from the framework's NON_EXISTENT_UUID so a body carrying two
# unknown foreign keys can give each its own value.
UNKNOWN_UUID_1 = "00000000-0000-4000-8000-000000000001"
UNKNOWN_UUID_2 = "00000000-0000-4000-8000-000000000002"

# --- Conventional test-data defaults (NOT contract constants) ------------------
TEST_DEFAULTS = {
    "CLINIC_NAME": "Vale Veterinary",
    "BASELINE_CASELOAD": 1000,
    "MONTHLY_MINIMUM_CENTS": 100000,
    "PURCHASE_PRICE_CENTS": 950000,
    "LEASE_RATE_CENTS": 320000,
    "TERM_MONTHS": 24,
    "START_DATE": CLOCK_START_ISO,
    "MODEL_RC": "VETCHEM_300",
    "MODEL_PURCHASE": "VETHEMAT_500",
    "EXPECTED_RESULT": 200.0,
    "PROF_PASS_RESULT": 205.0,
    "PATIENT_RESULT": 7.7,
    "TEST_CODE_PATIENT": "CBC",
    "TEST_CODE_PROFICIENCY": "PROF-CHEM",
    "TEST_CODE_SEND_OUT": "CHEM17",
    "GPA_EFFECTIVE_TO": "2027-09-01T00:00:00Z",
}

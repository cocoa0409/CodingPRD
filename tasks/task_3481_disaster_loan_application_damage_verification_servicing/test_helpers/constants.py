"""Domain constants — every value is stated verbatim in the PRD.

Sections: filing windows (3.1), caps/thresholds (3.6), credit/DTI (3.3),
rates/terms/deferral (2.8), disbursement (3.7), verification (3.4),
servicing/aging (3.9), receivable (3.8), reconsideration (3.2),
accommodation (3.9), logical clock (2.4), pagination (2.3).
"""

# --- URL layout -----------------------------------------------------------
API_PREFIX = "/disaster-relief"
# Platform-level endpoints live at the server root, NOT under API_PREFIX
# (PRD 2.4: "a single platform-level clock endpoint sits outside that prefix").
CLOCK_PATH = "/_clock/set_current_utc"

# --- Logical clock (PRD 2.4) ----------------------------------------------
CLOCK_STARTUP_DEFAULT = "2026-09-01T00:00:00Z"

# --- Filing windows (PRD 3.1) ----------------------------------------------
PHYSICAL_FILING_WINDOW_DAYS = 90
EIDL_FILING_WINDOW_DAYS = 270

# Canonical declaration used across the helper fixtures: DR-4821 declared
# 2026-10-01T00:00:00Z; the two deadlines are that date plus the windows.
CANONICAL_DECLARED_DATE = "2026-10-01T00:00:00Z"
CANONICAL_PHYSICAL_FILING_DEADLINE = "2026-12-30T00:00:00Z"
CANONICAL_EIDL_FILING_DEADLINE = "2027-06-28T00:00:00Z"
CANONICAL_COUNTY_BOTH = "06037"        # PHYSICAL_DAMAGE + ECONOMIC_INJURY
CANONICAL_COUNTY_EIDL_ONLY = "06059"   # ECONOMIC_INJURY only

# --- Statutory caps in cents (PRD 3.6 step one) -----------------------------
HOMEOWNER_PHYSICAL_CAP_CENTS = 50000000
RENTER_PHYSICAL_CAP_CENTS = 10000000
BUSINESS_PHYSICAL_CAP_CENTS = 200000000
EIDL_CAP_CENTS = 200000000

# --- Collateral thresholds in cents (PRD 3.6; strictly greater) -------------
PHYSICAL_COLLATERAL_THRESHOLD_CENTS = 2500000
EIDL_COLLATERAL_THRESHOLD_CENTS = 5000000

# --- Credit review (PRD 3.3) ------------------------------------------------
MIN_CREDIT_SCORE = 640
CREDIT_SCORE_MIN = 300
CREDIT_SCORE_MAX = 850
MAX_DTI_PERCENT = 43

# --- Rate / term / deferral (PRD 2.8) ---------------------------------------
INTEREST_RATE_PERSONAL = 0.03125   # HOMEOWNER and RENTER physical loans
INTEREST_RATE_BUSINESS = 0.04      # BUSINESS physical and all ECONOMIC_INJURY
TERM_MONTHS_HOMEOWNER = 360
TERM_MONTHS_RENTER = 84
TERM_MONTHS_BUSINESS = 360
TERM_MONTHS_EIDL = 360
DEFERRAL_MONTHS = 12

# --- Disbursement schedule (PRD 3.6 hop two / 3.7) ---------------------------
INITIAL_DISBURSEMENT_CAP_CENTS = 2500000

# --- Damage verification (PRD 3.4) -------------------------------------------
ESTIMATION_MAX_CENTS = 2500000
MAX_DEPRECIATION_PCT = 0.90
DISPUTE_WINDOW_DAYS = 30

# --- Payment allocation / aging (PRD 3.9) ------------------------------------
DAYS_IN_YEAR = 365
LATE_FEE_GRACE_DAYS = 15
LATE_FEE_PCT = 0.05
DELINQUENT_AFTER_DAYS = 30
DEFAULT_AFTER_DAYS = 120
CHARGE_OFF_AFTER_DAYS = 180

# --- Excess funds receivable (PRD 3.8) ---------------------------------------
EXCESS_FUNDS_DUE_DAYS = 30

# --- Reconsideration (PRD 3.2) -----------------------------------------------
MAX_RECONSIDERATIONS = 2

# --- Servicing accommodation (PRD 3.9) ---------------------------------------
ACCOMMODATION_MAX_DAYS = 360

# --- Pagination (PRD 2.3) ------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100

# --- Expected success HTTP status per ApiClient operation (PRD 4) ------------
# "Operations that create a new resource respond with 201; operations that
# modify an existing resource, drive a state transition, or read data respond
# with 200. The clock endpoint responds with 200."
EXPECTED_SUCCESS_STATUS = {
    "set_clock": 200,
    "create_declaration": 201,
    "create_applicant": 201,
    "create_application": 201,
    "list_applications": 200,
    "get_application": 200,
    "submit_application": 200,
    "request_reconsideration": 200,
    "create_credit_review": 201,
    "list_credit_reviews": 200,
    "decide_application": 200,
    "create_damage_verification": 201,
    "list_damage_verifications": 200,
    "complete_damage_verification": 200,
    "dispute_damage_verification": 200,
    "create_grant_award": 201,
    "list_grant_awards": 200,
    "list_loans": 200,
    "get_loan": 200,
    "accept_loan": 200,
    "list_tranches": 200,
    "create_milestone": 201,
    "list_milestones": 200,
    "decide_milestone": 200,
    "release_tranche": 200,
    "create_modification_request": 201,
    "list_modification_requests": 200,
    "decide_modification_request": 200,
    "create_insurance_settlement": 201,
    "list_insurance_settlements": 200,
    "apply_insurance_settlement": 200,
    "void_insurance_settlement": 200,
    "list_excess_funds_receivables": 200,
    "pay_excess_funds_receivable": 201,
    "create_servicing_action": 201,
    "list_servicing_actions": 200,
    "decide_servicing_action": 200,
    "create_payment": 201,
    "list_payments": 200,
    "reverse_payment": 200,
}

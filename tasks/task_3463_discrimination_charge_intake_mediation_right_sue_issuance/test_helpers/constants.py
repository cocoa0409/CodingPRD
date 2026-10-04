"""Domain thresholds and constants for the EEOC Charge Processing API.

Every value below is pinned to the PRD prose (see the inline section cites).
Nothing here is a guess: if a number is not stated in the PRD it does not
appear in this module.
"""

# --- Logical clock (PRD section 2.4) -----------------------------------------
# "Before any clock-setting call has been made, the logical clock reads exactly
#  2026-09-01T00:00:00Z"
CLOCK_BOOT_DEFAULT = "2026-09-01T00:00:00Z"

# --- Intake timeliness screening (PRD section 3.2) ----------------------------
# "when none matched, the federal default of 180 days applies"
FEDERAL_DEFAULT_DEADLINE_DAYS = 180
# "Only two deadline values are accepted — 180 or 300 days"
DEFERRAL_EXTENDED_DEADLINE_DAYS = 300
AGENCY_DEADLINE_CHOICES = (
    FEDERAL_DEFAULT_DEADLINE_DAYS,
    DEFERRAL_EXTENDED_DEADLINE_DAYS,
)

# --- Jurisdictional size screen (PRD section 3.2) -----------------------------
# "Every other basis survives when the snapshot headcount is at least 15."
TITLE_VII_MIN_EMPLOYEES = 15
# "An AGE basis survives only when the snapshot headcount is at least 20 ..."
ADEA_MIN_EMPLOYEES = 20

# --- Employer size bands (PRD section 3.1) ------------------------------------
# UNDER_15 0-14, FROM_15_TO_19 15-19, FROM_20_TO_100 20-100,
# FROM_101_TO_200 101-200, FROM_201_TO_500 201-500, OVER_500 501+.
BAND_EDGE_TITLE_VII = 15
BAND_EDGE_ADEA = 20
BAND_EDGE_CAP_T1_MAX = 100
BAND_EDGE_CAP_T2_MAX = 200
BAND_EDGE_CAP_T3_MAX = 500

SIZE_BAND_UNDER_15 = "UNDER_15"
SIZE_BAND_15_19 = "FROM_15_TO_19"
SIZE_BAND_20_100 = "FROM_20_TO_100"
SIZE_BAND_101_200 = "FROM_101_TO_200"
SIZE_BAND_201_500 = "FROM_201_TO_500"
SIZE_BAND_OVER_500 = "OVER_500"

SIZE_BANDS = (
    SIZE_BAND_UNDER_15,
    SIZE_BAND_15_19,
    SIZE_BAND_20_100,
    SIZE_BAND_101_200,
    SIZE_BAND_201_500,
    SIZE_BAND_OVER_500,
)


def expected_size_band(employee_count: int) -> str:
    """PRD section 3.1 band rule; boundaries inclusive at the low end."""
    if employee_count < BAND_EDGE_TITLE_VII:
        return SIZE_BAND_UNDER_15
    if employee_count < BAND_EDGE_ADEA:
        return SIZE_BAND_15_19
    if employee_count <= BAND_EDGE_CAP_T1_MAX:
        return SIZE_BAND_20_100
    if employee_count <= BAND_EDGE_CAP_T2_MAX:
        return SIZE_BAND_101_200
    if employee_count <= BAND_EDGE_CAP_T3_MAX:
        return SIZE_BAND_201_500
    return SIZE_BAND_OVER_500


# --- Remedy valuation (PRD section 3.7) ---------------------------------------
# "Interest accrues at an annual rate of 0.05 (five percent)"
ANNUAL_INTEREST_RATE = 0.05
# "... multiplied by interest_days, divided by 365, then rounded half-up"
INTEREST_DIVISOR_DAYS = 365
# Statutory cap tiers: "5000000 cents for FROM_15_TO_19 and FROM_20_TO_100
# alike, 10000000 cents for FROM_101_TO_200, 20000000 cents for FROM_201_TO_500,
# and 30000000 cents for OVER_500."
CAP_TIER_CENTS = {
    SIZE_BAND_15_19: 5_000_000,
    SIZE_BAND_20_100: 5_000_000,
    SIZE_BAND_101_200: 10_000_000,
    SIZE_BAND_201_500: 20_000_000,
    SIZE_BAND_OVER_500: 30_000_000,
}

# --- Right-to-sue (PRD section 3.8) -------------------------------------------
# "The charging-party path requires days_elapsed_since_filing of at least 180"
RTS_MIN_ELAPSED_DAYS = 180
# "computes court_filing_deadline as exactly 90 days after issuance"
RTS_COURT_FILING_DAYS = 90

# --- Evidence requests (PRD section 3.5) --------------------------------------
# "the due_date is computed as exactly 30 days after issuance"
EVIDENCE_RESPONSE_WINDOW_DAYS = 30

# --- Witness interviews (PRD section 3.5) -------------------------------------
# "kept apart by a 30-minute buffer on both sides"
INTERVIEW_BUFFER_MINUTES = 30

# --- Settlement vacatur (PRD section 3.8) -------------------------------------
# "Within 10 days of settled_at ... a later attempt is rejected"
VACATE_WINDOW_DAYS = 10

# --- Mediation rounds (PRD section 3.4) ---------------------------------------
# "the hard cap being 2 rounds per charge"
MAX_MEDIATION_ROUNDS = 2

# --- Investigation priority score (PRD section 3.5) ---------------------------
# "using 30 for RETALIATION, 25 for DISABILITY, 20 for AGE, and 15 for each of
#  SEX, RACE, COLOR, RELIGION, NATIONAL_ORIGIN, and GENETIC_INFO"
BASIS_SEVERITY_WEIGHT = {
    "RETALIATION": 30,
    "DISABILITY": 25,
    "AGE": 20,
    "SEX": 15,
    "RACE": 15,
    "COLOR": 15,
    "RELIGION": 15,
    "NATIONAL_ORIGIN": 15,
    "GENETIC_INFO": 15,
}
# Age tiers: "0 points under 90 days, 10 points from 90 through 179 days,
# 20 points from 180 through 364 days, and 35 points at 365 days or more."
# Each tuple is (min_days_inclusive, points).
PRIORITY_AGE_TIERS = ((90, 10), (180, 20), (365, 35))
# "adds 15 points per currently-OVERDUE evidence request"
OVERDUE_PER_REQUEST = 15
# "capped at 45 points no matter how many requests are late"
OVERDUE_COMPONENT_CAP = 45
# "the sum of those three terms is multiplied by 1.5"
SYSTEMIC_MULTIPLIER = 1.5
# "clamped to a ceiling of 100"
SCORE_CEILING = 100
# "the first time a recomputed score reaches 80 or more"
ESCALATION_THRESHOLD = 80

# --- Systemic consolidation (PRD section 3.9) ---------------------------------
# "at least 3 linked charges are non-terminal"
CONSOLIDATION_MIN_CHARGES = 3
# "at least 2 of those non-terminal charges share a basis with basis_focus"
CONSOLIDATION_MIN_SHARED_BASIS = 2

# --- Pagination defaults (PRD section 2.3) ------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# --- Charge state sets (PRD sections 3.2, 3.3, 3.8, 3.9) -----------------------
# Terminal: "DISMISSED_UNTIMELY, DISMISSED_NO_JURISDICTION, CLOSED_NO_CAUSE,
# RTS_ISSUED, and WITHDRAWN are the charge's terminal states" (section 3.2).
CHARGE_TERMINAL_STATES = frozenset(
    {
        "DISMISSED_UNTIMELY",
        "DISMISSED_NO_JURISDICTION",
        "CLOSED_NO_CAUSE",
        "RTS_ISSUED",
        "WITHDRAWN",
    }
)
# Amend/withdraw-eligible: "while its case_status is DOCKETED, IN_MEDIATION,
# UNDER_INVESTIGATION, or DELEGATED_TO_FEPA" (section 3.3).
CHARGE_WORKABLE_STATES = frozenset(
    {"DOCKETED", "IN_MEDIATION", "UNDER_INVESTIGATION", "DELEGATED_TO_FEPA"}
)
# For the systemic resolution rule a charge counts as terminal in every state
# except these seven (PRD section 3.9).
CHARGE_NON_TERMINAL_FOR_SYSTEMIC = frozenset(
    {
        "DOCKETED",
        "IN_MEDIATION",
        "UNDER_INVESTIGATION",
        "DETERMINATION_REVIEW",
        "CONCILIATION",
        "DELEGATED_TO_FEPA",
        "LITIGATION_REFERRED",
    }
)

# A valid UUID that no test fixture ever creates — used for 404 probes.
# Matches the id the design recipes probe with.
UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"

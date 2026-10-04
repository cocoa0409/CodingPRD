"""Domain constants, enum vocabularies, rounding and calendar helpers.

Every value here is transcribed from the PRD: the mount points of section 1
and section 4, the logical-clock default of section 2.4, the role names of
section 2.1, the rounding modes of section 2.6, the enum vocabularies and
pinned numeric constants of section 3, and the pagination bounds of
section 2.3.

Two helpers go beyond literals because the PRD pins their behaviour:
``round_half_up_cents`` / ``round_dime_cents`` implement the two rounding
modes of section 2.6 exactly, and ``add_months`` / ``month_diff`` implement
the exact calendar-month arithmetic of section 2.4.
"""

from decimal import ROUND_HALF_UP, Decimal

# --- Mount points -----------------------------------------------------------
#
# All business operations sit under ``/medicare``.  The two test-driving
# operations are mounted OUTSIDE that prefix; do not prefix them.

API_PREFIX = "/medicare"
CLOCK_PATH = "/_clock/set_current_utc"
MONTHLY_CYCLE_PATH = "/_ops/run_monthly_cycle"

# "Before any clock-setting call has been made, the clock reads exactly
# 2026-09-01T00:00:00Z" (PRD section 2.4).
CLOCK_INITIAL_INSTANT = "2026-09-01T00:00:00Z"

# --- Roles (spelled exactly as PRD section 2.1 declares them) ---------------

ROLE_BENEFICIARY = "Beneficiary"
ROLE_FIELD_OFFICER = "FieldOfficer"
ROLE_APPEALS_OFFICER = "AppealsOfficer"
ROLE_IRS_DATA_AGENT = "IrsDataAgent"
ROLE_BENEFIT_ADMINISTRATOR = "BenefitAdministrator"

ALL_ROLES = (
    ROLE_BENEFICIARY,
    ROLE_FIELD_OFFICER,
    ROLE_APPEALS_OFFICER,
    ROLE_IRS_DATA_AGENT,
    ROLE_BENEFIT_ADMINISTRATOR,
)

# --- Coverage parts (PRD section 1) -----------------------------------------

PART_A = "PART_A"
PART_B = "PART_B"
PART_C = "PART_C"
PART_D = "PART_D"
PARTS = (PART_A, PART_B, PART_C, PART_D)
ENROLLABLE_PARTS = (PART_A, PART_B, PART_D)  # PART_C only via election effectivity
PRICEABLE_PARTS = (PART_B, PART_D)           # determination parts
BILLABLE_PARTS = (PART_B, PART_D)

# --- Enrollment windows (PRD section 3.2) -----------------------------------

WINDOW_IEP = "IEP"
WINDOW_SEP = "SEP"
WINDOW_TYPES = (WINDOW_IEP, WINDOW_SEP)  # only beneficiary-anchored windows are rows

VIA_IEP = "IEP"
VIA_SEP = "SEP"
VIA_GEP = "GEP"
VIA_AEP = "AEP"
VIA_OEP_MA = "OEP_MA"
VIA_RELIEF = "RELIEF"
ENROLLED_VIA_WINDOWS = (VIA_IEP, VIA_SEP, VIA_GEP, VIA_AEP, VIA_OEP_MA, VIA_RELIEF)

PERIOD_UPCOMING = "UPCOMING"
PERIOD_OPEN = "OPEN"
PERIOD_EXPIRED = "EXPIRED"
ENROLLMENT_PERIOD_STATUSES = (PERIOD_UPCOMING, PERIOD_OPEN, PERIOD_EXPIRED)

# IEP: attainment-3 .. attainment+3 inclusive (PRD section 3.1).
IEP_MONTHS_BEFORE_ATTAINMENT = 3
IEP_MONTHS_AFTER_ATTAINMENT = 3
# SEP: anchor+1 .. anchor+8 inclusive (PRD section 3.3).
SEP_WINDOW_MONTHS = 8

# Calendar windows (computed from the clock, never persisted).
GEP_START_MONTH_DAY = (1, 1)    # January 1
GEP_END_MONTH_DAY = (3, 31)     # March 31
AEP_START_MONTH_DAY = (10, 15)  # October 15 00:00 UTC
AEP_END_MONTH_DAY = (12, 7)     # December 7 23:59:59 UTC
OEP_START_MONTH_DAY = (1, 1)    # January 1
OEP_END_MONTH_DAY = (3, 31)     # March 31

# --- CoverageEnrollment status dimensions (PRD section 3.2) -----------------

ENROLLMENT_PENDING = "PENDING"
ENROLLMENT_ACTIVE = "ACTIVE"
ENROLLMENT_TERMINATED = "TERMINATED"
ENROLLMENT_CANCELLED = "CANCELLED"
ENROLLMENT_STATUSES = (
    ENROLLMENT_PENDING,
    ENROLLMENT_ACTIVE,
    ENROLLMENT_TERMINATED,
    ENROLLMENT_CANCELLED,
)
ENROLLMENT_TERMINAL_STATUSES = (ENROLLMENT_TERMINATED, ENROLLMENT_CANCELLED)

COLLECTION_PENDING_SETUP = "PENDING_SETUP"
COLLECTION_WITHHOLDING = "WITHHOLDING"
COLLECTION_DIRECT_BILL = "DIRECT_BILL"
COLLECTION_DELINQUENT = "DELINQUENT"
COLLECTION_NOT_REQUIRED = "NOT_REQUIRED"
COLLECTION_CLOSED = "CLOSED"
COLLECTION_STATUSES = (
    COLLECTION_PENDING_SETUP,
    COLLECTION_WITHHOLDING,
    COLLECTION_DIRECT_BILL,
    COLLECTION_DELINQUENT,
    COLLECTION_NOT_REQUIRED,
    COLLECTION_CLOSED,
)

TARGET_METHOD_WITHHOLDING = "WITHHOLDING"
TARGET_METHOD_DIRECT_BILL = "DIRECT_BILL"
TARGET_METHODS = (TARGET_METHOD_WITHHOLDING, TARGET_METHOD_DIRECT_BILL)

# --- EmployerCoverageRecord vocabulary (PRD section 3.3) --------------------

VERIFICATION_UNVERIFIED = "UNVERIFIED"
VERIFICATION_VERIFIED = "VERIFIED"
VERIFICATION_REJECTED = "REJECTED"
VERIFICATION_STATUSES = (
    VERIFICATION_UNVERIFIED,
    VERIFICATION_VERIFIED,
    VERIFICATION_REJECTED,
)
VERIFY_DECISIONS = (VERIFICATION_VERIFIED, VERIFICATION_REJECTED)

RECORD_ACTIVE_COVERAGE = "ACTIVE_COVERAGE"
RECORD_ENDED = "ENDED"
RECORD_STATUSES = (RECORD_ACTIVE_COVERAGE, RECORD_ENDED)

# "employer_size of at least 20 - exactly 20 counts as large, while 19 does
# not" (PRD section 3.3).
LARGE_EMPLOYER_MIN_SIZE = 20

PAYER_ROLE_PRIMARY = "MEDICARE_PRIMARY"
PAYER_ROLE_SECONDARY = "MEDICARE_SECONDARY"
PAYER_ROLES = (PAYER_ROLE_PRIMARY, PAYER_ROLE_SECONDARY)

PAYER_BASIS_NO_EMPLOYER_COVERAGE = "NO_EMPLOYER_COVERAGE"
PAYER_BASIS_SMALL_EMPLOYER = "SMALL_EMPLOYER"
PAYER_BASIS_LARGE_EMPLOYER = "LARGE_EMPLOYER"
PAYER_BASES = (
    PAYER_BASIS_NO_EMPLOYER_COVERAGE,
    PAYER_BASIS_SMALL_EMPLOYER,
    PAYER_BASIS_LARGE_EMPLOYER,
)

# --- Penalty assessments (PRD section 3.4) ----------------------------------

PENALTY_ACTIVE = "ACTIVE"
PENALTY_WAIVED = "WAIVED"
PENALTY_VOIDED = "VOIDED"
PENALTY_STATUSES = (PENALTY_ACTIVE, PENALTY_WAIVED, PENALTY_VOIDED)

PENALTY_PARTS = (PART_B, PART_D)

# "ten percent per full twelve-month period uncovered" (PRD section 3.4).
PART_B_LEP_PCT_PER_PERIOD = 10
LEP_PERIOD_MONTHS = 12
# Part D: "one percent of that year's part_d_national_base_cents" per month.
PART_D_LEP_PCT_PER_MONTH = 1

# --- Tax records (PRD section 3.5) ------------------------------------------

FILING_SINGLE = "SINGLE"
FILING_MARRIED_JOINT = "MARRIED_JOINT"
FILING_STATUSES = (FILING_SINGLE, FILING_MARRIED_JOINT)

# --- Premium determinations (PRD section 3.5) -------------------------------

DETERMINATION_PROVISIONAL = "PROVISIONAL"
DETERMINATION_FINAL = "FINAL"
DETERMINATION_SUPERSEDED = "SUPERSEDED"
DETERMINATION_STATUSES = (
    DETERMINATION_PROVISIONAL,
    DETERMINATION_FINAL,
    DETERMINATION_SUPERSEDED,
)

IRMAA_TIER_MIN = 0
IRMAA_TIER_MAX = 5
IRMAA_BRACKET_COUNT = 6  # "an array of exactly six objects" (PRD section 3.5)

# --- Appeals (PRD section 3.6) ----------------------------------------------

APPEAL_UNDER_REVIEW = "UNDER_REVIEW"
APPEAL_MORE_INFO_REQUESTED = "MORE_INFO_REQUESTED"
APPEAL_APPROVED = "APPROVED"
APPEAL_DENIED = "DENIED"
APPEAL_STATUSES = (
    APPEAL_UNDER_REVIEW,
    APPEAL_MORE_INFO_REQUESTED,
    APPEAL_APPROVED,
    APPEAL_DENIED,
)
APPEAL_DECISIONS = (APPEAL_APPROVED, APPEAL_DENIED, APPEAL_MORE_INFO_REQUESTED)

LIFE_EVENT_WORK_STOPPAGE = "WORK_STOPPAGE"
LIFE_EVENT_WORK_REDUCTION = "WORK_REDUCTION"
LIFE_EVENT_MARRIAGE = "MARRIAGE"
LIFE_EVENT_DIVORCE = "DIVORCE"
LIFE_EVENT_SPOUSE_DEATH = "SPOUSE_DEATH"
LIFE_EVENT_PENSION_LOSS = "PENSION_LOSS"
LIFE_EVENT_PROPERTY_LOSS = "PROPERTY_LOSS"
LIFE_EVENT_TYPES = (
    LIFE_EVENT_WORK_STOPPAGE,
    LIFE_EVENT_WORK_REDUCTION,
    LIFE_EVENT_MARRIAGE,
    LIFE_EVENT_DIVORCE,
    LIFE_EVENT_SPOUSE_DEATH,
    LIFE_EVENT_PENSION_LOSS,
    LIFE_EVENT_PROPERTY_LOSS,
)

# --- Withholding arrangements (PRD section 3.7) -----------------------------

ARRANGEMENT_ACTIVE = "ACTIVE"
ARRANGEMENT_SUSPENDED = "SUSPENDED"
ARRANGEMENT_STOPPED = "STOPPED"
ARRANGEMENT_STATUSES = (
    ARRANGEMENT_ACTIVE,
    ARRANGEMENT_SUSPENDED,
    ARRANGEMENT_STOPPED,
)

# --- Premium invoices (PRD section 3.7) -------------------------------------

INVOICE_ISSUED = "ISSUED"
INVOICE_PAID = "PAID"
INVOICE_PAST_DUE = "PAST_DUE"
INVOICE_CANCELLED = "CANCELLED"
INVOICE_WRITTEN_OFF = "WRITTEN_OFF"
INVOICE_STATUSES = (
    INVOICE_ISSUED,
    INVOICE_PAID,
    INVOICE_PAST_DUE,
    INVOICE_CANCELLED,
    INVOICE_WRITTEN_OFF,
)
INVOICE_PAYABLE_STATUSES = (INVOICE_ISSUED, INVOICE_PAST_DUE)

# "Once an enrollment carries three or more PAST_DUE invoices, the enrollment
# itself is terminated" (PRD section 3.7).
PAST_DUE_TERMINATION_THRESHOLD = 3
# "an arrears invoice's [due_date] is thirty days after its issue date".
ARREARS_DUE_DAYS = 30

# --- Plan elections (PRD section 3.8) ---------------------------------------

ELECTION_WINDOW_AEP = "AEP"
ELECTION_WINDOW_OEP_MA = "OEP_MA"
ELECTION_WINDOWS = (ELECTION_WINDOW_AEP, ELECTION_WINDOW_OEP_MA)

COVERAGE_ORIGINAL = "ORIGINAL"
COVERAGE_MA = "MA"
COVERAGE_KINDS = (COVERAGE_ORIGINAL, COVERAGE_MA)

ELECTION_GOVERNING = "GOVERNING"
ELECTION_SUPERSEDED = "SUPERSEDED"
ELECTION_EFFECTIVE = "EFFECTIVE"
ELECTION_STATUSES = (
    ELECTION_GOVERNING,
    ELECTION_SUPERSEDED,
    ELECTION_EFFECTIVE,
)

# --- Equitable relief (PRD section 3.9) -------------------------------------

RELIEF_RETROACTIVE_ENROLLMENT = "RETROACTIVE_ENROLLMENT"
RELIEF_PENALTY_WAIVER = "PENALTY_WAIVER"
RELIEF_BOTH = "BOTH"
RELIEF_TYPES = (RELIEF_RETROACTIVE_ENROLLMENT, RELIEF_PENALTY_WAIVER, RELIEF_BOTH)

RELIEF_UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
RELIEF_GRANTED = "GRANTED"
RELIEF_DENIED = "DENIED"
RELIEF_STATUSES = (RELIEF_UNDER_INVESTIGATION, RELIEF_GRANTED, RELIEF_DENIED)
RELIEF_DECISIONS = (RELIEF_GRANTED, RELIEF_DENIED)

MISINFORM_FEDERAL_AGENCY = "FEDERAL_AGENCY"
MISINFORM_PLAN_REPRESENTATIVE = "PLAN_REPRESENTATIVE"
MISINFORM_EMPLOYER = "EMPLOYER"
MISINFORM_SOURCES = (
    MISINFORM_FEDERAL_AGENCY,
    MISINFORM_PLAN_REPRESENTATIVE,
    MISINFORM_EMPLOYER,
)

# --- Pagination (PRD section 2.3) -------------------------------------------

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0

# --- Canonical rate tables --------------------------------------------------
#
# The PRD's own worked examples use these figures: a Part B standard premium
# of 18500 cents in one year and 19000 the next (section 3.4), a Part D
# national base of 3450 (section 3.4), and a SINGLE tier-1 floor of
# 10000000 cents (section 3.5).  The full six-bracket arrays are the canonical
# schedules every priced scenario publishes.

IRMAA_SINGLE_FLOORS_CENTS = (0, 10000000, 13300000, 16700000, 20000000, 50000000)
IRMAA_JOINT_FLOORS_CENTS = (0, 20000000, 26600000, 33400000, 40000000, 75000000)

RS2026_COVERAGE_YEAR = 2026
RS2026_PART_B_STANDARD_CENTS = 18500
RS2026_PART_D_NATIONAL_BASE_CENTS = 3450
RS2026_PART_B_SURCHARGES_CENTS = (0, 7400, 18500, 29590, 40680, 44390)
RS2026_PART_D_SURCHARGES_CENTS = (0, 1370, 3530, 5680, 7850, 8580)

RS2027_COVERAGE_YEAR = 2027
RS2027_PART_B_STANDARD_CENTS = 19000
RS2027_PART_D_NATIONAL_BASE_CENTS = 3600
RS2027_PART_B_SURCHARGES_CENTS = (0, 7600, 19000, 30400, 41800, 45600)
RS2027_PART_D_SURCHARGES_CENTS = (0, 1400, 3620, 5830, 8060, 8810)


# --- Rounding modes (PRD section 2.6) ---------------------------------------


def round_half_up_cents(value):
    """Round to the nearest whole cent, halves rounding up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_dime_cents(value):
    """Round to the nearest ten cents, a five-cent remainder rounding up.

    PRD section 2.6: "a value of 448.5 cents rounds to 450, and a value of
    241.5 cents rounds to 240."
    """
    dimes = (Decimal(str(value)) / Decimal(10)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return int(dimes * 10)


# --- Calendar-month arithmetic (PRD section 2.4) ----------------------------


def is_month_string(value):
    """True for a well-formed ``YYYY-MM`` calendar-month string."""
    if not isinstance(value, str) or len(value) != 7 or value[4] != "-":
        return False
    year, _, month = value.partition("-")
    return year.isdigit() and month.isdigit() and 1 <= int(month) <= 12


def add_months(year_month, count):
    """Add ``count`` calendar months to a ``YYYY-MM`` string."""
    year = int(year_month[0:4])
    month = int(year_month[5:7])
    total = year * 12 + (month - 1) + count
    return "{0:04d}-{1:02d}".format(total // 12, total % 12 + 1)


def month_diff(earlier, later):
    """Calendar months from ``earlier`` to ``later`` (negative if reversed)."""
    return (int(later[0:4]) * 12 + int(later[5:7])) - (
        int(earlier[0:4]) * 12 + int(earlier[5:7])
    )


def clock_month(to_iso8601):
    """The clock month (``YYYY-MM``) of an ISO 8601 UTC instant."""
    return to_iso8601[0:7]

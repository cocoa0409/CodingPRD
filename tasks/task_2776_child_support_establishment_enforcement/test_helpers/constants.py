"""
Domain constants for the Child Support Enforcement API test suite.

Every literal here is stated in the PRD; nothing is invented and nothing is
recomputed from an implementation. Tests import these so that a statutory
figure appears once in the suite rather than once per assertion.
"""

# ---------------------------------------------------------------------------
# API root
# ---------------------------------------------------------------------------

API_ROOT = "/child-support"

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

#: "The clock starts at the fixed instant 2026-08-01T00:00:00Z".
CLOCK_START = "2026-08-01T00:00:00Z"
CLOCK_START_DATE = "2026-08-01"

# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------

ROLE_CASE_WORKER = "CaseWorker"
ROLE_SUPERVISING_ATTORNEY = "SupervisingAttorney"
ROLE_FINANCE_OFFICER = "FinanceOfficer"
ROLE_EMPLOYER_AGENT = "EmployerAgent"
ROLE_CUSTODIAL_PARTY = "CustodialParty"
ROLE_NONCUSTODIAL_PARTY = "NoncustodialParty"
ROLE_INTERSTATE_LIAISON = "InterstateLiaison"
ROLE_PROGRAM_ADMIN = "ProgramAdmin"

ALL_ROLES = (
    ROLE_CASE_WORKER,
    ROLE_SUPERVISING_ATTORNEY,
    ROLE_FINANCE_OFFICER,
    ROLE_EMPLOYER_AGENT,
    ROLE_CUSTODIAL_PARTY,
    ROLE_NONCUSTODIAL_PARTY,
    ROLE_INTERSTATE_LIAISON,
    ROLE_PROGRAM_ADMIN,
)

# ---------------------------------------------------------------------------
# Jurisdictions
# ---------------------------------------------------------------------------

HOME_STATE_CODE = "MN"
RECOGNISED_STATE_CODES = ("MN", "TX", "NY", "WI", "FL", "CA", "PA")
SISTER_STATE_CODES = ("TX", "NY", "WI", "FL", "CA", "PA")

#: The only two states that place their own ceiling on wage withholding.
STATE_CAP_STATES = ("TX", "WI")
STATE_STATUTORY_CAP_PCT = 0.50

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

PARTICIPANT_ROLE_TYPES = ("CUSTODIAL_PARTY", "NONCUSTODIAL_PARTY")
INCOME_VERIFICATION_SOURCES = ("VERIFIED_WAGE_RECORD", "SELF_REPORTED", "NONE")
LOCATE_STATUSES = ("NOT_NEEDED", "PENDING", "LOCATED", "UNLOCATABLE")
LOCATE_OUTCOMES = ("LOCATED", "UNLOCATABLE")
LOCATE_SOURCES = (
    "FEDERAL_PLS",
    "STATE_DIRECTORY_OF_NEW_HIRES",
    "CREDIT_BUREAU",
    "EMPLOYER_TIP",
)
RISK_TIERS = ("LOW", "MEDIUM", "HIGH")

CASE_TYPES = ("PA_REFERRAL", "DIRECT_APPLICATION")
CASE_STATUSES = (
    "OPENED",
    "LOCATE",
    "PATERNITY_PENDING",
    "ORDER_ESTABLISHMENT",
    "ENFORCEMENT",
    "CLOSED",
)
ENFORCEMENT_POSTURES = ("NORMAL", "ESCALATED", "STAYED")
INTERSTATE_ROLES = ("NONE", "INITIATING", "RESPONDING")
CLOSED_REASONS = (
    "ARREARS_SATISFIED",
    "NO_JURISDICTION",
    "CP_REQUEST",
    "CHILD_EMANCIPATED",
)

PATERNITY_METHODS = ("VOLUNTARY_ACKNOWLEDGMENT", "GENETIC_TEST", "PRESUMED_MARITAL")
PATERNITY_STATUSES = (
    "PENDING",
    "AOP_SIGNED",
    "AOP_RESCINDED",
    "GENETIC_ORDERED",
    "GENETIC_COLLECTED",
    "ESTABLISHED",
    "EXCLUDED",
    "NOT_REQUIRED",
)
GENETIC_COST_LIABLE_PARTIES = ("NONE", "NCP", "STATE")

ORDER_TYPES = ("CURRENT_SUPPORT", "MEDICAL_SUPPORT")
ORDER_STATUSES = (
    "DRAFT",
    "CALCULATED",
    "PENDING_DEVIATION_FINDINGS",
    "ENTERED",
    "SUPERSEDED",
    "VACATED",
)
DEVIATION_REASONS = (
    "EXTRAORDINARY_MEDICAL",
    "SHARED_PARENTING",
    "HIGH_INCOME",
    "HARDSHIP",
)
DEVIATION_DECISIONS = ("APPROVE", "REJECT")
VACATE_REASONS = ("PATERNITY_EXCLUDED", "JURISDICTION_DEFECT", "CLERICAL_ERROR")

PAY_FREQUENCIES = ("WEEKLY", "BIWEEKLY", "SEMIMONTHLY", "MONTHLY")

IWO_SERVICE_STATUSES = ("ISSUED", "SERVED", "AMENDED", "TERMINATED")
IWO_REMITTANCE_STATUSES = ("NOT_DUE", "CURRENT", "DELINQUENT", "DEFAULTED")
IWO_TERMINATED_REASONS = (
    "EMPLOYMENT_ENDED",
    "ORDER_VACATED",
    "ORDER_SUPERSEDED",
    "SUPERSEDED_BY_NEW_IWO",
    "CASE_CLOSED",
)

CHARGE_TYPES = (
    "CURRENT_SUPPORT",
    "MEDICAL_SUPPORT",
    "ARREARS_JUDGMENT",
    "GENETIC_TEST_COST",
)
CHARGE_STATUSES = ("OPEN", "SATISFIED", "VOID")

PAYMENT_SOURCES = (
    "DIRECT_PAY",
    "TAX_REFUND_INTERCEPT",
    "LIEN_LEVY",
    "COMPROMISE_INSTALLMENT",
    "REVERSAL",
    "INCOME_WITHHOLDING",
)

REVIEW_TRIGGER_TYPES = ("PARTY_REQUEST", "PERIODIC_36_MONTH", "PA_MANDATORY")
REVIEW_STATUSES = (
    "REQUESTED",
    "INFO_PENDING",
    "THRESHOLD_MET",
    "THRESHOLD_NOT_MET",
    "ORDER_PROPOSED",
)
INFO_REQUESTED_REASONS = ("NCP_INCOME_UNVERIFIED", "CP_INCOME_UNVERIFIED")

ACTION_TYPES = (
    "LICENSE_SUSPENSION",
    "TAX_REFUND_INTERCEPT",
    "PROPERTY_LIEN",
    "CONTEMPT_REFERRAL",
    "CREDIT_BUREAU_REPORT",
)
ACTION_STATUSES = (
    "PROPOSED",
    "NOTICE_SENT",
    "CONTESTED",
    "ACTIVE",
    "DENIED",
    "RELEASED",
)
CONTEST_GROUNDS = ("MISTAKE_OF_FACT", "IDENTITY", "PAYMENT_MADE", "INABILITY_TO_PAY")
REVIEW_DECISIONS = ("UPHOLD", "VACATE")
RELEASE_REASONS = (
    "ARREARS_SATISFIED",
    "COMPROMISE_ACCEPTED",
    "ORDER_VACATED",
    "PLAN_COMPLIANT",
    "INTERCEPT_REVERSED",
)

REFERRAL_DIRECTIONS = ("INITIATING", "RESPONDING")
TRANSMITTAL_TYPES = ("ESTABLISHMENT", "ENFORCEMENT", "MODIFICATION")
REFERRAL_STATUSES = (
    "DRAFT",
    "TRANSMITTED",
    "REGISTERED",
    "ENFORCING",
    "RETURNED",
)
RETURNED_REASONS = ("NO_ACK_RECEIVED", "INSUFFICIENT_INFO", "NO_JURISDICTION")

OFFER_STATUSES = (
    "PROPOSED",
    "ACCEPTED",
    "ACTIVE",
    "COMPLETED",
    "DEFAULTED",
    "SUPERSEDED",
)

# ---------------------------------------------------------------------------
# Guideline worksheet
# ---------------------------------------------------------------------------

#: Imputed monthly income credited to an obligor with no usable income figure.
IMPUTED_MONTHLY_INCOME_CENTS = 182000
#: The self-support reserve subtracted from the obligor's guideline income.
SELF_SUPPORT_RESERVE_CENTS = 113200
#: The statutory minimum order when available income is zero or negative.
STATUTORY_MINIMUM_ORDER_CENTS = 5000
#: Ten percent credit when the obligor supports a second family.
MULTI_FAMILY_CREDIT_PCT = 0.10

#: Band ceilings on combined monthly income; the third band is unbounded.
GUIDELINE_BAND_1_CEILING_CENTS = 400000
GUIDELINE_BAND_2_CEILING_CENTS = 800000

#: Band rate by child count (1 child, 2 children, 3-or-more children).
GUIDELINE_BAND_1_RATES = (0.20, 0.28, 0.33)
GUIDELINE_BAND_2_RATES = (0.17, 0.25, 0.30)
GUIDELINE_BAND_3_RATES = (0.14, 0.21, 0.25)

#: The share ratio is rounded half up to four decimal places before use.
GUIDELINE_RATIO_DECIMAL_PLACES = 4

CHILD_COUNT_MIN = 1
CHILD_COUNT_MAX = 6

#: An order becomes review-eligible thirty-six months after its effective date.
REVIEW_ELIGIBLE_MONTHS = 36

#: A deviation must move the guideline figure by at least ten percent.
DEVIATION_MIN_PCT_NUMERATOR = 10
DEVIATION_MIN_PCT_SCALE = 100
DEVIATION_REJECTION_LIMIT = 2

#: Arrears recovery is twenty percent of the monthly obligation.
ARREARS_RECOVERY_PCT = 0.20

# ---------------------------------------------------------------------------
# Paternity
# ---------------------------------------------------------------------------

#: The rescission window opened by a notarised acknowledgment.
RESCISSION_WINDOW_DAYS = 60
#: The statute permits exactly one rescission per acknowledgment.
RESCISSION_LIMIT = 1
#: A re-drawn specimen is permitted only while the rejection count is below two.
SPECIMEN_REJECTION_LIMIT = 2
#: The cost of genetic testing, stamped by the server rather than the caller.
GENETIC_COST_CENTS = 48000
#: A probability of at least 99.0 establishes parentage.
GENETIC_ESTABLISH_THRESHOLD_PCT = 99.0
GENETIC_PROBABILITY_MIN_PCT = 0
GENETIC_PROBABILITY_MAX_PCT = 100

#: The agency's statutory ceiling on locate attempts.
MAX_LOCATE_ATTEMPTS = 3

# ---------------------------------------------------------------------------
# Interest
# ---------------------------------------------------------------------------

ANNUAL_INTEREST_RATE = 0.06
#: The annual rate divided by twelve.
MONTHLY_INTEREST_RATE = 0.005
#: "the number of grace days before interest begins is zero".
INTEREST_GRACE_DAYS = 0

# ---------------------------------------------------------------------------
# Income withholding
# ---------------------------------------------------------------------------

#: Mandatory-deduction allowance subtracted from gross to derive disposable income.
MANDATORY_DEDUCTION_PCT = 0.22
#: Federal ceiling base, and the more protective base for a second family.
FEDERAL_CAP_BASE_PCT = 0.60
FEDERAL_CAP_SECOND_FAMILY_PCT = 0.50
#: The statutory twelve-week delinquency bump.
FEDERAL_CAP_ARREARS_BUMP_PCT = 0.05
#: Arrears must be at least this multiple of the monthly obligation to bump.
FEDERAL_CAP_BUMP_ARREARS_MULTIPLE = 3
#: An employer may retain at most five dollars per payment.
MAX_REMITTANCE_FEE_CENTS = 500
#: The employer implementation period between service and the first withholding.
EMPLOYER_IMPLEMENTATION_DAYS = 14
#: Two missed cycles is employer default.
EMPLOYER_DEFAULT_MISSED_REMITTANCES = 2

# ---------------------------------------------------------------------------
# Enforcement
# ---------------------------------------------------------------------------

ENFORCEMENT_THRESHOLDS_CENTS = {
    "LICENSE_SUSPENSION": 300000,
    "PROPERTY_LIEN": 500000,
    "CONTEMPT_REFERRAL": 1000000,
    "CREDIT_BUREAU_REPORT": 100000,
}
#: TAX_REFUND_INTERCEPT is the one conditional threshold.
TAX_INTERCEPT_THRESHOLD_TANF_CENTS = 15000
TAX_INTERCEPT_THRESHOLD_NON_TANF_CENTS = 50000

#: The two-month delinquency floor applied on top of the remedy threshold.
ENFORCEMENT_OBLIGATION_MULTIPLE = 2
#: The pre-deprivation notice opens a thirty-day contest window.
CONTEST_WINDOW_DAYS = 30

#: Risk score bands, identical for both weightings.
RISK_TIER_HIGH_MIN = 67
RISK_TIER_MEDIUM_MIN = 34

#: Enforcement weighting: arrears, delinquency, payment history, locate,
#: interstate exposure, enforcement history.
ENFORCEMENT_WEIGHTS = {
    "arrears": 40,
    "delinquency": 25,
    "payment_history": 20,
    "locate": 10,
    "interstate": 5,
    "enforcement_history": 0,
}
#: Compromise weighting over the same six components.
COMPROMISE_WEIGHTS = {
    "payment_history": 40,
    "arrears": 25,
    "delinquency": 20,
    "enforcement_history": 15,
    "locate": 0,
    "interstate": 0,
}

# ---------------------------------------------------------------------------
# Ledger and allocation
# ---------------------------------------------------------------------------

#: The capped pass-through of current support on an assistance case.
TANF_PASS_THROUGH_CAP_CENTS = 10000

# ---------------------------------------------------------------------------
# Modification review
# ---------------------------------------------------------------------------

#: The relative gate: variance at least fifteen percent of the snapshot,
#: evaluated by integer cross-multiplication.
VARIANCE_RELATIVE_GATE_NUMERATOR = 1500
VARIANCE_RELATIVE_GATE_SCALE = 10000
#: The absolute gate: variance at least fifty dollars.
VARIANCE_ABSOLUTE_GATE_CENTS = 5000
#: A third information request on the same review is refused.
INFO_REQUEST_LIMIT = 2

# ---------------------------------------------------------------------------
# Compromise
# ---------------------------------------------------------------------------

INSTALLMENT_COUNT_MIN = 3
INSTALLMENT_COUNT_MAX = 36
#: Small balances are collected, not settled.
MIN_COMPROMISE_ARREARS_CENTS = 100000
#: Waiver band ceilings and their rates, keyed on the pre-waiver total.
WAIVER_TIER_1_CEILING_CENTS = 500000
WAIVER_TIER_1_PCT = 0.25
WAIVER_TIER_2_CEILING_CENTS = 2000000
WAIVER_TIER_2_PCT = 0.50
WAIVER_TIER_3_PCT = 0.75

# ---------------------------------------------------------------------------
# Interstate
# ---------------------------------------------------------------------------

#: A transmittal's acknowledgment is due ten days later.
ACK_DUE_DAYS = 10

# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
MIN_OFFSET = 0

# ---------------------------------------------------------------------------
# Identifiers that never resolve
# ---------------------------------------------------------------------------

#: A syntactically valid UUID that is never minted by the server.
MISSING_UUID = "00000000-0000-4000-8000-000000000000"

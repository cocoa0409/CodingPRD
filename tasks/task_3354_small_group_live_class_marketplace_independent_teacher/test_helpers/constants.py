"""Domain thresholds and catalogue constants (PRD §2.9, §2.10, §3.5, §3.8).

Every value here is a literal taken from the PRD's own prose, not a re-derivation:
the refund cutoffs, the fee bands, the coupon catalogue, the risk weights and the
tax-document thresholds are all stated explicitly in the requirements.
"""

# --- Logical clock (PRD §2.4) ---------------------------------------------
CURRENT_DEFAULT_UTC = "2026-09-01T00:00:00Z"

# --- Teacher onboarding (PRD §3.1) ----------------------------------------
SAMPLE_MIN_MINUTES = 5
SCREENING_VALIDITY_PERIODS = 365
APPLICATION_MAX_REVISIONS = 3
REVIEWER_SLA_PERIODS = 7

# Deterministic screening provider: a pure function of the applicant's email.
SCREENING_OUTCOME_BY_EMAIL = {
    "ada@example.com": "PASS",
    "grace@example.com": "PASS",
    "linus@example.com": "PASS",
    "alan@example.com": "FAIL",
    "edsger@example.com": "FAIL",
}
SCREENING_DEFAULT_OUTCOME = "PASS"

# --- Sections and operations sweeps (PRD §3.4, §3.9) ----------------------
AUTO_CANCEL_CUTOFF_HOURS = 24

# --- Reports and risk (PRD §3.7) ------------------------------------------
REPORT_SLA_PERIODS = 14
REPORT_MAX_PER_SECTION = 2
RISK_SUSPENSION_THRESHOLD = 40
CATEGORY_WEIGHT = {
    "CONTENT_POLICY": 25,
    "SAFETY": 40,
    "CONDUCT": 15,
    "TECHNICAL": 5,
    "OTHER": 2,
}
SEVERITY_POINTS = {"LOW": 0, "MEDIUM": 10, "HIGH": 25}

# --- Subscriptions and coupons (PRD §3.5) ---------------------------------
SUB_DISCOUNT_PCT = {"NONE": 0.00, "PLUS": 0.10, "FAMILY": 0.20}
SUBSCRIPTION_INCLUDED_CREDIT_CENTS = {"NONE": 0, "PLUS": 5000, "FAMILY": 12000}

# code -> (type, value); PERCENT values are rates, AMOUNT_CENTS values are cents.
CATALOG_COUPONS = {
    "WELCOME5": ("PERCENT", 0.05),
    "SIBLING10": ("PERCENT", 0.10),
    "SPRING15": ("PERCENT", 0.15),
    "FLAT250": ("AMOUNT_CENTS", 250),
}

# --- Refund tiers (PRD §3.6) ----------------------------------------------
REFUND_PARTIAL_RATE = 0.50
REFUND_FULL_CUTOFF_HOURS = {"ONE_TIME": 168, "MULTI_DAY": 336, "ONGOING": 336}
REFUND_HALF_CUTOFF_HOURS = {"ONE_TIME": 24, "MULTI_DAY": 72, "ONGOING": 168}
SPECIAL_REFUND_TIMEZONE = "America/Anchorage"

# --- Payouts: fees, cap and tax documents (PRD §3.8, §3.2) ----------------
# Band rates by gross: (exclusive upper bound in cents, rate); None = open ended.
FEE_BANDS = [(2000, 0.30), (5000, 0.25), (10000, 0.20), (None, 0.15)]
FORMAT_ADJUSTMENT = {"ONE_TIME": 0.00, "MULTI_DAY": -0.02, "ONGOING": -0.03}
VOLUME_DISCOUNT = 0.02
VOLUME_DISCOUNT_THRESHOLD_CENTS = 500000
FEE_RATE_FLOOR = 0.10
PAYOUT_APPROVAL_CAP_CENTS = 100000
REFUND_TEACHER_LIABILITY_RATE = 0.50
TAX_DOC_REQUIRED_CENTS = 20000
TAX_DOC_VALIDITY_CEILING_CENTS = 200000

# --- Defaults used by factories and fixtures ------------------------------
DEFAULT_TEACHER_EMAIL = "ada@example.com"
DEFAULT_APPLICANT_USER_ID = "u_ada"
DEFAULT_TEACHER_DISPLAY_NAME = "Ada Lovelace"
DEFAULT_REVIEWER_USER_ID = "rev_1"
DEFAULT_PARENT_USER_ID = "p_1"
DEFAULT_SAMPLE_URL = "https://samples.example.com/ada.mp4"
DEFAULT_SAMPLE_MINUTES = 10
DEFAULT_LEARNER_BIRTH_DATE = "2016-05-01T00:00:00Z"
DEFAULT_LIST_PRICE_CENTS = 2000
DEFAULT_SECTION_START_UTC = "2026-11-05T14:00:00Z"
DEFAULT_SECTION_END_UTC = "2026-11-05T16:00:00Z"
DEFAULT_TIMEZONE = "America/New_York"

# Non-existent but syntactically valid identifiers used by not-found tests.
MISSING_SECTION_ID = "11111111-1111-4111-8111-111111111111"
MISSING_LISTING_ID = "22222222-2222-4222-8222-222222222222"
MISSING_LISTING_ID_FOR_ANON = "33333333-3333-4333-8333-333333333333"

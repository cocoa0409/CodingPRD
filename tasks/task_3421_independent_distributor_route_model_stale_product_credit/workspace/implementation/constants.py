"""Module-scope constants for the Independent Distributor Route Model API.

Every tunable referenced anywhere in the codebase is defined HERE, before any
module imports it. Values come from SCAFFOLD.yaml calculations/constants and
PRD.md prose.
"""
from decimal import Decimal

# --- Logical clock ---------------------------------------------------------
CLOCK_DEFAULT_ISO = "2026-09-01T00:00:00Z"

# --- Auth ------------------------------------------------------------------
HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"
ROLE_COMPANY_ADMIN = "CompanyAdmin"
ROLE_ROUTE_OPS = "RouteOpsManager"
ROLE_CREDIT_ANALYST = "CreditAnalyst"
ROLE_DISTRIBUTOR = "Distributor"
ALL_ROLES = (ROLE_COMPANY_ADMIN, ROLE_ROUTE_OPS, ROLE_CREDIT_ANALYST, ROLE_DISTRIBUTOR)

# --- Pagination (PRD 2.3) ---------------------------------------------------
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0

# --- Calculation constants (SCAFFOLD 1.3) -----------------------------------
STALE_CREDIT_RATE = Decimal("0.75")
STALE_CAP_PCT = Decimal("0.10")
VIOLATION_THRESHOLD = 70
W_SHELF = Decimal("0.40")
W_ROTATION = Decimal("0.30")
W_DISPLAY = Decimal("0.30")
STRIKE_SUSPEND_THRESHOLD = 3
STRIKE_WINDOW_DAYS = 90          # trailing window; inclusive of the anchor date
DEPRECIATION_RATE = Decimal("0.02")
FOR_CAUSE_PENALTY_PCT = Decimal("0.15")
GOODWILL_PER_COMPLIANT_ACCOUNT = 50000
WEEKS_PER_YEAR = 52
DAYS_PER_YEAR = 365

# --- Business-rule windows ---------------------------------------------------
ORDER_LEAD_DAYS = 2              # delivery_date - today >= 2
CLAIM_PULL_GRACE_DAYS = 7        # pull_date <= delivery + shelf_life + 7
CLAIM_SUBMIT_WINDOW_DAYS = 2     # submit date <= pull_date + 2
CLAIM_AUTO_EXPIRE_DAYS = 3       # close denies claims created > 3 days earlier
PROBATION_NUM = 4                # trade_balance > (4/5) * credit_limit -> PROBATION
PROBATION_DEN = 5

# --- Enums -------------------------------------------------------------------
WEEKDAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
SUSPEND_REASONS = ("SERVICE_DEFAULT", "CLASSIFICATION_DISPUTE")
REINSTATE_RESOLUTIONS = ("CONFIRMED_IC", "RECLASSIFIED")
EXIT_MODES = ("VOLUNTARY", "FOR_CAUSE")
FINANCIER_TYPES = ("COMPANY", "EXTERNAL_LENDER")
DECISIONS = ("APPROVE", "DENY", "REQUEST_INFO")

# Agreement statuses that count as "non-terminal" for the overlap rule and
# for the distributor-exit check.
AGREEMENT_LIVE_STATUSES = (
    "DRAFT", "ACTIVE", "SUSPENDED_SERVICE", "SUSPENDED_CLASSIFICATION", "EXITING",
)
# Claim filing is blocked in these agreement states.
CLAIM_BLOCKED_AGREEMENT_STATUSES = ("SUSPENDED_CLASSIFICATION", "EXITING", "EXITED")

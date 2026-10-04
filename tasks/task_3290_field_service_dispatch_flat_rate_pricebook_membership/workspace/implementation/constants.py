"""Static vocabulary, tunables and the logical clock.

Nothing in this module holds entity data.  The store (store.py) starts empty on
every boot: every row a caller sees was produced by calling a declared endpoint.
"""

from datetime import datetime, timedelta, timezone

API_PREFIX = "/api"

# -- response envelope (PRD 2.2) -------------------------------------------
RESPONSE_OBJECT = "object"
RESPONSE_ARRAY = "array"
RESPONSE_ERROR = "error"

# -- pagination (PRD 2.3) ---------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# -- roles (PRD 2.1) --------------------------------------------------------
ROLE_DISPATCHER = "Dispatcher"
ROLE_TECHNICIAN = "Technician"
ROLE_MANAGER = "Manager"
ROLE_CUSTOMER_SERVICE = "CustomerService"
ROLE_PLATFORM_ADMIN = "PlatformAdmin"

ROLES = {ROLE_DISPATCHER, ROLE_TECHNICIAN, ROLE_MANAGER,
         ROLE_CUSTOMER_SERVICE, ROLE_PLATFORM_ADMIN}

# -- enumerations (PRD 2.9) -------------------------------------------------
PLAN_STATUSES = {"DRAFT", "PUBLISHED", "RETIRED"}
TASK_CATEGORIES = {"HVAC", "PLUMBING", "ELECTRICAL", "APPLIANCE", "GENERAL"}
CAMPAIGN_CHANNELS = {"SEARCH", "YARD_SIGN", "REFERRAL", "DIRECT_MAIL", "ORGANIC"}
TECH_STATUSES = {"AVAILABLE", "ON_SHIFT", "ON_JOB", "OFF_SHIFT"}
PERFORMANCE_STATUSES = {"CLEAR", "COACHING", "PROBATION"}
GRADES = {"DOES_NOT_MEET", "MEETS", "EXCEEDS", "OUTSTANDING"}
APPOINTMENT_STATUSES = {"SCHEDULED", "DISPATCHED", "COMPLETED", "CANCELLED"}
DISPATCH_STATUSES = {"UNASSIGNED", "DISPATCHED", "IN_SERVICE", "RELEASED"}
PRICING_STATUSES = {"NOT_QUOTED", "AUTO_QUOTED", "OVERRIDE_PENDING",
                    "QUOTE_APPROVED", "QUOTE_REJECTED"}
LINE_STATUSES = {"PROPOSED", "SOLD", "DECLINED"}
OPTION_TIERS = {"GOOD", "BETTER", "BEST"}
OVERRIDE_STATUSES = {"PENDING", "APPROVED", "REJECTED"}
AGREEMENT_STATUSES = {"PENDING_PAYMENT", "ACTIVE", "OVERDUE", "CANCELLED"}
VISIT_STATUSES = {"SCHEDULED", "COMPLETED", "MISSED"}
COACHING_STATUSES = {"UNREVIEWED", "COACHING_ASSIGNED", "REVIEWED"}
TERM_MONTHS_ALLOWED = {12, 24}

# -- pricing / dispatch tunables (PRD 3.5, 3.6) ----------------------------
AUTHORIZATION_CEILING_MULTIPLE = 1.20
OVERRIDE_MARKUP = 1.25
OVERRIDE_HEADROOM = 1.10
DOWN_PAYMENT_FRACTION = 0.30
DISCOUNT_FLOOR_PCT = 0.20
COMP_PREFIX_LENGTH = 3
DEFAULT_BRANCH_CAPACITY_HOURS = 80

# -- household load propagation (PRD 3.4) ----------------------------------
LOAD_BUCKET1_MAX_EXCLUSIVE = 500
LOAD_BUCKET2_MAX_EXCLUSIVE = 1500
LOAD_INCREMENT_BUCKET1 = 300
LOAD_INCREMENT_BUCKET2 = 600
LOAD_INCREMENT_BUCKET3 = 900
APPLIANCE_NUMERATOR = 115
DEFAULT_NUMERATOR = 100

# -- incentive pay (PRD 3.11) ---------------------------------------------
INCENTIVE_TIER1_UPPER_CENTS = 20000
INCENTIVE_TIER2_UPPER_CENTS = 50000
INCENTIVE_RATE_T1 = "0.02"
INCENTIVE_RATE_T2 = "0.04"
INCENTIVE_RATE_T3 = "0.06"
GROSS_CAP_CENTS = 150000
STRIKE_CHARGE_CENTS = 1500
PAY_TIER1_UPPER_CENTS = 25000
PAY_TIER2_UPPER_CENTS = 75000
PAY_RATE_T1 = "0.020"
PAY_RATE_T2 = "0.035"
PAY_RATE_T3 = "0.050"

# -- performance review (PRD 3.11) -----------------------------------------
WINDOW_DAYS = 90
BOUNDARY_MEETS_CENTS = 400000
BOUNDARY_EXCEEDS_CENTS = 600000
BOUNDARY_OUTSTANDING_CENTS = 900000

# -- description quality gate (PRD 3.7) ------------------------------------
MIN_DESCRIPTION_WORDS = 10
WORDS_PER_MINUTE_FRACTION = "0.05"

# -- marketing (PRD 3.12) --------------------------------------------------
CONVERSION_SCALE = 3

# -- logical clock (PRD 2.4) -----------------------------------------------
CLOCK_START_ISO = "2026-09-01T00:00:00Z"
CLOCK_START = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


class LogicalClock:
    """The only source of 'now' in the system; never falls back to wall time."""

    def __init__(self):
        self._now = CLOCK_START

    def now(self):
        return self._now

    def set(self, value):
        self._now = value


clock = LogicalClock()


def days(delta):
    return timedelta(days=delta)
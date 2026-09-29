"""Business constants for the Neighborhood Swim Club API.

Every figure here traces to a pinned number in PRD.md (§2, §3) or to the
`constants` block of the matching entry in SCAFFOLD.yaml `calculations`.
"""
from decimal import Decimal

API_PREFIX = "/swim-club"

# ---------------------------------------------------------------- roles (§2.1)
ROLES = (
    "Member",
    "MembershipChair",
    "PoolManager",
    "SwimTeamCoach",
    "HealthInspector",
    "Treasurer",
    "BoardPresident",
    "SystemOperator",
)

HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"

# ------------------------------------------------------- logical clock (§2.5)
CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00.000Z"

# ------------------------------------------------------------- pagination (§2.3)
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0

# ------------------------------------------------------------------- enums
SEASON_STATUS = ("PLANNED", "OPEN", "CLOSED")
FACILITY_POSTURE = ("OPEN", "RESTRICTED", "CLOSED")
PRORATION_BASIS = ("CALENDAR_DAY", "SWIM_WEEK")
GUEST_SETTLEMENT_POLICY = ("PASS_FIRST", "FEE_FIRST_ON_WEEKEND")
CATEGORY_CODE = ("FAMILY", "COUPLE", "SINGLE", "SENIOR", "SWIM_TEAM_ONLY")
RESIDENCY = ("IN_DISTRICT", "OUT_OF_DISTRICT")
BOND_STATUS = ("NONE", "INSTALLMENTS", "PAID", "TRANSFERRED")
HOUSEHOLD_STANDING = ("GOOD_STANDING", "PROBATION", "SUSPENDED", "EXPELLED")
PRIORITY_TIER = ("LEGACY", "SIBLING", "STANDARD")
PRIORITY_TIER_RANK = {"LEGACY": 0, "SIBLING": 1, "STANDARD": 2}
WAITLIST_STATUS = ("WAITING", "OFFERED", "ACCEPTED", "DECLINED", "EXPIRED", "WITHDRAWN")
WAITLIST_DECISION = ("ACCEPT", "DECLINE", "WITHDRAW")
BOND_PAYMENT_PLAN = ("FULL", "INSTALLMENTS", "TRANSFERRED")
DUES_STATUS = ("UNBILLED", "INVOICED", "PAID", "DELINQUENT", "WRITTEN_OFF")
ACCESS_STATUS = ("PENDING", "ACTIVE", "SUSPENDED", "LAPSED", "TERMINATED")
MEMBERSHIP_PAYMENT_ALLOCATION = ("DUES", "BOND")
HOUSEHOLD_PAYMENT_ALLOCATION = ("GUEST_FEES", "PARTY_CHARGES", "BOND")
GUEST_VISIT_STATUS = ("RECORDED", "VOIDED")
CERT_TYPE = ("LIFEGUARD", "CPR_AED", "WSI", "POOL_OPERATOR")
CERT_STATUS = ("VALID", "EXPIRED", "REVOKED", "SUPERSEDED")
EMPLOYMENT_STATUS = ("ACTIVE", "INACTIVE")
SHIFT_ROLE = ("PRIMARY", "SECONDARY", "SUPERVISOR")
SHIFT_STATUS = (
    "SCHEDULED",
    "CONFIRMED",
    "COMPLETED",
    "CANCELLED",
    "NO_SHOW",
    "CANCELLED_BY_CLOSURE",
)
SQUAD = ("MINI", "JUNIOR", "SENIOR")
REGISTRATION_STATUS = (
    "PENDING",
    "CONFIRMED",
    "WAITLISTED",
    "WITHDRAWN",
    "REVOKED",
    "COMPLETED",
)
MEET_STATUS = ("SCHEDULED", "STAFFED", "UNDERSTAFFED", "HOSTED", "CANCELLED")
JOB_CODE = ("TIMER", "STARTER", "CONCESSIONS", "MARSHAL", "SCORER")
ASSIGNMENT_STATUS = ("ASSIGNED", "COMPLETED", "NO_SHOW", "RELEASED")
ZONE = ("PAVILION", "SHALLOW_END", "WHOLE_FACILITY")
RESERVATION_STATUS = (
    "REQUESTED",
    "CONFIRMED",
    "COMPLETED",
    "REJECTED",
    "CANCELLED_BY_HOST",
    "CANCELLED_BY_CLOSURE",
    "CANCELLED_BY_SUSPENSION",
)
FINDING_SEVERITY = ("CRITICAL", "MAJOR", "MINOR")
FINDING_STATUS = ("OPEN", "REMEDIATION_SUBMITTED", "REOPENED", "VERIFIED_CLOSED")
CONDUCT_SEVERITY = ("MINOR", "MAJOR", "SEVERE")
CONDUCT_STATUS = (
    "REPORTED",
    "UNDER_REVIEW",
    "SANCTIONED",
    "APPEALED",
    "DISMISSED",
    "CLOSED",
)
SANCTION_TYPE = ("WARNING", "PROBATION", "SUSPENSION", "EXPULSION")
PROJECT_KIND = ("POOL_RESURFACING", "PUMP_REPLACEMENT")
PROJECT_STATUS = (
    "PROPOSED",
    "APPROVED",
    "FUNDED",
    "IN_PROGRESS",
    "COMPLETED",
    "REJECTED",
    "CANCELLED",
)

# ------------------------------------------------------- season defaults (§3.1)
BASELINE_BATHER_LOAD_DEFAULT = 10
BATHER_LOAD_CAPACITY_DEFAULT = 120
SEASON_YEAR_MIN = 2026
SEASON_YEAR_MAX = 2099

# ---------------------------------------------- facility posture (§3.1)
MAJOR_FINDING_RESTRICT_THRESHOLD = 2
RESTRICTED_MAX_GUESTS_PER_VISIT = 2

# ------------------------------------------------- seasonal dues (§3.3)
DAYS_PER_SWIM_WEEK = 7

# -------------------------------------------------------- invoice (§3.4)
BOND_INSTALLMENT_RATE = Decimal("0.25")
LATE_PENALTY_RATE = Decimal("0.035")

# ------------------------------------------------------ guest gate (§3.5)
GUEST_FEE_WEEKDAY_CENTS = 500
GUEST_FEE_WEEKEND_CENTS = 800
MAX_GUESTS_PER_VISIT = 6

# ------------------------------------------------------- swim team (§3.6)
SWIM_TEAM_FEE_CENTS = 14500
MULTI_SWIMMER_DISCOUNT_RATE = Decimal("0.0625")
MULTI_SWIMMER_DISCOUNT_CAP = Decimal("0.25")
SQUAD_CAPACITY = {"MINI": 20, "JUNIOR": 30, "SENIOR": 30}
JOB_CREDIT_VALUES = {
    "TIMER": 1,
    "STARTER": 2,
    "CONCESSIONS": 1,
    "MARSHAL": 1,
    "SCORER": 2,
}
VOLUNTEER_CREDIT_CAP = 10
VOLUNTEER_BUYOUT_PER_CREDIT_CENTS = 3500
MEET_UNDERSTAFF_PENALTY_CENTS = 7500

# ----------------------------------------------------------- parties (§3.7)
GUARD_BATHER_RATIO = 25
MIN_GUARDS_WHEN_OPEN = 1
GUARD_HOURLY_CENTS = 2200
INCLUDED_GUESTS = 10
GUEST_OVERAGE_CENTS = 700
DISCOUNT_TIER_1_CENTS = 25000
DISCOUNT_TIER_2_CENTS = 45000
DISCOUNT_RATE_TIER_1 = Decimal("0.10")
DISCOUNT_RATE_TIER_2 = Decimal("0.15")
PARTY_HALF_REFUND_RATE = Decimal("0.5")
ZONE_BASE_FEE_CENTS = {"PAVILION": 6000, "SHALLOW_END": 9000, "WHOLE_FACILITY": 20000}
CANCEL_FULL_REFUND_DAYS = 7

# --------------------------------------------------------- the deck (§3.8)
SHIFT_REST_BUFFER_MINUTES = 30

# --------------------------------------------------------- conduct (§3.9)
CONDUCT_LOOKBACK_DAYS = 730
CONDUCT_POINTS = {"MINOR": 2, "MAJOR": 4, "SEVERE": 8}
CONDUCT_SUSPENSION_THRESHOLD = 6
CONDUCT_EXPULSION_THRESHOLD = 10
STANDING_RANK = {"GOOD_STANDING": 0, "PROBATION": 1, "SUSPENDED": 2, "EXPELLED": 3}
SANCTION_TO_STANDING = {
    "WARNING": "GOOD_STANDING",
    "PROBATION": "PROBATION",
    "SUSPENSION": "SUSPENDED",
    "EXPULSION": "EXPELLED",
}
APPEAL_WINDOW_DAYS = 10
MAX_APPEALS = 2

# --------------------------------------------------- capital reserve (§3.10)
RESERVE_CONTRIBUTION_PER_MEMBERSHIP_CENTS = 5000

# ------------------------------------------------------- waitlist (§3.2)
OFFER_WINDOW_DAYS = 14
MAX_DEFERRALS = 2

# ------------------------------------------------------------- fiscal (§3.4)
DELINQUENCY_TOLERANCE_CENTS = 0

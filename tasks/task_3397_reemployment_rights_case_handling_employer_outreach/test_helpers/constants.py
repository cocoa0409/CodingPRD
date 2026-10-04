"""Domain constants for the Reemployment Rights Mediation API.

Every value here is a literal the PRD states verbatim. Tests import these
instead of re-typing magic numbers, so a boundary case such as "exactly
1,825 cumulative chargeable days" reads as the rule it exercises.
"""

# ── Logical clock ──────────────────────────────────────────────────────────
# On a fresh deployment the logical clock reads exactly this instant and only
# moves when a ProgramCoordinator sets it through the clock endpoint.
CLOCK_STARTUP_DEFAULT = "2026-09-01T00:00:00Z"

# ── Roles (X-User-Role header values, spelled exactly) ─────────────────────
ROLE_ANONYMOUS = "Anonymous"
ROLE_SERVICE_MEMBER = "ServiceMember"
ROLE_EMPLOYER = "Employer"
ROLE_OMBUDSMAN = "Ombudsman"
ROLE_PROGRAM_COORDINATOR = "ProgramCoordinator"
ROLE_AGENCY_REVIEWER = "AgencyReviewer"

ALL_ROLES = (
    ROLE_ANONYMOUS,
    ROLE_SERVICE_MEMBER,
    ROLE_EMPLOYER,
    ROLE_OMBUDSMAN,
    ROLE_PROGRAM_COORDINATOR,
    ROLE_AGENCY_REVIEWER,
)

# ── Pagination ─────────────────────────────────────────────────────────────
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ── Statutory eligibility analysis ─────────────────────────────────────────
# Advance notice: STRICT requires notice at least this many hours before start.
NOTICE_MIN_HOURS = 24

# Five-year cumulative cap on chargeable service; exactly this many days passes.
FIVE_YEAR_CAP_DAYS = 1825

# Duration bands keyed on the disputed period's whole-day length.
BAND_SHORT_MAX_DAYS = 30
BAND_MID_MAX_DAYS = 180

# Application deadline (days after the disputed period's end_date) per band.
DEADLINE_DAYS_SHORT = 1
DEADLINE_DAYS_MID = 14
DEADLINE_DAYS_LONG = 90

DURATION_BAND_DEADLINE_DAYS = {
    "SHORT": DEADLINE_DAYS_SHORT,
    "MID": DEADLINE_DAYS_MID,
    "LONG": DEADLINE_DAYS_LONG,
}

ESCALATOR_BY_BAND = {
    "SHORT": "SAME_POSITION",
    "MID": "SENIORITY_ESCALATED",
    "LONG": "ESCALATED_WITH_RETRAINING",
}

# Orders categories exempt from the five-year cumulative cap.
CAP_EXEMPT_ORDERS = ("NATIONAL_EMERGENCY", "PRESIDENTIAL_CALLUP")

# ── Benefits mathematics ───────────────────────────────────────────────────
# One month is exactly 30.44 days; month-valued results round half-up to 2dp.
DAYS_PER_MONTH = 30.44
HEALTH_CAP_MONTHS = 24

# ── Ombudsman caseload ─────────────────────────────────────────────────────
# Assignment is rejected once the ombudsman's active caseload reaches this.
MAX_ACTIVE_CASELOAD = 4

# ── Program windows (days) ─────────────────────────────────────────────────
RESPONSE_WINDOW_DAYS = 14
REFERRAL_WINDOW_DAYS = 30
REOPEN_WINDOW_DAYS = 60

# ── Training and certification ─────────────────────────────────────────────
CERT_MIN_HOURS = 20
RECERT_MIN_HOURS = 8
EXAM_PASS_SCORE = 80
CERTIFICATION_TERM_MONTHS = 24
RECERT_WINDOW_MONTHS = 24
CORE_MODULES = ("CORE_LAW", "MEDIATION_SKILLS", "DOCUMENTATION")

# ── Statements of support ──────────────────────────────────────────────────
STATEMENT_DEFAULT_TERM_MONTHS = 24

# ── Employer recognition scoring ───────────────────────────────────────────
POINTS_PER_RESOLVED_CASE = 10
POINTS_SIGNED_STATEMENT = 15
PENALTY_PER_OPEN_CASE = 10

TIER_GATE_BASE_BRONZE = 20
TIER_GATE_BASE_SILVER = 40
TIER_GATE_BASE_GOLD = 60

AWARD_TIER_GATE_BASE = {
    "BRONZE": TIER_GATE_BASE_BRONZE,
    "SILVER": TIER_GATE_BASE_SILVER,
    "GOLD": TIER_GATE_BASE_GOLD,
}

BONUS_BRONZE = 5
BONUS_SILVER = 15
BONUS_GOLD = 30

AWARD_BONUS_BY_TIER = {
    "BRONZE": BONUS_BRONZE,
    "SILVER": BONUS_SILVER,
    "GOLD": BONUS_GOLD,
}

# Vetting gates: minimum resolved_case_count per nominated tier.
VET_RESOLVED_GATE_BRONZE = 1
VET_RESOLVED_GATE_SILVER = 3
VET_RESOLVED_GATE_GOLD = 5

AWARD_VET_RESOLVED_GATE = {
    "BRONZE": VET_RESOLVED_GATE_BRONZE,
    "SILVER": VET_RESOLVED_GATE_SILVER,
    "GOLD": VET_RESOLVED_GATE_GOLD,
}

# ── Outreach events ────────────────────────────────────────────────────────
# A venue is double-booked when intervals overlap including this teardown
# buffer after each event; unlike service periods, touching counts as overlap.
VENUE_TEARDOWN_BUFFER_MINUTES = 60

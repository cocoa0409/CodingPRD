"""Domain constants for the model-law / accreditation / filings API.

Every numeric value below is transcribed from the requirements document (the
section each value comes from is cited inline). Timestamps derived from the
logical clock are computed off its pinned start instant so no fixture can anchor
before the clock begins.
"""

from datetime import datetime, timedelta

# --- Roles (PRD section 2.1: six declared roles, spellings fixed) ------------
ROLE_ASSOCIATION_STAFF = "AssociationStaff"
ROLE_ACTUARY = "Actuary"
ROLE_STATE_REGULATOR = "StateRegulator"
ROLE_INSURER_USER = "InsurerUser"
ROLE_PRODUCER_USER = "ProducerUser"
ROLE_REVIEW_TEAM_LEAD = "ReviewTeamLead"

ALL_ROLES = (
    ROLE_ASSOCIATION_STAFF,
    ROLE_ACTUARY,
    ROLE_STATE_REGULATOR,
    ROLE_INSURER_USER,
    ROLE_PRODUCER_USER,
    ROLE_REVIEW_TEAM_LEAD,
)

# --- Logical clock (PRD 2.4) --------------------------------------------------
# "Before any request has been processed, the clock reads exactly
# 2026-09-01T00:00:00Z."
CLOCK_START_INSTANT = "2026-09-01T00:00:00Z"

_ISO_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def _parse_instant(value: str) -> datetime:
    return datetime.strptime(value, _ISO_FORMAT)


def format_instant(moment: datetime) -> str:
    """Render a datetime the way the logical clock reads (whole seconds, Z)."""
    return moment.strftime(_ISO_FORMAT)


def days_after(instant: str, days: int) -> str:
    """The instant ``days`` days after ``instant`` (both whole-second ISO UTC)."""
    return format_instant(_parse_instant(instant) + timedelta(days=days))


def days_after_clock_start(days: int) -> str:
    """An instant ``days`` after the clock's pinned start instant."""
    return days_after(CLOCK_START_INSTANT, days)


# --- Pagination (PRD 2.3) -----------------------------------------------------
# "The limit parameter defaults to 10, with a minimum of 1 and a maximum of 100;
# offset defaults to 0."
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# --- Ballot adoption rule (PRD 3.1) -------------------------------------------
# "Quorum is the smallest whole number that is at least 60 percent of that
# eligible count." / "the smallest whole number that is at least two-thirds of
# votes_cast"
QUORUM_PCT = 0.60
SUPERMAJORITY_NUM = 2
SUPERMAJORITY_DEN = 3

# --- Exposure drafts (PRD 3.1) ------------------------------------------------
# "the window length must span at least 30 days"
MIN_COMMENT_DAYS = 30

# --- Accreditation reviews (PRD 3.2 / 3.3) ------------------------------------
# "PASS when the onsite score is at least 75.0"
PASS_THRESHOLD = 75.0
# Coverage-triggered reviews: "a period running from the current clock to 180
# days later"
AUTO_REVIEW_PERIOD_DAYS = 180
# "the gap between the new period_start and the most recent prior period_end of
# that state must be at least 180 days"
MIN_REVIEW_GAP_DAYS = 180

# --- Core-act coverage (PRD 3.2) ----------------------------------------------
# "whose recomputed coverage has fallen below 50.0 percent" triggers an
# auto-created review; "When no published core act exists the coverage reads
# 100.0"
MIN_COVERAGE_PCT = 50.0
COVERAGE_WHEN_NO_CORE_ACTS = 100.0

# --- Risk-based capital action levels (PRD 3.4) -------------------------------
# "at least 2.0000 maps to NONE; at least 1.5000 but below 2.0000 to
# COMPANY_ACTION; at least 1.0000 but below 1.5000 to REGULATORY_ACTION; at
# least 0.7000 but below 1.0000 to AUTHORIZED_CONTROL; and anything below
# 0.7000 to MANDATORY_CONTROL"
RBC_NONE_FLOOR = 2.0
RBC_COMPANY_ACTION_FLOOR = 1.5
RBC_REGULATORY_ACTION_FLOOR = 1.0
RBC_AUTHORIZED_CONTROL_FLOOR = 0.7

# The validation edits a filing is run against (PRD 3.4): "always a subset of
# E101, E103, E106, and E107"
VALIDATION_EDIT_IDS = ("E101", "E103", "E106", "E107")

# --- Market conduct calls (PRD 3.7) -------------------------------------------
# "a total_cost_cents examination cost pool that must be at least 100000 cents"
MIN_CALL_COST_CENTS = 100000
# "any response whose pass-one share falls below 5 percent is excluded"
MIN_SHARE_PCT = 0.05
# "one hundred million times complaint_count divided by direct_premium_cents"
COMPLAINT_RATE_MULTIPLIER = 100000000
# "caps that rate at 50, and multiplies the capped rate by a weight of 0.5"
COMPLAINT_CAP = 50
COMPLAINT_WEIGHT = 0.5
# "when the insurer has no validated filing and the ratio is null, it
# contributes a neutral 25 points"
NEUTRAL_RBC_POINTS = 25
# RBC tiers: "below 0.7000 contributes 50 points, below 1.0000 contributes 35,
# below 1.5000 contributes 20, below 2.0000 contributes 10, and a ratio of at
# least 2.0000 contributes nothing"
EXAM_RBC_TIER_POINTS = (50, 35, 20, 10, 0)
# Share tiers: "a share of at least 25 percent contributes 20 points, a share of
# at least 10 percent but under 25 contributes 10, and anything smaller
# contributes nothing"
SHARE_TIER_HIGH = 0.25
SHARE_TIER_HIGH_POINTS = 20
SHARE_TIER_LOW = 0.10
SHARE_TIER_LOW_POINTS = 10
# "The score is the sum of the three components, capped at 100"
SCORE_CAP = 100

# --- Common default datetimes (all at or after the clock start) ---------------
# First exposure window: exactly the 30-day minimum, anchored at clock start.
DEFAULT_EXPOSURE_START = CLOCK_START_INSTANT                       # 2026-09-01
DEFAULT_EXPOSURE_END = days_after_clock_start(30)                  # 2026-10-01
# A disjoint second window for revision rounds.
SECOND_EXPOSURE_START = days_after_clock_start(61)                 # 2026-11-01
SECOND_EXPOSURE_END = days_after_clock_start(91)                   # 2026-12-01

# Default accreditation-review period (pure caller-supplied data; the gap rule
# spaces successive periods of the same state by at least 180 days).
DEFAULT_REVIEW_PERIOD_START = CLOCK_START_INSTANT                  # 2026-09-01
DEFAULT_REVIEW_PERIOD_END = days_after_clock_start(120)            # 2026-12-30

# Default adoption enactment date.
DEFAULT_ENACTED_ON = days_after_clock_start(61)                    # 2026-11-01

# Default producer-license window.
DEFAULT_LICENSE_EFFECTIVE_FROM = days_after_clock_start(122)       # 2027-01-01
DEFAULT_LICENSE_VALID_UNTIL = days_after_clock_start(487)          # 2028-01-01

# --- Default operator identifiers for opaque roles ----------------------------
ASSOCIATION_STAFF_USER_ID = "staff-1"
AUTHOR_ACTUARY_USER_ID = "actuary-1"
ACTIVATOR_ACTUARY_USER_ID = "actuary-2"
THIRD_ACTUARY_USER_ID = "actuary-3"
REVIEW_LEAD_USER_ID = "lead-1"
SECOND_REVIEW_LEAD_USER_ID = "lead-2"
THIRD_REVIEW_LEAD_USER_ID = "lead-3"

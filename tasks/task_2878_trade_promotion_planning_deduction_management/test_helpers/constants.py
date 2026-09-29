"""
Domain constants for the Trade Promotion Deductions API test suite.

Every threshold below is the literal declared by the PRD; the calendar helpers
exist because the PRD requires Monday-aligned, half-open fiscal weeks and a
logical clock that starts at a fixed instant.
"""

from datetime import date, datetime, timedelta, timezone

# ─── Logical clock ────────────────────────────────────

DEFAULT_CLOCK_INSTANT = "2026-08-01T00:00:00Z"

# ─── Numeric thresholds declared by the PRD ───────────

MAX_REVISION_ROUNDS = 2
MAX_DISPUTE_ROUNDS = 2
TPR_CONCURRENCY_CAP = 2
FEATURE_COOLDOWN_DAYS = 7
AGING_ESCALATION_DAYS = 90
SHIPMENT_ACCRUAL_LEAD_DAYS = 14
POST_WINDOW_DAYS = 14
TRAILING_WINDOW_DAYS = 28
TRAILING_WEEKS = 4
POST_PERIOD_EXPECTED_WEEKS = 2

WRITE_OFF_SELF_APPROVAL_LIMIT = 500.00

# Off-invoice allowance bands, read against `tactic_subtotal_amount`.
ALLOWANCE_BAND_MID_FLOOR = 10000.00
ALLOWANCE_BAND_HIGH_FLOOR = 50000.00
ALLOWANCE_RATE_LOW = 0.000
ALLOWANCE_RATE_MID = 0.020
ALLOWANCE_RATE_HIGH = 0.035

# Spend-status boundaries on `spend_ratio`.
OVERSPEND_WARNING_RATIO = 0.9000
OVERSPENT_RATIO = 1.0000

# Compliance penalty ledger.
PENALTY_POINTS_RESTRICTED_ALLOCATION = 10
PENALTY_POINTS_DISPUTE_ESCALATION = 5
PENALTY_POINTS_FINDINGS_ISSUED = 10
CREDIT_HOLD_POINT_THRESHOLD = 10
SUSPENDED_POINT_THRESHOLD = 25
AUTO_CREDIT_HOLD_REASON_PREFIX = "AUTO: compliance penalty points"

# Performance rating boundary on `roi`.
ON_TRACK_ROI = 1.0000

# Pagination bounds.
DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100

# A syntactically valid UUID that is never minted by the service.
NEVER_MINTED_UUID = "11111111-1111-4111-8111-111111111111"

# ─── Fiscal-week calendar ─────────────────────────────

# Mondays around the default clock instant, usable as window boundaries.
MONDAY_JUL_06 = "2026-07-06"
MONDAY_JUL_13 = "2026-07-13"
MONDAY_JUL_20 = "2026-07-20"
MONDAY_JUL_27 = "2026-07-27"
MONDAY_AUG_03 = "2026-08-03"
MONDAY_AUG_10 = "2026-08-10"
MONDAY_AUG_17 = "2026-08-17"
MONDAY_AUG_24 = "2026-08-24"
MONDAY_AUG_31 = "2026-08-31"
MONDAY_SEP_07 = "2026-09-07"
MONDAY_SEP_14 = "2026-09-14"
MONDAY_SEP_21 = "2026-09-21"
MONDAY_SEP_28 = "2026-09-28"
MONDAY_OCT_05 = "2026-10-05"

NON_MONDAY_DATE = "2026-08-04"  # a Tuesday

TEST_DEFAULTS = {
    "fiscal_year": 2026,
    "program_budget": 1000000.00,
    "allocation_amount": 100000.00,
    "promotion_window_start": MONDAY_AUG_03,
    "promotion_window_end": MONDAY_AUG_31,
    "rate_per_case": 1.250,
    "fixed_fee": 4000.00,
    "planned_units": 2000,
}


def monday_plus_weeks(monday: str, weeks: int) -> str:
    """Return the ISO date `weeks` fiscal weeks after the supplied Monday."""
    return (date.fromisoformat(monday) + timedelta(days=7 * weeks)).isoformat()


def date_plus_days(iso_date: str, days: int) -> str:
    """Return the ISO date `days` days after the supplied ISO date."""
    return (date.fromisoformat(iso_date) + timedelta(days=days)).isoformat()


def instant(iso_date: str, hour: int = 0, minute: int = 0, second: int = 0) -> str:
    """Build an ISO 8601 UTC instant with three fractional digits from a date."""
    moment = datetime.fromisoformat(iso_date).replace(
        hour=hour, minute=minute, second=second, tzinfo=timezone.utc
    )
    return moment.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def instant_plus_days(base_instant: str, days: int) -> str:
    """Shift an ISO 8601 UTC instant forward by whole days, keeping the format."""
    cleaned = base_instant.replace("Z", "+00:00")
    moment = datetime.fromisoformat(cleaned) + timedelta(days=days)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def week_count(window_start: str, window_end: str) -> int:
    """Whole fiscal weeks spanned by a half-open Monday-aligned window."""
    delta = date.fromisoformat(window_end) - date.fromisoformat(window_start)
    return delta.days // 7

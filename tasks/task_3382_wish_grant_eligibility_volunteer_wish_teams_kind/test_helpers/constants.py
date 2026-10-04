"""Domain thresholds and canonical values for the Wish Grant API.

All numeric constants come from the PRD's calculation rules; all money
is integer cents. Also includes pure-python reference implementations of
the PRD formulas so tests can compute expected values without re-deriving.
"""
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

# Startup default of the server logical clock (PRD: never wall-clock time).
DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Age thresholds (complete calendar months)
# ---------------------------------------------------------------------------

MIN_INTAKE_AGE_MONTHS = 30                # intake eligible iff age >= 30
MAX_INTAKE_AGE_MONTHS_EXCLUSIVE = 216     # intake/determination require age < 216
SELF_REFERRAL_MIN_AGE_MONTHS = 156        # SELF referrals require age >= 156

# Visit-method age bands (months at the visit's scheduled_start)
PLAY_ONLY_BELOW_MONTHS = 72               # m < 72 -> PLAY_BASED only
INTERVIEW_FROM_MONTHS = 156               # m >= 156 -> INTERVIEW only
# 72 <= m < 156 -> PLAY_BASED or DRAWING

# ---------------------------------------------------------------------------
# Urgency / scheduling
# ---------------------------------------------------------------------------

URGENT_PROGNOSIS_MONTHS = 6   # prognosis_months <= 6 -> RAPID (inclusive)
RAPID_SLA_DAYS = 14           # event_start_date <= date(determined_at) + 14 (inclusive)

# ---------------------------------------------------------------------------
# Donation valuation / chapter fiscal thresholds
# ---------------------------------------------------------------------------

PARTNER_DECLARED_CAP_PCT = 80   # cap = round_half_up(unit_retail_cents * 80 / 100)
BUDGET_FREEZE_THRESHOLD_PCT = 95  # posture FROZEN when committed >= floor(budget * 95 / 100)

# ---------------------------------------------------------------------------
# Canonical fixture values (used across the design indices)
# ---------------------------------------------------------------------------

CANONICAL_CHILD_DOB = "2016-03-10"   # 125 complete months at the default clock
CANONICAL_CHILD_AGE_MONTHS = 125
CANONICAL_CHILD_NAME = "Lila Monroe"
CANONICAL_CHILD_ZIP = "90012"

SECOND_CHILD_DOB = "2015-06-15"      # 134 months at 2026-09-06 visit start
SECOND_CHILD_NAME = "Theo Alvarez"
SECOND_CHILD_ZIP_SUFFIX = "44"       # pair with chapter prefix to form the zip

DEFAULT_CHAPTER_NAME = "Metro Chapter"
DEFAULT_ZIP_PREFIX = "900"
DEFAULT_FISCAL_YEAR_BUDGET_CENTS = 2_000_000
DEFAULT_TARGET_AVG_COST_PER_WISH_CENTS = 800_000

DEFAULT_VISIT_START = "2026-09-05T09:00:00Z"
DEFAULT_VISIT_END = "2026-09-05T11:00:00Z"

DEFAULT_EVENT_START_DATE = "2026-10-01"
DEFAULT_EVENT_END_DATE = "2026-10-02"

DEFAULT_OFFER_VALID_FROM = "2026-08-01"
DEFAULT_OFFER_VALID_UNTIL = "2026-12-31"

# Auto-denial reason stamped by the system on NON_QUALIFYING certification.
AUTO_DENIAL_REASON = "CONDITION_NOT_QUALIFYING"

# Donation category allowed per wish type (PRD fulfillment-path mapping).
CATEGORY_BY_WISH_TYPE = {
    "TRAVEL": ("AIRLINE", "RESORT"),
    "RECEIVE_ITEM": ("RETAILER",),
    "MEET_PERSON": ("SPONSOR",),
    "BE_SOMETHING": ("SPONSOR", "RETAILER"),
}


# ---------------------------------------------------------------------------
# Reference implementations of the PRD formulas
# ---------------------------------------------------------------------------

def round_half_up(value) -> int:
    """Round a numeric value to the nearest integer, halves away from zero."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_age_months(dob: str, ref_date: str) -> int:
    """Complete calendar months from dob (YYYY-MM-DD) to ref_date (YYYY-MM-DD).

    PRD formula: (ref.year - dob.year) * 12 + (ref.month - dob.month)
                 - (1 if ref.day < dob.day else 0)
    """
    y1, m1, d1 = (int(p) for p in dob.split("-"))
    y2, m2, d2 = (int(p) for p in ref_date.split("-"))
    return (y2 - y1) * 12 + (m2 - m1) - (1 if d2 < d1 else 0)


def date_of(iso_timestamp: str) -> str:
    """Extract the YYYY-MM-DD calendar date from an ISO 8601 UTC timestamp."""
    return iso_timestamp[:10]


def add_days(date_str: str, days: int) -> str:
    """Add whole days to a YYYY-MM-DD date string."""
    d = date.fromisoformat(date_str) + timedelta(days=days)
    return d.isoformat()


def rapid_sla_deadline_date(determined_at_iso: str) -> str:
    """RAPID scheduling deadline: date(determined_at) + RAPID_SLA_DAYS (inclusive)."""
    return add_days(date_of(determined_at_iso), RAPID_SLA_DAYS)


def clock_date(clock_iso: str = DEFAULT_CLOCK_ISO) -> str:
    """Calendar date of a logical-clock ISO instant."""
    return date_of(clock_iso)


def partner_declared_cap_cents(unit_retail_cents: int) -> int:
    """PARTNER_DECLARED cap: round_half_up(unit_retail_cents * 80 / 100)."""
    return round_half_up(unit_retail_cents * PARTNER_DECLARED_CAP_PCT / 100)


def expected_fmv_unit_cents(valuation_method: str,
                            unit_retail_cents: int,
                            partner_declared_unit_cents=None) -> int:
    """Expected DonationOffer.fmv_unit_cents per the valuation variant."""
    if valuation_method == "RETAIL_BASIS":
        return unit_retail_cents
    if valuation_method == "PARTNER_DECLARED":
        return min(partner_declared_unit_cents,
                   partner_declared_cap_cents(unit_retail_cents))
    raise ValueError(f"unknown valuation_method: {valuation_method}")


def budget_freeze_threshold_cents(fiscal_year_budget_cents: int) -> int:
    """FROZEN threshold: floor(budget * 95 / 100). Equality freezes."""
    return (fiscal_year_budget_cents * BUDGET_FREEZE_THRESHOLD_PCT) // 100


def expected_avg_cents(total_cents: int, count: int) -> int:
    """Chapter average: round_half_up(total / count); 0 when count == 0."""
    if count == 0:
        return 0
    return round_half_up(total_cents / count)


def projected_avg_cents(granted_cost_total_cents: int,
                        plan_total_cost_cents: int,
                        granted_wish_count: int) -> int:
    """Escalation projection: pre-approval totals plus this plan exactly once."""
    return expected_avg_cents(granted_cost_total_cents + plan_total_cost_cents,
                              granted_wish_count + 1)


def allowed_visit_methods(age_months: int) -> tuple:
    """Visit methods allowed for a child of the given age in complete months."""
    if age_months < PLAY_ONLY_BELOW_MONTHS:
        return ("PLAY_BASED",)
    if age_months < INTERVIEW_FROM_MONTHS:
        return ("PLAY_BASED", "DRAWING")
    return ("INTERVIEW",)


def normalize_child_name(full_name: str) -> str:
    """Duplicate-detection normalization: lowercase, trim, collapse whitespace."""
    return " ".join(full_name.split()).lower()

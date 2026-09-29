"""Domain thresholds and calendar conventions used by the Preschool Child Find API."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

# --- statutory age window on referral intake (PRD §3.3)
AGE_MIN_MONTHS = 33
AGE_MAX_MONTHS = 71
PART_C_PATHWAY_MAX_AGE_MONTHS = 35

# --- evaluation deadline (PRD §3.3)
EVAL_WINDOW_DAYS = 60
AT_RISK_DAYS = 10

# --- kindergarten (PRD §3.1 / §3.9)
KINDERGARTEN_AGE_YEARS = 5
KINDERGARTEN_CUTOFF_MONTH = 9
KINDERGARTEN_CUTOFF_DAY = 1
TRANSITION_CONFERENCE_LEAD_DAYS = 90

# --- delay arithmetic (PRD §3.6)
DELAY_QUALIFY_PCT = 25.0
SEVERE_SINGLE_DOMAIN_PCT = 33.0
MULTI_DOMAIN_MIN_COUNT = 2
REQUIRED_DOMAIN_COUNT = 5
PLAY_BASED_CONFIDENCE_WEIGHT = 0.9

# --- service minute recommendation (PRD §3.6)
BASE_MINUTES_PER_QUALIFYING_DOMAIN = 50
SEVERITY_MULT_MODERATE = 1.0
SEVERITY_MULT_SIGNIFICANT = 1.15
SEVERITY_MULT_PROFOUND = 1.4
SEVERITY_BAND_SIGNIFICANT_PCT = 33.0
SEVERITY_BAND_PROFOUND_PCT = 50.0
MINUTE_ROUNDING_INCREMENT = 5

# --- provider minute ledger (PRD §3.8)
TRAVEL_TIER1_MAX_DIRECT_MINUTES = 300
TRAVEL_TIER1_PCT = 0.05
TRAVEL_TIER2_MAX_DIRECT_MINUTES = 600
TRAVEL_TIER2_PCT = 0.10
TRAVEL_TIER3_PCT = 0.15
TRAVEL_PER_EXTRA_SITE_MINUTES = 15
NEAR_CAPACITY_UTILIZATION = 0.80

# --- registration defaults (PRD §3.1 / §3.2)
DEFAULT_MAX_WEEKLY_SERVICE_MINUTES = 1500
DEFAULT_MAX_EVALUATION_CASELOAD = 12
DEFAULT_MAX_INTERPRETER_ASSIGNMENTS = 0
DEFAULT_SLOT_LENGTH_MINUTES = 20
DEFAULT_LANGUAGE_CODE = "en"

# --- revision loop (PRD §3.7)
MAX_REVISION_ROUNDS = 2

# --- logical clock (PRD §2.4): the value the clock reads before it is ever set
INITIAL_LOGICAL_CLOCK = "2026-08-01T00:00:00Z"

# --- pagination (PRD §2.3)
DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100

# A syntactically valid UUID that no row will ever carry.
MISSING_UUID = "00000000-0000-4000-8000-000000000000"

# Which disciplines may assess which developmental domain (PRD §3.5).
DOMAIN_DISCIPLINE_MAP = {
    "COMMUNICATION": ["SLP", "ECSE_TEACHER"],
    "PHYSICAL_MOTOR": ["OT", "PT"],
    "COGNITIVE": ["SCHOOL_PSYCHOLOGIST", "ECSE_TEACHER"],
    "SOCIAL_EMOTIONAL": ["SOCIAL_WORKER", "SCHOOL_PSYCHOLOGIST"],
    "ADAPTIVE": [
        "SCHOOL_PSYCHOLOGIST",
        "SLP",
        "OT",
        "PT",
        "ECSE_TEACHER",
        "SOCIAL_WORKER",
    ],
}

CHAIR_ELIGIBLE_DISCIPLINES = ["SCHOOL_PSYCHOLOGIST", "ECSE_TEACHER"]


# ------------------------------------------------------------------ conversions
def utc(text: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating any sub-second width and 'Z'."""
    cleaned = text.strip()
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    parsed = datetime.fromisoformat(cleaned)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def iso_z(moment: datetime) -> str:
    """Render an instant in the ``...Z`` UTC form the API accepts on input."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_ms(moment: datetime) -> str:
    """Render an instant with exactly three fractional-second digits."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + (
        f"{moment.microsecond // 1000:03d}Z"
    )


def ts(text: str) -> str:
    """Normalise an instant literal to the three-fractional-digit input form."""
    return iso_ms(utc(text))


def plus_minutes(text: str, minutes: int) -> str:
    """Advance an ISO 8601 UTC instant by whole minutes, in the input form."""
    return iso_ms(utc(text) + timedelta(minutes=minutes))


def plus_hours(text: str, hours: int) -> str:
    """Advance an ISO 8601 UTC instant by whole hours, in the input form."""
    return iso_ms(utc(text) + timedelta(hours=hours))


def plus_days(text: str, days: int) -> str:
    """Advance an ISO 8601 UTC instant by whole days, in the input form."""
    return iso_ms(utc(text) + timedelta(days=days))


def plus_days_date(day: str, days: int) -> str:
    """Plain calendar-day addition on a ``YYYY-MM-DD`` date (PRD §2.8)."""
    return (date.fromisoformat(day) + timedelta(days=days)).isoformat()


def whole_months(earlier: str, later: str) -> int:
    """Whole completed months between two calendar dates (PRD §2.8)."""
    d0 = date.fromisoformat(earlier)
    d1 = date.fromisoformat(later)
    months = (d1.year - d0.year) * 12 + (d1.month - d0.month)
    if d1.day < d0.day:
        months -= 1
    return months


def date_of_birth_for_age(age_months: int, on_date: str) -> str:
    """A birth date that makes a child exactly ``age_months`` old on ``on_date``."""
    target = date.fromisoformat(on_date)
    total = target.year * 12 + (target.month - 1) - age_months
    year, month = divmod(total, 12)
    return date(year, month + 1, min(target.day, 28)).isoformat()


def round_half_up_1dp(value) -> float:
    """Round to one decimal place, half away from zero (PRD §2.8)."""
    quantised = Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return float(quantised)


def ceil5(value) -> int:
    """Round up to the next multiple of five (PRD §2.8)."""
    exact = Decimal(str(value)) / Decimal(5)
    whole = int(exact)
    if Decimal(whole) < exact:
        whole += 1
    return whole * 5


def expected_percent_delay(chronological_age_months: int, age_equivalent_months: int) -> float:
    """``percent_delay`` exactly as PRD §3.6 defines it."""
    numerator = Decimal(100) * (
        Decimal(chronological_age_months) - Decimal(age_equivalent_months)
    )
    return round_half_up_1dp(numerator / Decimal(chronological_age_months))


def expected_weighted_delay(percent_delay: float, weight: float) -> float:
    """Weight an already-rounded ``percent_delay`` and round again (PRD §3.6)."""
    return round_half_up_1dp(Decimal(str(percent_delay)) * Decimal(str(weight)))


def severity_multiplier(weighted_percent_delay: float) -> float:
    """Severity multiplier band for a qualifying domain (PRD §3.6)."""
    if weighted_percent_delay >= SEVERITY_BAND_PROFOUND_PCT:
        return SEVERITY_MULT_PROFOUND
    if weighted_percent_delay >= SEVERITY_BAND_SIGNIFICANT_PCT:
        return SEVERITY_MULT_SIGNIFICANT
    return SEVERITY_MULT_MODERATE


def travel_tier_pct(direct_minutes: int) -> float:
    """Travel percentage tier chosen from the direct total alone (PRD §3.8)."""
    if direct_minutes <= TRAVEL_TIER1_MAX_DIRECT_MINUTES:
        return TRAVEL_TIER1_PCT
    if direct_minutes <= TRAVEL_TIER2_MAX_DIRECT_MINUTES:
        return TRAVEL_TIER2_PCT
    return TRAVEL_TIER3_PCT


def expected_travel_overhead(direct_minutes: int, distinct_sites: int) -> int:
    """``travel_overhead_minutes`` with the pinned single ceil-to-5 (PRD §3.8)."""
    pct = Decimal(str(travel_tier_pct(direct_minutes)))
    extra = max(0, distinct_sites - 1)
    raw = Decimal(direct_minutes) * pct + Decimal(extra) * Decimal(
        TRAVEL_PER_EXTRA_SITE_MINUTES
    )
    return ceil5(raw)


def expected_assigned_minutes(direct_minutes: int, distinct_sites: int) -> int:
    """Direct total plus travel overhead (PRD §3.8)."""
    return direct_minutes + expected_travel_overhead(direct_minutes, distinct_sites)


def anniversary(day: str, years: int) -> str:
    """Add whole years to a date; February 29 maps to March 1 (PRD §2.8)."""
    d = date.fromisoformat(day)
    if d.month == 2 and d.day == 29:
        return date(d.year + years, 3, 1).isoformat()
    return date(d.year + years, d.month, d.day).isoformat()


def expected_kindergarten_eligibility_date(date_of_birth: str) -> str:
    """First September 1 on or after the child's fifth birthday (PRD §3.1)."""
    fifth = date.fromisoformat(anniversary(date_of_birth, KINDERGARTEN_AGE_YEARS))
    cutoff = date(fifth.year, KINDERGARTEN_CUTOFF_MONTH, KINDERGARTEN_CUTOFF_DAY)
    if fifth <= cutoff:
        return cutoff.isoformat()
    return date(fifth.year + 1, KINDERGARTEN_CUTOFF_MONTH, KINDERGARTEN_CUTOFF_DAY).isoformat()


def date_part(instant: Optional[str]) -> Optional[str]:
    """The calendar date of an ISO 8601 UTC instant."""
    if instant is None:
        return None
    return utc(instant).date().isoformat()

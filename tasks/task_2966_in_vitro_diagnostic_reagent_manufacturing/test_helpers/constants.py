"""Numeric thresholds and default values stated in the PRD.

Also carries the clock helpers: the PRD drives every server-stamped instant from
a logical clock which reads exactly 2026-08-01T00:00:00Z before any caller has
moved it, and renders instants in ISO 8601 UTC with three fractional digits.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

# --- logical clock (PRD §2.4) ---------------------------------------------
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00.000Z"
DEFAULT_CLOCK_DT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

# --- raw material acceptance (PRD §3.1) -----------------------------------
ACCEPTANCE_SCORE_ACCEPT_MIN = 85.00
POTENCY_TOLERANCE_PCT = 5.0
ACCEPTANCE_WEIGHTS = {
    "POTENCY": 0.45,
    "PURITY": 0.30,
    "ENDOTOXIN": 0.15,
    "IDENTITY": 0.10,
}
IDENTITY_PASS_MIN = 1.0
DEFAULT_MAX_RETESTS = 1
DEFAULT_RETEST_WINDOW_DAYS = 30

# --- product specification defaults (PRD §3.2) ----------------------------
DEFAULT_MAX_REFERENCE_BIAS_PCT = 5.0
DEFAULT_MIN_SHELF_LIFE_DAYS_AT_SHIP = 90

# --- environmental monitoring action limits (PRD §3.4) --------------------
EM_ACTION_LIMITS = {
    "VIABLE_AIR": 10,
    "SURFACE": 5,
    "NONVIABLE_PARTICLE": 3520,
    "BIOBURDEN_BULK": 10,
}
MAJOR_EXCURSION_MULTIPLE = 2
MINOR_EXCURSIONS_TO_DISQUALIFY = 3

# --- filling line occupation (PRD §3.4) -----------------------------------
FILL_LINE_CHANGEOVER_BUFFER_MINUTES = 120

# --- stability programme (PRD §3.6) ---------------------------------------
STABILITY_CHAMBER_CAPACITY = 2
STABILITY_RECOVERY_CONFORMING_MIN_PCT = 90.00
ACCELERATED_REFERENCE_TEMP_C = {
    "TWO_TO_EIGHT_C": 5.0,
    "MINUS_TWENTY_C": -20.0,
}
Q10_TEMPERATURE_DIVISOR = 10

# --- bridging equivalence (PRD §3.7) --------------------------------------
BRIDGING_MEAN_BIAS_MAX_PCT = 3.00
BRIDGING_MAX_BIAS_MAX_PCT = 5.00

# --- complaint reporting deadlines (PRD §3.8) -----------------------------
REPORT_DEADLINE_DAYS_DEATH_OR_INJURY = 5
REPORT_DEADLINE_DAYS_DEFAULT = 30

# --- cold chain (PRD §3.9) ------------------------------------------------
COLD_CHAIN_MAX_TEMP_C = 15.0
COLD_CHAIN_MAX_CUMULATIVE_MINUTES = 240

# --- pagination (PRD §2.3) ------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100

# --- convenient defaults for fixture payloads -----------------------------
TEST_DEFAULTS = {
    "RECEIVED_QUANTITY_UNITS": 1000.00,
    "PLANNED_UNITS": 1000,
    "PLANNED_FILL_UNITS": 1000,
    "QUANTITY_USED": 10.00,
    "SHELF_LIFE_MONTHS_CLAIM": 24,
    "BASELINE_VALUE": 100.00,
    "REQUESTED_UNITS": 100,
}


def iso_utc(moment: datetime) -> str:
    """Render a datetime as ISO 8601 UTC with exactly three fractional digits."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    moment = moment.astimezone(timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating 'Z', offsets and any
    fractional-second width."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def clock_plus(days: float = 0, hours: float = 0, minutes: float = 0,
               seconds: float = 0, base: Optional[datetime] = None) -> str:
    """An instant offset from the default logical clock, rendered ISO 8601 UTC."""
    anchor = base or DEFAULT_CLOCK_DT
    return iso_utc(anchor + timedelta(days=days, hours=hours,
                                     minutes=minutes, seconds=seconds))


def shift(instant: str, days: float = 0, hours: float = 0, minutes: float = 0,
          seconds: float = 0) -> str:
    """An instant offset from another ISO 8601 instant."""
    return iso_utc(parse_instant(instant) + timedelta(
        days=days, hours=hours, minutes=minutes, seconds=seconds))


def add_calendar_months(instant: str, months: int) -> str:
    """Advance an instant by whole calendar months, preserving the day-of-month
    where it exists in the target month and clamping to the last day of that
    month where it does not; the time-of-day is preserved (PRD §3.5)."""
    moment = parse_instant(instant)
    total = moment.month - 1 + months
    year = moment.year + total // 12
    month = total % 12 + 1
    if month == 12:
        next_month_first = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        next_month_first = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    days_in_month = (next_month_first - timedelta(days=1)).day
    day = min(moment.day, days_in_month)
    return iso_utc(moment.replace(year=year, month=month, day=day))

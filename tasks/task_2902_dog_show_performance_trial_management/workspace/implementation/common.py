"""Shared primitives: vocabularies, numeric helpers, timestamp helpers."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING
import random
import string
import uuid

# ---------------------------------------------------------------- vocabularies
REGION_CODES = ["NE", "SE", "MW", "WC"]
GROUP_CODES = [
    "SPORTING", "HOUND", "WORKING", "TERRIER", "TOY", "NON_SPORTING", "HERDING",
]
DISCIPLINES = ["AGILITY", "OBEDIENCE", "RALLY"]

ROLES = [
    "ClubOfficer", "SanctionOfficer", "ShowSecretary", "Judge", "Handler",
    "RegistryOfficer",
]
ALL_ROLES = list(ROLES)

CLUB_SANCTION_STATUS = ["ACTIVE", "PROBATION", "SUSPENDED"]
JUDGE_STATUS = ["ACTIVE", "PROVISIONAL", "SUSPENDED"]
HANDLER_STATUS = ["ACTIVE", "SUSPENDED"]

SHOW_TYPES = ["CONFORMATION", "PERFORMANCE", "COMBINED"]
SHOW_STATUSES = [
    "DRAFT", "SUBMITTED", "RETURNED", "APPROVED", "IN_PROGRESS", "COMPLETED",
    "RESULTS_FILED",
]
POINTS_SCALES = ["SCALE_A", "SCALE_B"]

SLOT_STATUSES = ["PROPOSED", "CONFIRMED", "DECLINED"]
PANEL_ROLES = ["BREED_JUDGE", "GROUP_JUDGE", "BIS_JUDGE", "PERFORMANCE_JUDGE"]

CLASS_LEVELS = ["BREED", "GROUP", "BEST_IN_SHOW", "PERFORMANCE"]
CLASS_STATUSES = ["OPEN", "CLOSED", "SCHEDULED", "COMPLETED", "ABANDONED"]

ENTRY_STATUSES = [
    "RECEIVED", "CONFIRMED", "CHECKED_IN", "JUDGED", "ABSENT", "WITHDRAWN",
    "DISQUALIFIED",
]
WELFARE_STATUSES = ["CLEAR", "SEASON_DECLARED", "HEAT_HOLD"]
ENTRY_SOURCES = ["HANDLER_SUBMITTED", "PROMOTION"]
FEE_BASES = ["PROVISIONAL", "FINAL"]

BLOCK_STATUSES = ["PLANNED", "PUBLISHED", "SUPERSEDED", "COMPLETED"]

PROTEST_STATUSES = [
    "FILED", "UNDER_REVIEW", "EVIDENCE_REQUESTED", "UPHELD", "DISMISSED",
]
PROTEST_TYPES = ["MEASUREMENT", "ELIGIBILITY", "JUDGING_CONDUCT", "WELFARE"]
RESOLUTION_CODES = ["DISQUALIFY_ENTRY", "VACATE_PLACEMENT", "WARNING", "NO_ACTION"]

FILING_STATUSES = ["PENDING", "ACCEPTED", "REJECTED_INCOMPLETE"]

SEXES = ["DOG", "BITCH"]
MEASUREMENT_STATUSES = ["UNMEASURED", "TEMP_CARD", "PERMANENT_CARD"]
CARD_TYPES = ["TEMP_CARD", "PERMANENT_CARD"]

ADVISORY_LEVELS = ["GREEN", "AMBER", "RED"]
RUN_RESULTS = ["QUALIFIED", "NQ", "ELIMINATED"]
TITLE_CODES = ["CH", "AX", "CD", "RN"]
ATTENDANCE = ["PRESENT", "ABSENT"]

COUNTED_ACTIVE = {"CONFIRMED", "CHECKED_IN", "JUDGED"}
# An absent dog still counts toward a class's entry_count for the purposes of the
# entered-dog population, but no longer counts as present (PRD 3.7).
ENTERED_POPULATION = {"CONFIRMED", "CHECKED_IN", "JUDGED", "ABSENT"}
PLANNABLE_BLOCKS = {"PLANNED", "PUBLISHED"}

DEFAULT_CLOCK = "2026-08-01T00:00:00.000Z"


# ------------------------------------------------------------------- numerics
def D(value):
    """Coerce to Decimal without going through binary float when possible."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def round_half_up_int(value):
    return int(D(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def round_half_up_places(value, places):
    exp = Decimal(1).scaleb(-places)
    return D(value).quantize(exp, rounding=ROUND_HALF_UP)


def one_dp(value):
    """Round half-up to one decimal place and return as a float."""
    return float(round_half_up_places(value, 1))


def ceil_int(value):
    return int(D(value).to_integral_value(rounding=ROUND_CEILING))


def ceil_div(numerator, denominator):
    return -((-int(numerator)) // int(denominator))


# ----------------------------------------------------------------- timestamps
ISO_FMT = "%Y-%m-%dT%H:%M:%S"


def parse_instant(text):
    """Parse an ISO-8601 instant. Returns an aware UTC datetime or None."""
    if not isinstance(text, str):
        return None
    raw = text.strip()
    if not raw:
        return None
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_instant(dt):
    """Canonical ISO-8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime(ISO_FMT) + ".%03dZ" % (dt.microsecond // 1000)


def canonical_instant(text):
    dt = parse_instant(text)
    if dt is None:
        return None
    return format_instant(dt)


def shift_instant(iso_text, **kwargs):
    dt = parse_instant(iso_text)
    return format_instant(dt + timedelta(**kwargs))


def parse_date(text):
    if not isinstance(text, str) or len(text) != 10:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def date_midnight(date_text):
    return date_text + "T00:00:00.000Z"


def whole_months_between(start_date, end_date):
    months = (end_date.year - start_date.year) * 12 + (end_date.month - start_date.month)
    if end_date.day < start_date.day:
        months -= 1
    return months


# ------------------------------------------------------------------ identifiers
def new_uuid():
    return str(uuid.uuid4())


_ALNUM = string.ascii_uppercase + string.digits


def new_request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))

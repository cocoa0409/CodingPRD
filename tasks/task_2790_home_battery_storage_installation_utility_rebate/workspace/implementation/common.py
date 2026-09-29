"""Shared primitives: decimal arithmetic, ISO-8601 handling, firmware comparison,
domain constants and the manufacturer model catalog.

Precision discipline (PRD 2.7):
  * kW / kWh  -> exactly 2 decimals, ROUND_HALF_UP
  * ratios    -> exactly 4 decimals, ROUND_HALF_UP
  * money     -> integer cents, never a string, one rounding step per figure
All intermediate arithmetic is done on ``decimal.Decimal`` -- never float.
"""

import random
import re
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

# --------------------------------------------------------------------------- #
# Decimal helpers
# --------------------------------------------------------------------------- #

TWO = Decimal("0.01")
FOUR = Decimal("0.0001")
ZERO = Decimal("0")


def dec(value):
    """Coerce an int/float/Decimal/str into an exact Decimal."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise TypeError("bool is not a number")
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def rhu(value, places):
    """Round half up to ``places`` decimal places."""
    q = Decimal(1).scaleb(-places) if places > 0 else Decimal(1)
    return dec(value).quantize(q, rounding=ROUND_HALF_UP)


def kw(value):
    """Quantize a kW / kWh figure to exactly 2 decimals, round half up."""
    return rhu(value, 2)


def ratio4(value):
    """Quantize a ratio to exactly 4 decimals, round half up."""
    return rhu(value, 4)


def cents(value):
    """Round half up to a whole number of cents and return a Python int."""
    return int(rhu(value, 0))


def floor_cents(value):
    """Discard the fractional part toward zero, returning a Python int."""
    d = dec(value)
    return int(d.to_integral_value(rounding="ROUND_DOWN"))


# --------------------------------------------------------------------------- #
# ISO-8601 UTC with three fractional digits
# --------------------------------------------------------------------------- #

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(\.\d+)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_iso(value):
    """Parse an ISO-8601 instant into a timezone-aware UTC datetime.

    Returns ``None`` when the value is not a parseable instant.
    """
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute, second = (int(m.group(i)) for i in range(1, 7))
    frac = m.group(7)
    micro = 0
    if frac:
        digits = (frac[1:] + "000000")[:6]
        micro = int(digits)
    tz = m.group(8)
    try:
        base = datetime(year, month, day, hour, minute, second, micro, tzinfo=timezone.utc)
    except ValueError:
        return None
    if tz and tz not in ("Z", "z"):
        sign = 1 if tz[0] == "+" else -1
        body = tz[1:].replace(":", "")
        offset = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
        base = base - sign * offset
    return base


def fmt_iso(moment):
    """Format a datetime as ISO-8601 UTC with exactly three fractional digits."""
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    moment = moment.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        moment.year,
        moment.month,
        moment.day,
        moment.hour,
        moment.minute,
        moment.second,
        moment.microsecond // 1000,
    )


def normalize_iso(value):
    """Normalize a caller-supplied instant to the canonical output format."""
    parsed = parse_iso(value)
    return fmt_iso(parsed) if parsed else None


def wall_now_iso():
    """Real wall-clock instant, used only for created_at / updated_at / meta."""
    return fmt_iso(datetime.now(timezone.utc))


def exact_hours(start_iso, end_iso):
    """Window length in hours as an exact Decimal."""
    start = parse_iso(start_iso)
    end = parse_iso(end_iso)
    delta = end - start
    seconds = (
        Decimal(delta.days) * Decimal(86400)
        + Decimal(delta.seconds)
        + Decimal(delta.microseconds) / Decimal(1000000)
    )
    return seconds / Decimal(3600)


def plus_days(iso_value, days):
    moment = parse_iso(iso_value)
    return fmt_iso(moment + timedelta(days=days))


def plus_minutes(moment, minutes):
    return moment + timedelta(minutes=minutes)


# --------------------------------------------------------------------------- #
# Identifiers
# --------------------------------------------------------------------------- #

_ALNUM = string.ascii_uppercase + string.digits


def new_uuid():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


# --------------------------------------------------------------------------- #
# Firmware versions (PRD 2.11)
# --------------------------------------------------------------------------- #

_FIRMWARE_RE = re.compile(r"^\d+\.\d+\.\d+$")


def firmware_well_formed(value):
    """A firmware string must be three dot-separated integers."""
    return isinstance(value, str) and bool(_FIRMWARE_RE.match(value.strip()))


def _fw_parts(value):
    return [int(part) for part in str(value).split(".") if part != ""]


def version_ge(left, right):
    """True when ``left`` is not older than ``right``.

    Components are compared left to right as integers, missing components
    treated as zero, so ``25.2`` is not older than ``25.2.0``.
    """
    a = _fw_parts(left)
    b = _fw_parts(right)
    width = max(len(a), len(b))
    a = a + [0] * (width - len(a))
    b = b + [0] * (width - len(b))
    for x, y in zip(a, b):
        if x != y:
            return x > y
    return True


# --------------------------------------------------------------------------- #
# Domain constants
# --------------------------------------------------------------------------- #

ROLES = (
    "CertifiedInstaller",
    "Homeowner",
    "AuthorityHavingJurisdiction",
    "UtilityInterconnectionReviewer",
    "RebateAdministrator",
    "ManufacturerWarrantyAgent",
)

CERT_LEVELS = ("NONE", "CERTIFIED", "ADVANCED")
CERT_STATUSES = ("ACTIVE", "SUSPENDED")
MODEL_CODES = ("PWX_A", "PWX_B", "PWX_C")
INVERTER_MODELS = ("GW2_HOME", "GW3_HOME")
TERRITORIES = ("TER_WEST", "TER_EAST", "TER_NORTH")
PANEL_AMPS = (100, 125, 200, 400)
LOAD_METHODS = ("NEC_220_82_STANDARD", "NEC_220_87_MEASURED")
BACKUP_SCOPES = ("WHOLE_HOME", "ESSENTIAL_LOADS")
LOAD_CALC_STATUSES = ("DRAFT", "SUBMITTED", "REVISION_REQUIRED", "APPROVED")
BUILD_STATUSES = (
    "DESIGN_DRAFT",
    "DESIGN_LOCKED",
    "INSTALLED",
    "COMMISSIONED",
    "SUPERSEDED",
    "DESIGN_HOLD",
)
GRID_STATUSES = (
    "NOT_APPLIED",
    "APPLICATION_SUBMITTED",
    "APPROVED_TO_INSTALL",
    "PTO_GRANTED",
    "DENIED",
)
WARRANTY_STATUSES = ("UNREGISTERED", "ACTIVE", "VOID")
JURISDICTIONS = ("AHJ_CITY", "AHJ_COUNTY")
PERMIT_STATUSES = (
    "DRAFT",
    "SUBMITTED",
    "CORRECTIONS_REQUIRED",
    "ISSUED",
    "INSPECTION_FAILED",
    "INSPECTION_PASSED",
)
EXPORT_MODES = ("NON_EXPORT", "LIMITED_EXPORT", "FULL_EXPORT")
APPLICATION_STATUSES = (
    "DRAFT",
    "SUBMITTED",
    "SUPPLEMENTAL_REVIEW",
    "APPROVED_TO_INSTALL",
    "PTO_GRANTED",
    "DENIED",
)
PROGRAM_TYPES = ("STATE_CAPACITY", "UTILITY_UPFRONT", "FEDERAL_ADDER")
CLAIM_STATUSES = (
    "RESERVED",
    "SUBMITTED",
    "APPROVED",
    "PAID",
    "DENIED",
    "VOID",
    "CLAWED_BACK",
)
CLAIM_DEAD_STATUSES = ("VOID", "DENIED", "CLAWED_BACK")
TEST_TYPES = (
    "BACKUP_TRANSITION",
    "CAPACITY_DISCHARGE",
    "ANTI_ISLANDING",
    "FIRMWARE_BASELINE",
)
TEST_STATUSES = ("SCHEDULED", "RECORDED")
TEST_RESULTS = ("PENDING", "PASS", "FAIL")
ALERT_CODES = (
    "FIRMWARE_UPDATE_FAILED",
    "CELL_IMBALANCE",
    "GATEWAY_OFFLINE",
    "THERMAL_DERATE",
)
SEVERITIES = ("INFO", "WARNING", "CRITICAL")
ALERT_STATUSES = (
    "OPEN",
    "ACKNOWLEDGED",
    "UNDER_REVIEW",
    "INFO_REQUESTED",
    "CLAIM_APPROVED",
    "CLAIM_DENIED",
)
SEASONS = ("SUMMER_2026", "WINTER_2026")
ENROLLMENT_STATUSES = ("PENDING_CONSENT", "ENROLLED", "SUSPENDED", "WITHDRAWN")
EVENT_TYPES = ("ECONOMIC", "EMERGENCY")
EVENT_STATUSES = ("SCHEDULED", "SETTLED")
PERFORMANCE_STATUSES = ("PENDING", "REPORTED", "SETTLED", "CANCELLED")

# load_sizing
LIGHTING_VA_PER_SQFT = Decimal("3")
GENERAL_FIRST_VA = Decimal("3000")
GENERAL_FIRST_FACTOR = Decimal("1.00")
GENERAL_REMAINDER_FACTOR = Decimal("0.40")
MEASURED_METHOD_HEADROOM = Decimal("1.25")
WHOLE_HOME_SURGE_FACTOR = Decimal("1.75")
ESSENTIAL_TOP_N = 2
ESSENTIAL_REMAINDER_FACTOR = Decimal("0.50")
MOTOR_SURGE_MULTIPLIER = Decimal("3.0")
SURGE_HEADROOM_FACTOR = Decimal("0.25")

# rebate_award
EXPORT_MULTIPLIER_BP = {
    "NON_EXPORT": Decimal("7500"),
    "LIMITED_EXPORT": Decimal("9000"),
    "FULL_EXPORT": Decimal("10000"),
}
BP_DIVISOR = Decimal("10000")

# byod_settlement
EMERGENCY_MULTIPLIER_BP = Decimal("12500")
BASE_MULTIPLIER_BP = Decimal("10000")
SHORTFALL_RATIO_FLOOR = Decimal("0.80")
PENALTY_FACTOR = Decimal("0.50")
BONUS_TIER_HIGH_RATIO = Decimal("0.95")
BONUS_HIGH_BP = Decimal("1000")
BONUS_TIER_MID_RATIO = Decimal("0.85")
BONUS_MID_BP = Decimal("500")

# thresholds
WARRANTY_REGISTRATION_GRACE_DAYS = 30
CLAWBACK_SUSPENSION_THRESHOLD = 2
PERMIT_MAX_CORRECTION_ROUNDS = 3
COMMISSIONING_TRAVEL_BUFFER_MIN = 30
TERRITORY_DISPATCH_CAP_KW = Decimal("1500")
RESERVE_SOC_MAX_PCT = 50
MAX_TRANSITION_MS = 200
MAX_ANTI_ISLANDING_MS = 2000
CAPACITY_PASS_FRACTION = Decimal("0.90")

MODEL_CATALOG = {
    "PWX_A": {
        "usable_kwh_per_unit": Decimal("13.5"),
        "continuous_kw_per_unit": Decimal("5.0"),
        "max_units": 10,
        "min_firmware": "24.4.0",
    },
    "PWX_B": {
        "usable_kwh_per_unit": Decimal("13.5"),
        "continuous_kw_per_unit": Decimal("11.5"),
        "max_units": 4,
        "min_firmware": "25.2.0",
    },
    "PWX_C": {
        "usable_kwh_per_unit": Decimal("11.9"),
        "continuous_kw_per_unit": Decimal("4.6"),
        "max_units": 12,
        "min_firmware": "24.4.0",
    },
}

INVERTER_FAMILY = {"GW2_HOME": "GW2", "GW3_HOME": "GW3"}
MODEL_INVERTER_FAMILY = {"PWX_A": "GW2", "PWX_B": "GW3", "PWX_C": "GW2"}

LOGICAL_CLOCK_EPOCH = "2026-08-01T00:00:00.000Z"

"""In-memory store and logical clock for the Dealer Color Licensing API.

The store starts EMPTY on every boot. No seeding.
"""
import uuid
from datetime import datetime, timezone, timedelta

EARTH_RADIUS_MILES = 3958.8
LICENSE_TERM_DAYS = 365
CALIBRATION_PERIOD_DAYS = 90
CLAIM_WINDOW_DAYS = 90
ATTESTATION_FRESH_DAYS = 366
WINDOW_MONTHS = 12

CLOCK_START = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

ROLES = [
    "PlatformAdmin",
    "RegionManager",
    "ChannelDirector",
    "DealerPrincipal",
    "ColorLabAdmin",
    "EquipmentTech",
]

# ---------------------------------------------------------------------------
# logical clock
# ---------------------------------------------------------------------------
_logical_now = CLOCK_START


def now():
    return _logical_now


def set_clock(dt):
    global _logical_now
    _logical_now = dt


def reset_clock():
    global _logical_now
    _logical_now = CLOCK_START


# ---------------------------------------------------------------------------
# stores: id -> dict
# ---------------------------------------------------------------------------
regions = {}
dealers = {}
applications = {}
equipment = {}
colorant_systems = {}
product_lines = {}
formulas = {}
formulation_changes = {}
rematch_tasks = {}
licenses = {}
contractors = {}
purchases = {}
orders = {}
coop_claims = {}
channel_events = {}


def new_id():
    return str(uuid.uuid4())


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits, 'Z' suffix."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    ms = dt.microsecond // 1000
    return f"{base}.{ms:03d}Z"


def parse_ts(value):
    """Parse an ISO 8601 timestamp. Returns aware datetime or None."""
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    s = value.strip()
    try:
        if s.endswith("Z"):
            s2 = s[:-1] + "+00:00"
        else:
            s2 = s
        dt = datetime.fromisoformat(s2)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def window_bounds(reference=None):
    """Trailing 12 full calendar months ending at the end of the month
    preceding the current logical month, inclusive of both endpoints.

    Returns (start, end) aware datetimes.
    """
    ref = reference if reference is not None else _logical_now
    # end = last instant of the month preceding ref's month
    first_of_current = ref.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = first_of_current - timedelta(microseconds=1)
    # start = first instant of the month 12 months before end's month
    y = end.year
    m = end.month - 11
    while m <= 0:
        m += 12
        y -= 1
    start = end.replace(year=y, month=m, day=1, hour=0, minute=0, second=0, microsecond=0)
    return (start, end)


def new_common():
    """Common fields for entities with common_fields=True."""
    ts = fmt_ts(_logical_now)
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }


def touch(entity):
    """Refresh updated_at and bump version."""
    entity["updated_at"] = fmt_ts(_logical_now)
    entity["version"] = entity.get("version", 1) + 1


def bump(entity):
    """Bump version/updated_at on cascade mutations (same as touch)."""
    touch(entity)

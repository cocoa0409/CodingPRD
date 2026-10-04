"""In-memory data store.

The store is created empty on every process boot.  Nothing here seeds,
preloads or registers any entity: every record a caller can observe was
produced by a declared endpoint of the API.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

CLOCK_STARTUP_ISO = "2026-09-01T00:00:00Z"
HOLD_EXPIRY_ISO = "2026-09-01T00:00:00Z"


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """ISO 8601 UTC with exactly three fractional digits."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        "{:03d}Z".format(datetime.now(timezone.utc).microsecond // 1000)


def parse_iso(value):
    """Parse an ISO 8601 instant into an aware UTC datetime, or None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if not text:
            return None
        if text.endswith("Z") or text.endswith("z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_from_dt(dt):
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        "{:03d}Z".format(dt.astimezone(timezone.utc).microsecond // 1000)


def round_half_up(value, places=0):
    """Round a Decimal/number half up to the given number of places."""
    quant = Decimal(1).scaleb(-places)
    dec = value if isinstance(value, Decimal) else Decimal(str(value))
    rounded = dec.quantize(quant, rounding=ROUND_HALF_UP)
    if places == 0:
        return int(rounded)
    return float(rounded)


def service_date_of(dt):
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d")


def date_from_service_date(text):
    dt = parse_iso(str(text) + "T00:00:00Z") if text is not None else None
    return dt


def store():
    return STORE


class Store(object):
    """Plain in-memory maps keyed by identifier."""

    def __init__(self):
        self.reset()

    def reset(self):
        # All entity data lives here, keyed by id.  Empty on every boot.
        self.resorts = {}
        self.room_types = {}
        self.reservations = {}
        self.day_passes = {}
        self.wristbands = {}
        self.attractions = {}
        self.lifeguard_shifts = {}
        self.water_quality_logs = {}
        self.admission_events = {}
        self.arcade_credit_grants = {}
        self.cabanas = {}
        self.cabana_bookings = {}
        self.group_bookings = {}
        self.group_members = {}
        self.activity_sessions = {}
        self.activity_bookings = {}
        # Per-resort logical clocks, advanceable only through the test-driving
        # endpoint; they never fall back to wall-clock time.
        self.clocks = {}
        # Per-resort simulated gateway outcomes for group deposits.
        self.gateway_outcomes = {}


STORE = Store()
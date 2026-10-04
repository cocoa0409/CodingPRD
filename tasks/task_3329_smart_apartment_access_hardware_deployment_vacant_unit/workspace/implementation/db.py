"""In-memory store and the logical clock.

Storage is memory-only: nothing is written to disk, so a fresh ``start.sh``
boot (the per-test-server isolation contract) wipes every byte of state.
No entity is ever seeded at startup — the maps below start empty.
"""

import secrets
import string
import uuid
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# Logical clock (PRD 3.10): pinned at startup, never wall-clock.
# ---------------------------------------------------------------------------
LOGICAL_CLOCK_START = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock(object):
    def __init__(self):
        self.now = LOGICAL_CLOCK_START

    def set(self, moment):
        self.now = moment

    def advance_to(self, moment):
        if moment > self.now:
            self.now = moment


clock = Clock()


# ---------------------------------------------------------------------------
# Collections.  One dict per entity, keyed by id.
# ---------------------------------------------------------------------------
class Store(object):
    def __init__(self):
        self.properties = {}
        self.buildings = {}
        self.units = {}
        self.devices = {}
        self.device_alerts = {}
        self.work_orders = {}
        self.residents = {}
        self.resident_status_events = {}
        self.access_credentials = {}
        self.guest_passes = {}
        self.tour_sessions = {}
        self.maintenance_visits = {}
        self.installation_jobs = {}

    def clear(self):
        for name, value in list(vars(self).items()):
            if isinstance(value, dict):
                setattr(self, name, {})


db = Store()


# ---------------------------------------------------------------------------
# Identifier and timestamp helpers
# ---------------------------------------------------------------------------
def new_id():
    """UUID with no type prefix and no readable component (PRD 2.4)."""
    return str(uuid.uuid4())


def new_request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(18))


def iso(moment):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.4)."""
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    moment = moment.astimezone(timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (
        moment.microsecond // 1000
    )


def parse_instant(value, field="instant"):
    """Parse an ISO 8601 instant into an aware UTC datetime."""
    from errors import ApiError, ERR_INVALID_REQUEST

    if value is None:
        raise ApiError(ERR_INVALID_REQUEST, "Missing required field: %s" % field)
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            moment = datetime.fromisoformat(text)
        except ValueError:
            raise ApiError(
                ERR_INVALID_REQUEST, "Field %s is not a valid ISO 8601 instant" % field
            )
    else:
        raise ApiError(ERR_INVALID_REQUEST, "Field %s is not a valid instant" % field)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def hours_between(a, b):
    return (b - a).total_seconds() / 3600.0


def days_between(a, b):
    return (b - a).total_seconds() / 86400.0


def add_minutes(moment, minutes):
    return moment + timedelta(minutes=minutes)


def add_hours(moment, hours):
    return moment + timedelta(hours=hours)


# ---------------------------------------------------------------------------
# Common resource properties (PRD 2.4)
# ---------------------------------------------------------------------------
# Internal bookkeeping keys are never rendered to clients.
INTERNAL_PREFIX = "_"

_ID_SEQ = 0


def new_record(fields=None, common=True):
    """Mint a resource carrying the standard system-managed fields."""
    now = clock.now
    # Identity is scoped to a logical instant: two rows created in the same
    # "now" are still minted in a total order, so a list is deterministic even
    # while every creation shares one clock reading.
    global _ID_SEQ
    _ID_SEQ += 1
    record = {"id": new_id(), "_seq": _ID_SEQ}
    if common:
        record["created_at"] = iso(now)
        record["updated_at"] = iso(now)
        record["version"] = 1
    else:
        record["created_at"] = iso(now)
    if fields:
        record.update(fields)
    return record


def touch(record):
    """Any write refreshes updated_at and bumps version by exactly one."""
    record["updated_at"] = iso(clock.now)
    record["version"] = record.get("version", 1) + 1
    return record


def serialize(record):
    """Render a resource for the response body."""
    if record is None:
        return None
    return {
        key: value
        for key, value in record.items()
        if not key.startswith(INTERNAL_PREFIX)
    }


def serialize_all(records):
    return [serialize(row) for row in records]
"""In-memory store and the server-owned logical clock. Empty on every boot."""
import uuid
from datetime import datetime, timezone

from constants import DEFAULT_CLOCK_ISO
from util import parse_iso

STORE = {
    "smelters": {},
    "potlines": {},
    "power_contracts": {},
    "price_observations": {},
    "interrupt_events": {},
    "hedge_positions": {},
    "alumina_agreements": {},
    "curtailment_decisions": {},
    "restart_plans": {},
    "environmental_permits": {},
    "labor_agreements": {},
    "production_plans": {},
}

_CLOCK = {"current_utc": parse_iso(DEFAULT_CLOCK_ISO)}


def new_id():
    return str(uuid.uuid4())


def now_wall():
    return datetime.now(timezone.utc)


def logical_clock():
    return _CLOCK["current_utc"]


def set_logical_clock(dt):
    _CLOCK["current_utc"] = dt


def stamp_new(record):
    """Populate the common system fields for a freshly created resource."""
    ts = now_wall()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    return record


def bump(record):
    """Every mutation (including lazy/system ones) bumps version + updated_at."""
    record["version"] += 1
    record["updated_at"] = now_wall()

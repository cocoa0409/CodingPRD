"""In-memory data store and logical clock.

Every byte of state lives in the module-level dicts below.  Nothing is persisted,
nothing is pre-populated: re-invoking ``start.sh`` yields a completely empty
system so that each isolated test boots from zero.
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# Tables — id -> record.  All start empty; the implementation never owns data.
# ---------------------------------------------------------------------------
TABLES = {
    "dealers": {},
    "dealer_agreements": {},
    "performance_reviews": {},
    "parts_commitments": {},
    "parts_order_batches": {},
    "certification_records": {},
    "rebuild_claims": {},
    "equipment_orders": {},
    "trade_in_units": {},
    "support_agreements": {},
    "market_share_observations": {},
    "party_registrations": {},
    "machine_population_records": {},
    "service_orders": {},
}

STATE = {
    # The server's startup default is exactly 2026-09-01T00:00:00Z and it never
    # silently reverts to real wall-clock time.
    "current_utc": datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc),
    # PartsCommitment.id -> {"rule_active": bool, "epoch": object}
    "deferred_rules": {},
    # Commitment ids whose deferred re-evaluation fired and was never consumed.
    "re_evaluation_armed": set(),
    # number of pending deferral slots per dealer (consumed by equipment delivery)
    "deferral_slots": {},
    # monotonic counter used to keep logical-clock timestamps strictly ordered
    "stamp_seq": 0,
}

LOCK = threading.RLock()


def reset() -> None:
    """Wipe every table (used by the test-only reset hook)."""
    for table in TABLES.values():
        table.clear()
    STATE["current_utc"] = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
    STATE["deferred_rules"].clear()
    STATE["re_evaluation_armed"].clear()
    STATE["deferral_slots"].clear()
    STATE["stamp_seq"] = 0


# ---------------------------------------------------------------------------
# Identifiers and timestamps
# ---------------------------------------------------------------------------
def new_id() -> str:
    return str(uuid.uuid4())


def now() -> datetime:
    return STATE["current_utc"]


def clock_iso(value: datetime) -> str:
    """ISO 8601 UTC with three fractional digits and a trailing Z."""
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:23] + "Z"


def now_iso() -> str:
    return clock_iso(now())


def as_dt(value) -> datetime:
    """Parse a stored ISO 8601 instant back into an aware datetime."""
    if isinstance(value, datetime):
        return value
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def stamp() -> str:
    """A logical-clock instant that is strictly greater than any earlier stamp.

    Derived-field mutations (which are still mutations) advance the logical
    clock by one millisecond so that creation-timestamp ordering stays total
    and reproducible — several records written inside one logical tick must
    still order deterministically.
    """
    STATE["stamp_seq"] += 1
    base = STATE["current_utc"] + timedelta(milliseconds=STATE["stamp_seq"])
    return clock_iso(base)


def set_clock(value: datetime) -> str:
    STATE["current_utc"] = value
    STATE["stamp_seq"] = 0
    return clock_iso(value)


def table(name: str) -> dict:
    return TABLES[name]


def find(name: str, entity_id) -> dict | None:
    if entity_id is None:
        return None
    return TABLES[name].get(str(entity_id))


def insert(name: str, record: dict) -> dict:
    TABLES[name][record["id"]] = record
    return record


def rows(name: str) -> list:
    return list(TABLES[name].values())
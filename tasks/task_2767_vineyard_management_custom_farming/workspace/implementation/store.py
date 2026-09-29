"""In-memory data store and the logical clock.

Every table starts EMPTY on every boot.  Nothing is seeded, preloaded or
hardcoded: all state is built through the declared endpoints.
"""

from datetime import datetime

from common import UTC, ApiError, fmt_ms, new_id, wall_now

# --------------------------------------------------------------------------
# Tables — plain dicts keyed by id
# --------------------------------------------------------------------------

vineyards = {}
blocks = {}
contracts = {}
plans = {}
crews = {}
work_orders = {}
irrigation_events = {}
pest_observations = {}
yield_estimates = {}
spray_records = {}
delivery_windows = {}
harvest_loads = {}

ALL_TABLES = (
    vineyards,
    blocks,
    contracts,
    plans,
    crews,
    work_orders,
    irrigation_events,
    pest_observations,
    yield_estimates,
    spray_records,
    delivery_windows,
    harvest_loads,
)

# --------------------------------------------------------------------------
# Logical clock (PRD 2.4): starts at exactly 2026-08-01T00:00:00Z and never
# falls back to machine time.
# --------------------------------------------------------------------------

CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)
_clock = {"now": CLOCK_DEFAULT}


def now_utc():
    return _clock["now"]


def set_clock(instant):
    _clock["now"] = instant
    return _clock["now"]


# --------------------------------------------------------------------------
# Row bookkeeping
# --------------------------------------------------------------------------

_seq = {"n": 0}


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def new_row(versioned=True):
    """Create the common system fields of a fresh row."""
    created = wall_now()
    row = {
        "id": new_id(),
        "created_at": created,
        "_seq": next_seq(),
    }
    if versioned:
        row["updated_at"] = created
        row["version"] = 1
    return row


def touch(row):
    """Mutation bookkeeping: version += 1 and updated_at refreshed."""
    row["version"] = row["version"] + 1
    row["updated_at"] = wall_now()
    return row


def created_key(row):
    return (row["created_at"], row["_seq"])


def base_fields(row):
    out = {"id": row["id"], "created_at": fmt_ms(row["created_at"])}
    if "version" in row:
        out["updated_at"] = fmt_ms(row["updated_at"])
        out["version"] = row["version"]
    return out


def find(table, row_id, error_id):
    if not isinstance(row_id, str) or row_id not in table:
        raise ApiError(error_id, 404)
    return table[row_id]

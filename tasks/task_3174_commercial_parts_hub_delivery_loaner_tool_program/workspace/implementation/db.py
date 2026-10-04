"""In-memory data store.

Nothing is seeded, preloaded or hardcoded: every map below starts empty on each
boot and only the declared endpoints ever put a row into one of them.  The
process holds no file, no cache and no external persistence.
"""

import threading
import uuid
from datetime import datetime, timezone

from timeutil import DEFAULT_CLOCK_ISO, now_stamp, parse_iso

# Resource collections, keyed by the server-minted uuid.
accounts = {}
vehicles = {}
parts = {}
part_fitments = {}
part_interchanges = {}
tool_fitments = {}
stores = {}
inventory_items = {}
sales_reps = {}
rep_coverages = {}
part_orders = {}
tool_loans = {}
tool_catalog = {}
core_returns = {}
warranty_registrations = {}
route_stops = {}
service_routes = {}

# The logical clock.  Until a PlatformAdmin moves it, it reads the fixed
# startup default and never the real wall clock (PRD 3.9).
_clock = {"current": parse_iso(DEFAULT_CLOCK_ISO)}

_lock = threading.RLock()


def new_id():
    """A server-minted uuid carrying no type prefix or mnemonic."""
    return str(uuid.uuid4())


def clock():
    """The logical clock as an aware UTC datetime."""
    return _clock["current"]


def clock_iso():
    from timeutil import format_iso
    return format_iso(_clock["current"])


def set_clock(value):
    _clock["current"] = value


def stamp():
    return now_stamp()


def touch(row):
    """Recompute derived fields and bump updated_at/version on a mutation."""
    row["updated_at"] = now_stamp()
    if "version" in row:
        row["version"] = row.get("version", 1) + 1
    row["_derived_rev"] = row.get("_derived_rev", 0) + 1
    return row


def bump(row):
    """Increment version and updated_at without any other side effect."""
    return touch(row)


def reset():
    """Drop every row.  Used only by the test harness's own clock reset."""
    for mapping in (
        accounts, vehicles, parts, part_fitments, part_interchanges,
        tool_fitments, stores, inventory_items, sales_reps, rep_coverages,
        part_orders, tool_loans, tool_catalog, core_returns,
        warranty_registrations, route_stops, service_routes,
    ):
        mapping.clear()
    set_clock(parse_iso(DEFAULT_CLOCK_ISO))


def rows(mapping):
    return list(mapping.values())


def find(mapping, row_id):
    return mapping.get(row_id)


def by(rows_list, **filters):
    out = []
    for row in rows_list:
        ok = True
        for key, value in filters.items():
            if value is None:
                continue
            if row.get(key) != value:
                ok = False
                break
        if ok:
            out.append(row)
    return out
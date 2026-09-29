"""In-memory data store. Every table starts empty on every boot; nothing is
seeded, preloaded or hardcoded here."""
from datetime import datetime, timezone

from flask import g

from common import new_id, utc_now

# ---------------------------------------------------------------------------
# Tables, keyed by id
# ---------------------------------------------------------------------------
jurisdictions = {}
grain_profiles = {}
coating_specs = {}
roll_forming_lines = {}
engineers = {}
dealers = {}
bin_designs = {}
design_analyses = {}
coil_lots = {}
roll_forming_runs = {}
dealer_orders = {}
kit_lines = {}
freight_loads = {}
installation_crews = {}
field_failures = {}

# The logical plant clock. Startup value is exactly 2026-08-01T00:00:00Z and it
# never falls back to real wall-clock time for business decisions.
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = {"now": CLOCK_DEFAULT}

_seq = {"n": 0}


def clock_now():
    return _clock["now"]


def clock_set(instant):
    _clock["now"] = instant
    return _clock["now"]


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def insert(table, row, versioned=True):
    """Insert a new row, minting id, creation ordinal and audit fields."""
    row["id"] = new_id()
    row["_seq"] = next_seq()
    created = utc_now()
    row["created_at"] = created
    if versioned:
        row["updated_at"] = created
        row["version"] = 1
    table[row["id"]] = row
    return row


def touch(row):
    """Advance a row's audit spine. A row touched several times inside one
    request still advances its version by exactly 1."""
    if row is None:
        return row
    if "version" not in row:
        return row
    touched = getattr(g, "touched", None)
    if touched is None:
        touched = set()
        g.touched = touched
    key = row["id"]
    if key in touched:
        return row
    touched.add(key)
    row["updated_at"] = utc_now()
    row["version"] = row["version"] + 1
    return row


def ordered(table):
    return sorted(table.values(), key=lambda row: row["_seq"])


def orders_of_dealer(dealer_id):
    return [row for row in ordered(dealer_orders) if row["dealer_id"] == dealer_id]


def orders_of_design(bin_design_id):
    return [row for row in ordered(dealer_orders) if row["bin_design_id"] == bin_design_id]


def orders_on_load(load_id):
    return [row for row in ordered(dealer_orders) if row["freight_load_id"] == load_id]


def analyses_of_design(bin_design_id):
    rows = [row for row in design_analyses.values() if row["bin_design_id"] == bin_design_id]
    return sorted(rows, key=lambda row: row["analysis_index"])


def kit_lines_of_order(order_id):
    return [row for row in ordered(kit_lines) if row["dealer_order_id"] == order_id]


def runs_of_lot(lot_id):
    return [row for row in ordered(roll_forming_runs) if row["coil_lot_id"] == lot_id]


def runs_of_line(line_id):
    return [row for row in ordered(roll_forming_runs) if row["roll_forming_line_id"] == line_id]


def loads_of_dealer(dealer_id):
    return [row for row in ordered(freight_loads) if row["dealer_id"] == dealer_id]


def crews_of_dealer(dealer_id):
    return [row for row in ordered(installation_crews) if row["dealer_id"] == dealer_id]


def orders_of_crew(crew_id):
    return [row for row in ordered(dealer_orders) if row["installation_crew_id"] == crew_id]

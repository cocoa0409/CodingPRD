"""In-memory store.

The store starts EMPTY on every boot. Nothing here seeds, preloads or registers
any entity: every row any caller sees was constructed through a declared
endpoint. There is no SQLite file, no JSON dump and no /tmp cache — the maps
below are the entire persistence layer, and they die with the process.
"""

import uuid
from datetime import datetime, timezone

# Fixed startup default of the logical clock (SCAFFOLD §1.5 / PRD §2.9).
DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def parse_dt(value):
    """Parse an ISO 8601 instant, tolerating a trailing Z. Returns None if unusable."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.price_points = {}
        self.season_windows = {}
        self.pack_programs = {}
        self.items = {}
        self.vendors = {}
        self.containers = {}
        self.stores = {}
        self.aisle_resets = {}
        self.conversion_projects = {}
        self.audits = {}
        self.landed_costs = {}
        self.allocation_lines = {}

        # Server-minted strictly increasing sequence, unique across all
        # LandedCostHistory rows (SCAFFOLD §1.1).
        self.landed_cost_sequence = 0

        # Logical clock — fixed default, never wall-clock.
        self.logical_clock = parse_dt(DEFAULT_CLOCK_ISO)

    # --- identity / ordering -------------------------------------------------
    def new_id(self):
        return str(uuid.uuid4())

    def now_iso(self):
        return iso(self.logical_clock)

    def mint_sequence(self):
        self.landed_cost_sequence += 1
        return self.landed_cost_sequence

    # --- timestamps ----------------------------------------------------------
    def creation_order(self, table):
        """Rows sorted by created_at ascending, stable (insertion order breaks ties)."""
        rows = list(table.values())
        for idx, row in enumerate(rows):
            row["__ord"] = idx
        rows.sort(key=lambda r: (r.get("created_at") or "", r["__ord"]))
        for row in rows:
            row.pop("__ord", None)
        return rows

    # --- clock ---------------------------------------------------------------
    def set_clock(self, dt):
        self.logical_clock = dt


db = Store()
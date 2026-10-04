"""In-memory data store.  The store starts empty on every boot: nothing is
seeded, preloaded or hardcoded.  Every entity a client observes was created by
that client through a declared endpoint."""

import uuid
from datetime import datetime, timezone

from response import now_iso

# Hub-local minute derivation (PRD 2.4): the operating day begins at 12:00Z.
_DAY_START_UTC_HOUR = 12

DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"

COLLECTIONS = (
    "hubs",
    "banks",
    "aircraft",
    "packages",
    "lanes",
    "moves",
    "buildups",
    "feeders",
    "shifts",
    "ops_runs",
    "failures",
    "claims",
)

# OpsRun and ServiceFailureClaim are created once and never modified in place:
# they carry id and created_at only (PRD 2.8).
NO_COMMON_FIELDS = ("ops_runs", "claims")

# Fields the server keeps for its own bookkeeping and never serialises.
PRIVATE_PREFIX = "_"


def new_id():
    return str(uuid.uuid4())


def now_minute_for(dt):
    """Hub-local minute-of-day for a UTC instant."""
    minutes = dt.hour * 60 + dt.minute
    if dt.hour < _DAY_START_UTC_HOUR:
        minutes += 1440
    return minutes


def parse_utc(text):
    if not isinstance(text, str):
        return None
    raw = text.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class Store:
    def __init__(self):
        self.tables = {name: {} for name in COLLECTIONS}
        # per-hub monotone counters keyed by hub id
        self.move_sequence = {}
        self.claim_sequence = {}
        self._clock = parse_utc(DEFAULT_CLOCK_ISO)

    # --- logical clock --------------------------------------------------
    @property
    def clock(self):
        return self._clock

    def set_clock(self, dt):
        self._clock = dt

    def minute(self):
        return now_minute_for(self._clock)

    # --- generic record helpers ----------------------------------------
    def create(self, table, fields, ts=None):
        stamp = ts or now_iso()
        record = {"id": new_id(), "created_at": stamp}
        if table not in NO_COMMON_FIELDS:
            record["updated_at"] = stamp
            record["version"] = 1
        record.update(fields)
        self.tables[table][record["id"]] = record
        return record

    def touch(self, table, record):
        """Ordinary mutation: refresh updated_at and bump version.

        A package mutation also ends any operator-declared volume override,
        because the total is then recomputed in the ordinary way (PRD 2.6).
        """
        if table not in NO_COMMON_FIELDS:
            record["updated_at"] = now_iso()
            record["version"] = int(record.get("version", 1)) + 1
        if table == "packages":
            hub = self.tables["hubs"].get(record.get("hub_id"))
            if hub is not None:
                hub.pop("_volume_override", None)
        return record

    def get(self, table, record_id):
        if not record_id:
            return None
        return self.tables[table].get(record_id)

    def all(self, table):
        return list(self.tables[table].values())

    def where(self, table, **criteria):
        out = []
        for row in self.tables[table].values():
            if all(row.get(k) == v for k, v in criteria.items()):
                out.append(row)
        return out

    # --- package helpers -------------------------------------------------
    def find_by_ack(self, hub_id, ack):
        """The original package minted for an acknowledgement_number replay."""
        for pkg in self.all("packages"):
            if pkg.get("hub_id") == hub_id and pkg.get("acknowledgement_number") == ack:
                return pkg
        return None

    def move_of(self, package_id):
        """The load move a package belongs to.

        Onboarding is the act that puts a package on a move, and it is recorded
        explicitly so that a package whose destination gateway has no buildup yet
        still counts toward the move's filled weight (PRD 3.6's "planned weight
        of everything committed to it").
        """
        pkg = self.get("packages", package_id)
        if not pkg:
            return None
        if "_move_id" in pkg:
            return pkg["_move_id"]
        buildup = self.get("buildups", pkg.get("buildup_id"))
        if not buildup:
            return None
        return buildup.get("load_move_id")

    def move_members(self, move_id):
        out = []
        for pkg in self.all("packages"):
            if self.move_of(pkg["id"]) != move_id:
                continue
            out.append(pkg)
        return out


STORE = Store()
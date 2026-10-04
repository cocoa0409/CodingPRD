"""In-memory store for the refurbished-device marketplace API.

Everything lives in plain Python dicts keyed by id.  Nothing is persisted to
disk, nothing is seeded at boot: a fresh process starts with an empty store and
every entity a client ever sees was created through a declared endpoint.
"""

import uuid
from datetime import datetime, timedelta, timezone

DEFAULT_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.sellers = {}
        self.audit_records = {}
        self.listings = {}
        self.verifications = {}
        self.reservations = {}
        self.claims = {}
        self.service_scores = {}
        self.trade_ins = {}
        self.grading_definitions = {}
        # Governance catalogs.  These are *policy* inputs the tests file through
        # the declared catalog endpoints -- they are never pre-populated.
        self.supported_models = {}       # model_code -> {"floor_cents": int}
        self.restricted_models = {}      # model_code -> {"effective_from": dt|None}
        self.stolen_blocklist = set()
        self.counterfeit_blocklist = set()
        self._clock = DEFAULT_CLOCK
        # Insertion-ordered journal so every "created_at ASC" ordering has a
        # deterministic tie-break that never depends on a random uuid.
        self._seq = 0

    # ------------------------------------------------------------------ ids
    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        self._seq += 1
        return self._seq

    # ----------------------------------------------------------------- clock
    @property
    def clock(self):
        return self._clock

    def set_clock(self, instant):
        self._clock = instant

    def now_iso(self):
        return iso(self._clock)

    # ------------------------------------------------------------- catalogs
    def register_model(self, model_code, floor_cents=0):
        self.supported_models[model_code] = {"floor_cents": int(floor_cents)}

    def restrict_model(self, model_code, effective_from=None):
        self.supported_models.setdefault(model_code, {"floor_cents": 0})
        self.restricted_models[model_code] = {"effective_from": effective_from}

    def model_floor(self, model_code):
        row = self.supported_models.get(model_code)
        if row is None:
            return None
        return row["floor_cents"]

    def model_restricted(self, model_code, clock):
        row = self.restricted_models.get(model_code)
        if row is None:
            return False
        eff = row.get("effective_from")
        if eff is None:
            return True
        return clock >= eff

    # --------------------------------------------------------------- lookups
    def find(self, table, entity_id):
        return getattr(self, table).get(entity_id)


store = Store()


# --------------------------------------------------------------- timestamps
def iso(dt):
    """ISO 8601 UTC with three fractional digits and a Z suffix."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        "%03dZ" % (dt.microsecond // 1000)


def parse_iso(value):
    """Parse an ISO 8601 instant into an aware UTC datetime (or None)."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_days(dt, days):
    return dt + timedelta(days=days)


def calendar_days_between(start, end):
    """Calendar-day count from `start` to `end`, truncated toward zero."""
    return (end - start).days


# ------------------------------------------------------------- common fields
def stamp_new(table, payload, created_at):
    """Attach the four system-managed properties to a freshly minted row."""
    payload["id"] = store.new_id()
    payload["created_at"] = iso(created_at)
    payload["updated_at"] = iso(created_at)
    payload["version"] = 1
    payload["_seq"] = store.next_seq()
    payload["_created_dt"] = created_at
    return payload


def touch(row, clock):
    """Bump updated_at and version on any mutation, including cascades."""
    row["updated_at"] = iso(clock)
    row["version"] = row.get("version", 0) + 1


def touch_parent(table, parent_id, clock):
    row = getattr(store, table).get(parent_id)
    if row is not None:
        touch(row, clock)
    return row


def public(row):
    """Strip internal bookkeeping keys before serialising."""
    if row is None:
        return None
    return {k: v for k, v in row.items() if not k.startswith("_")}
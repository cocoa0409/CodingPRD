"""In-memory storage and the logical clock.

Nothing is persisted and nothing is seeded: every store starts empty on process
boot, so a fresh `start.sh` invocation wipes every byte of state. The only
pre-populated value is the logical clock, whose documented startup default is
2026-09-01T00:00:00Z (PRD 2.6 / 3.11) — it is not entity data.
"""
import uuid
from datetime import datetime, timedelta, timezone

CLOCK_START = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        # Entity maps, each keyed by the entity id. All empty at boot.
        self.licensors = {}
        self.designs = {}
        self.production_orders = {}
        self.print_layers = {}
        self.print_capacities = {}
        self.print_reservations = {}
        self.fulfillment_orders = {}
        self.shipments = {}
        self.royalty_accruals = {}
        self.settlements = {}
        self.counterfeit_reports = {}
        # Cross-cutting bookkeeping the specification makes observable.
        self.pick_remarks = {}       # fulfillment_order_id -> [remark, ...]
        self.ledger_lines = {}       # production_order_id -> [ledger line, ...]
        self.design_deciders = {}    # design_id -> X-User-ID of the licensor decision
        # The rights projects each licensor holds: the trigger types and the
        # garment SKUs its recorded projects cover.
        self.rights_projects = {}
        # Runs that have been reopened from PRINTING back to COMMITTED: their
        # intervening revert is what makes them committable again.
        self.reopened_runs = set()
        # Monotonic creation sequence: the tie-break of "ascending id order of
        # creation" cannot be a random field, so every resource's creation
        # order is tracked alongside it (never inside the resource body).
        self.seq = 0
        self.seq_of = {}
        # Logical clock (documented startup default, never wall-clock time).
        self.current_utc = CLOCK_START


store = Store()


# --- Identifiers ----------------------------------------------------------

def new_id():
    """A bare UUID string: no type prefix, no resource-name prefix, no separator."""
    return str(uuid.uuid4())


# --- Timestamps -----------------------------------------------------------

def fmt_iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    s = dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")
    return s[:-3] + "Z"


def now():
    """The logical clock (never the host's wall-clock time)."""
    return store.current_utc


def set_clock(dt):
    store.current_utc = dt


def stamp():
    """The current instant in the wire format."""
    return fmt_iso(now())


def parse_iso(value):
    """Parse an ISO 8601 instant, tolerating a trailing Z and fractional digits."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def hours_between(later, earlier):
    """Whole hours from `earlier` to `later`; negative once `later` has passed.
    Accepts datetimes or their serialised ISO 8601 form."""
    if later is None or earlier is None:
        return None
    later = parse_iso(later) if not isinstance(later, datetime) else later
    earlier = parse_iso(earlier) if not isinstance(earlier, datetime) else earlier
    return (later - earlier) / timedelta(hours=1)


# --- Common resource properties (PRD 2.5) ---------------------------------

def init_common(entity):
    """Stamp id / created_at / updated_at / version onto a new resource."""
    ts = stamp()
    entity["id"] = new_id()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    store.seq += 1
    store.seq_of[entity["id"]] = store.seq
    return entity


def touch(entity):
    """Every mutation of a resource increments its version by exactly 1
    and refreshes its updated_at stamp (cascade-driven mutations included)."""
    entity["version"] = int(entity.get("version", 0)) + 1
    entity["updated_at"] = stamp()
    return entity


def created_order(items):
    """Deterministic processing order: created_at ascending, ties broken by
    ascending id order of creation (PRD 2.3 / 3.2) — never by a random field."""
    return sorted(items, key=creation_key)


def creation_key(entity):
    """The deterministic processing key: the created_at instant, then the order
    in which the resource was created."""
    return (str(entity.get("created_at") or ""),
            int(store.seq_of.get(entity.get("id"), 0) or 0),
            str(entity.get("id") or ""))
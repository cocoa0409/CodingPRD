"""In-memory data store and the logical clock.

The store starts completely empty on every boot: nothing is seeded, preloaded
or hardcoded.  All collections are plain dicts/lists inside a process-local
singleton, so re-invoking start.sh wipes every byte of state.
"""

import uuid
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# Constants -- every one of these is read from SCAFFOLD.yaml §1.3 or §1.2.
# ---------------------------------------------------------------------------
INCLUDED_PIECES = {"SMALL": 60, "LARGE": 120, "JUMBO": 200}
CUP_REFERENCE_MASS_GRAMS = {"SMALL": 200, "LARGE": 400, "JUMBO": 620}
CUP_VOLUME_ML = {"SMALL": 250, "LARGE": 500, "JUMBO": 750}
# PRD §3.2: "a RESTRICTED store keeps trading but compresses its commercial
# envelope ... a cup whose weighed mass exceeds the mass capacity for its cup
# size is refused with ERR_STORE_RESTRICTED".  The narrow envelope that binds
# at a RESTRICTED store.  SCAFFOLD_DIFFICULTY_DESIGN §1.8 names the ceilings
# ("under the 340 g / 120 g cup ceilings").
CUP_CAPACITY_GRAMS = {"SMALL": 120, "LARGE": 340, "JUMBO": 620}

# At any other posture the envelope is not narrowed, so the ordinary mass
# capacity of a cup size is its own build capacity -- twice the reference mass
# the size is priced against.
STANDARD_CUP_CAPACITY_GRAMS = {"SMALL": 400, "LARGE": 800, "JUMBO": 1240}
OVERAGE_BAND_CENTS = {"SMALL": 44, "LARGE": 88, "JUMBO": 132}
RESTRICTED_SURCHARGE_DIVISOR = 2

PER_PIECE_UNIT_CENTS = 12
PER_PIECE_SURCHARGE_THRESHOLD = 100
PER_PIECE_SURCHARGE_BAND = 400

VIP_DISCOUNT_PCT = 0.05
STANDARD_DISCOUNT_PCT = 0.10
LAUNCH_SURCHARGE_PCT = 0.25

FILL_LOW_PCT = 50.0
FILL_EMPTY_PCT = 15.0

ENGINE_RESTRICTED_FRACTION = 0.10
SUSPENDED_MEMBER_FREEZE_COUNT = 3

RESTOCK_BATCH_SIZE = 3
EMPTY_BACKFILL_PCT = 0.10

SHRINKAGE_ALERT_BPS = 500

PRIORITY_CLASS_RANK = {"VIP_EARLY": 0, "GENERAL": 1}
MAX_LAUNCH_PURCHASES_PER_WAVE = 2
EXCLUSIVE_PURCHASE_POINTS = 50

VIP_PASSED_MB_THRESHOLD = 2
NO_SHOW_RESTRICT_COUNT = 2

REPLACEMENT_LIMIT_PER_90_DAYS = 1
REPLACEMENT_WINDOW_LOOKBACK_DAYS = 90
DEFAULT_WINDOW_DAYS = 30
CLAIM_VALUATION_RATE = 0.10
COMPLETION_CREDIT_PER_UNIT = 25

MINIFIGURE_SEAL_POINTS = 10
SEALED_CORRECTION_HOURS = 48

DEFAULT_CLOCK = "2026-09-01T00:00:00.000Z"

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100


# ---------------------------------------------------------------------------
# Clock helpers -- the server never reads wall-clock time.
# ---------------------------------------------------------------------------
def parse_iso(value):
    """Parse an ISO 8601 instant (with or without fractional digits)."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_iso(dt):
    """Render an instant as ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now():
    return _STORE.clock


def days_later(dt, days):
    return dt + timedelta(days=days)


def hours_later(dt, hours):
    return dt + timedelta(hours=hours)


# ---------------------------------------------------------------------------
# Counters
# ---------------------------------------------------------------------------
class Counter(object):
    def __init__(self):
        self._value = 0

    def next(self):
        self._value += 1
        return self._value

    def peek(self):
        return self._value


class Store(object):
    """The whole database: empty maps on every process boot."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = parse_iso(DEFAULT_CLOCK)

        self.stores = {}
        self.members = {}
        self.elements = {}
        self.theme_launches = {}
        self.launch_queues = {}
        self.wall_bins = {}
        self.fusion_orders = {}
        self.fusion_allocations = {}
        self.minifigure_builds = {}
        self.store_events = {}
        self.mini_build_reservations = {}
        self.replacement_requests = {}
        self.loyalty_ledger = {}
        self.exit_inspections = {}

        # Monotone, per-scope arrival counters.  These -- never the row id --
        # are the authoritative FIFO tie-breaks.
        self.launch_arrival = {}          # launch_id -> Counter
        self.event_arrival = {}           # store_id -> Counter
        self.grant_batch = {}             # launch_id -> Counter
        self.pending_corrections = []     # deferred return-to-bin records

    # -- id minting --------------------------------------------------------
    def new_id(self):
        return str(uuid.uuid4())


_STORE = Store()


def db():
    return _STORE


def launch_arrival(launch_id):
    counter = _STORE.launch_arrival.get(launch_id)
    if counter is None:
        counter = Counter()
        _STORE.launch_arrival[launch_id] = counter
    return counter


def event_arrival(store_id):
    counter = _STORE.event_arrival.get(store_id)
    if counter is None:
        counter = Counter()
        _STORE.event_arrival[store_id] = counter
    return counter


def grant_batch_counter(launch_id):
    counter = _STORE.grant_batch.get(launch_id)
    if counter is None:
        counter = Counter()
        _STORE.grant_batch[launch_id] = counter
    return counter
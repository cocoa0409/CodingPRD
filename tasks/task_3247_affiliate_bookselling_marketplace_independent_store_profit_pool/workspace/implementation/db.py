"""In-memory data store. Starts empty on every boot - no seeding."""
import uuid
from datetime import datetime, timezone


def new_id():
    return str(uuid.uuid4())


def now_wall_iso():
    """Wall-clock timestamp for meta/created_at fields (ISO 8601 UTC, 3 fractional digits)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# The logical clock: fixed at startup, never wall-clock.
LOGICAL_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


def get_clock():
    return LOGICAL_CLOCK


def set_clock(dt):
    global LOGICAL_CLOCK
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    LOGICAL_CLOCK = dt


def logical_now_iso():
    dt = LOGICAL_CLOCK
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "000Z"


class Store:
    def __init__(self):
        self.publishers = {}
        self.books = {}
        self.stores = {}
        self.partners = {}
        self.lists = {}
        self.orders = {}
        self.returns = {}
        self.ledger = {}
        self.pools = {}
        self.payouts = {}
        self.tickets = {}
        self.promotions = {}


DB = Store()

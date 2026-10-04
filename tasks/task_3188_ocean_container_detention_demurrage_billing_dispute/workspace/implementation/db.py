"""In-memory data store and logical clock."""
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.accounts = {}            # id -> dict
        self.contracts = {}           # id -> dict
        self.terminals = {}           # id -> dict
        self.holidays = {}            # id -> dict
        self.slots = {}               # id -> dict
        self.locations = {}           # id -> dict
        self.containers = {}          # id -> dict
        self.accruals = {}            # id -> dict
        self.invoices = {}            # id -> dict
        self.disputes = {}            # id -> dict
        self.evidence = {}            # id -> dict
        self.waivers = {}             # id -> dict
        self.payments = {}            # id -> dict
        self.bookings = {}            # id -> dict
        # daily empty-return counters: (location_id, iso_date_str) -> count
        self.location_daily_returns = {}
        # consecutive 61+ exposure day counters per account
        self.consecutive_61_plus = {}
        # logical clock
        self.clock = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


db = Store()


def now_utc() -> datetime:
    return db.clock


def iso_utc(dt: datetime) -> str:
    """Render as ISO 8601 with millisecond precision and Z suffix."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"

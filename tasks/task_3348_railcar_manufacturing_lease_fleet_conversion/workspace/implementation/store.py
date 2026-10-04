"""In-memory data store, logical clock and shared date/identity helpers.

Storage is Python dicts keyed by id and lives only in this process: re-running
start.sh starts a brand new interpreter, so every byte of state is wiped.  No
file, no database and no cache is ever written.  Nothing is seeded at startup
except the singleton PortfolioLedger, which PRD section 2.4 declares is "always
present in status OPEN" and which has no creation endpoint.
"""

import uuid
from datetime import datetime, date, timedelta, timezone

# --- Logical clock (PRD section 2.5) ----------------------------------------
CLOCK_DEFAULT = "2026-09-01T00:00:00Z"


class Clock:
    """The only source of 'now' in the system; never falls back to wall time."""

    def __init__(self):
        self._raw = CLOCK_DEFAULT
        self.current = parse_iso(CLOCK_DEFAULT)

    def set(self, iso):
        parsed = parse_iso(iso)
        self._raw = str(iso).strip()
        self.current = parsed
        return self.current

    def iso(self):
        # echoes the instant exactly as it was set, so the pinned startup
        # default reads back as 2026-09-01T00:00:00Z
        return self._raw

    @property
    def date(self):
        return self.current.date()

    def days_between(self, a, b):
        """Whole days from date a to date b (b - a)."""
        return (to_date(b) - to_date(a)).days


# --- Timestamp / date formatting --------------------------------------------
def now_iso():
    """Server-generated ISO 8601 UTC timestamp with exactly three fractional digits."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def fmt_clock(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def parse_iso(value):
    """Parse an ISO 8601 instant (or calendar date) into an aware datetime."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    s = str(value).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ValueError("not an ISO 8601 instant: %r" % (value,))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


clock = Clock()


def to_date(value):
    """Coerce a business date (calendar date or ISO instant) to a date."""
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    s = str(value).strip()
    if "T" in s:
        return parse_iso(s).date()
    return date.fromisoformat(s)


def fmt_date(d):
    return to_date(d).isoformat()


def add_days(d, n):
    return to_date(d) + timedelta(days=int(n))


def add_years(d, n):
    """Calendar-year advance; 29 Feb lands on 28 Feb in a non-leap year."""
    src = to_date(d)
    try:
        return src.replace(year=src.year + int(n))
    except ValueError:
        return src.replace(year=src.year + int(n), day=28)


def new_id():
    """Server-minted UUID with no type prefix (PRD section 2.4)."""
    return str(uuid.uuid4())


# --- Store -------------------------------------------------------------------
class Store:
    """Every collection in the system.  Dicts keyed by id, insertion-ordered."""

    COLLECTIONS = (
        "car_types", "components", "bom_rows", "production_orders",
        "endorsements", "lease_contracts", "lessees", "fleet_cars",
        "car_assignments", "car_returns", "retrofit_programs",
        "program_car_types", "retrofit_work_orders", "purchase_orders",
        "component_receipts", "fleet_sales", "changeovers",
    )

    def __init__(self):
        for name in self.COLLECTIONS:
            setattr(self, name, {})
        self.seq = 0
        self.ledger = None
        self.reset()

    def reset(self):
        for name in self.COLLECTIONS:
            getattr(self, name).clear()
        self.seq = 0
        # Singleton portfolio ledger: always present, always OPEN.
        self.ledger = self.new_row({
            "status": "OPEN",
            "committed_capital_cents": 0,
            "realized_gain_cents": 0,
            "fleet_nbv_cents": 0,
        })

    def new_row(self, fields):
        """Stamp the common field set (id, created_at, updated_at, version)."""
        self.seq += 1
        ts = now_iso()
        row = {
            "id": new_id(),
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
            "_seq": self.seq,
        }
        row.update(fields)
        return row

    def touch(self, row):
        """Bump version by 1 and refresh updated_at (PRD section 2.4)."""
        row["version"] = int(row.get("version", 1)) + 1
        row["updated_at"] = now_iso()
        return row

    def put(self, collection, row):
        getattr(self, collection)[row["id"]] = row
        return row

    def get(self, collection, row_id):
        return getattr(self, collection).get(row_id)

    def all(self, collection):
        return list(getattr(self, collection).values())

    def delete(self, collection, row_id):
        getattr(self, collection).pop(row_id, None)

    def sorted_rows(self, rows):
        """List ordering: created_at ascending, ties by insertion order."""
        return sorted(rows, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))


store = Store()


# --- Serialisation helper ----------------------------------------------------
def public(row, drop=("_seq",)):
    out = {}
    for k, v in row.items():
        if k in drop:
            continue
        out[k] = v
    return out

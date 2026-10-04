"""In-memory data store and logical clock.

The store starts empty on every boot; all state arrives via API calls.
The logical clock starts at exactly 2026-09-01T00:00:00Z and advances only
via POST /_clock/set_current_utc. It never reads wall-clock time.
"""

import itertools
import uuid
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.customers = {}          # FleetCustomer id -> entity
        self.depots = {}             # Depot id -> entity
        self.charging_projects = {}  # ChargingProject id -> entity
        self.suppliers = {}          # Supplier id -> entity
        self.modules = {}            # BatteryModule id -> entity
        self.orders = {}             # VehicleOrder id -> entity
        self.vehicles = {}           # Vehicle id -> entity
        self.centers = {}            # ServiceCenter id -> entity
        self.vans = {}               # MobileVan id -> entity
        self.visits = {}             # ServiceVisit id -> entity
        self.parts = {}              # (service_center_id, sku) -> PartsStock row
        self.campaigns = {}          # SoftwareCampaign id -> entity
        self.contracts = {}          # UptimeContract id -> entity
        self.claims = {}             # WarrantyClaim id -> entity
        self.clock = DEFAULT_CLOCK
        self.seq = itertools.count(1)


DB = Store()


def now():
    return DB.clock


def fmt_dt(dt):
    """Render a datetime as ISO 8601 UTC with three fractional digits."""
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def now_str():
    return fmt_dt(DB.clock)


def mint_id():
    return str(uuid.uuid4())


def stamp_new(e):
    """Assign the four common system fields to a freshly built entity dict."""
    ts = now_str()
    e["id"] = mint_id()
    e["created_at"] = ts
    e["updated_at"] = ts
    e["version"] = 1
    e["_created_dt"] = DB.clock
    e["_seq"] = next(DB.seq)


def touch(e):
    """Register a mutation: version +1, updated_at refreshed (PRD section 2.5)."""
    e["version"] += 1
    e["updated_at"] = now_str()
    e["_updated_dt"] = DB.clock


def public(e):
    """Strip internal underscore-prefixed keys for serialization."""
    return {k: v for k, v in e.items() if not k.startswith("_")}

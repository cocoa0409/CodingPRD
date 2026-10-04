"""In-memory data store. The store starts empty on every boot; nothing is seeded."""

from datetime import datetime, timezone

# Logical clock — fixed startup default per PRD §2.4.
DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"
DEFAULT_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

logical_clock = DEFAULT_CLOCK


def clock_now():
    return logical_clock


def set_clock(dt):
    global logical_clock
    logical_clock = dt


def utcnow():
    """Real wall-clock time, used only for meta.api_request_timestamp."""
    return datetime.now(timezone.utc)


suppliers = {}          # id -> BeefSupplier
audits = {}             # id -> Audit
commissaries = {}       # id -> Commissary
trucks = {}             # id -> Truck
routes = {}             # id -> DeliveryRoute
menu_items = {}         # id -> MenuItem
stores = {}             # id -> Store
batches = {}            # id -> DeliveryBatch
orders = {}             # id -> Order
associates = {}         # id -> Associate
postings = {}           # id -> ManagerPosting
applications = {}       # id -> ManagerApplication
shifts = {}             # id -> ShiftAssignment
beef_deliveries = {}    # id -> BeefDelivery
production_runs = {}    # id -> ProductionRun

# Store on-hand inventory ledger: store_id -> {"patties": int, "buns": int, "produce_units": int}
store_inventory = {}


def inventory_for(store_id):
    inv = store_inventory.get(store_id)
    if inv is None:
        inv = {"patties": 0, "buns": 0, "produce_units": 0}
        store_inventory[store_id] = inv
    return inv

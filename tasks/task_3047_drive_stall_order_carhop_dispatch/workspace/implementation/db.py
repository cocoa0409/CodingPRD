"""In-memory data store. Starts empty on every boot; no seeding of any kind."""
from datetime import datetime, timezone

# Logical clock (UTC). Startup default per PRD 2.6.
CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


def now():
    return CLOCK


def set_clock(dt):
    global CLOCK
    CLOCK = dt


class DB:
    def __init__(self):
        self.locations = {}
        self.menu_items = {}
        self.customization_options = {}
        self.customers = {}
        self.stalls = {}
        self.carhops = {}
        self.orders = {}
        self.order_lines = {}
        self.offers = {}
        self.delivery_runs = {}
        self.tip_records = {}
        self.equipment_faults = {}
        self.service_target_profiles = {}


db = DB()

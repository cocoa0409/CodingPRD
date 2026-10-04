"""In-memory data store and logical clock. Empty on every boot; no seeding."""
from datetime import datetime, timezone, timedelta


class Store:
    def __init__(self):
        self.items = {}
        self.purchase_orders = {}
        self.containers = {}
        self.stores = {}
        self.allocations = {}
        self.customers = {}
        self.memberships = {}
        self.coupons = {}
        self.sales = {}
        self.sale_lines = {}
        self.warranty_claims = {}
        self.recalls = {}
        # logical clock: initial value 2026-09-01T00:00:00Z
        self.clock = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

    def now(self):
        return self.clock

    def set_clock(self, dt):
        self.clock = dt


DB = Store()


def parse_iso(s):
    if s is None:
        return None
    if isinstance(s, str):
        ss = s.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(ss)
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    return None


def fmt_iso(dt):
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

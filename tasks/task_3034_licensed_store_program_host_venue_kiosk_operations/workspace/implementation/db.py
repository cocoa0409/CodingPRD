"""In-memory data store. The store starts empty on every boot — no seeding."""
import threading
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        # Logical clock; startup default exactly 2026-09-01T00:00:00Z
        self.clock = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.clock_set = False
        self.licensees = {}
        self.host_venues = {}
        self.license_agreements = {}
        self.stores = {}
        self.product_items = {}
        self.assortment_items = {}
        self.distributors = {}
        self.supply_orders = {}
        self.supply_order_lines = {}
        self.employees = {}
        self.certifications = {}
        self.sales_reports = {}
        self.royalty_statements = {}
        self.inspections = {}
        self.corrective_actions = {}
        self.loyalty_members = {}
        self.loyalty_account_events = {}
        self.promotion_campaigns = {}


db = Store()

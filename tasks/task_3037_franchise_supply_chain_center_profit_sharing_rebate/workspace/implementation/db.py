"""In-memory data store. Starts empty on every boot — no seeding."""
from datetime import datetime, timezone


class Clock:
    """Logical clock; default startup time 2026-09-01T00:00:00Z."""

    def __init__(self):
        self._current = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self._current

    def set(self, dt: datetime):
        self._current = dt


class DB:
    def __init__(self):
        self.centers = {}            # id -> SupplyCenter
        self.stores = {}             # id -> Store
        self.products = {}           # id -> Product
        self.price_books = {}        # id -> PriceBook
        self.routes = {}             # id -> DeliveryRoute
        self.stops = {}              # id -> DeliveryStop
        self.orders = {}             # id -> PurchaseOrder
        self.lines = {}              # id -> OrderLine
        self.promotions = {}         # id -> PromotionEvent
        self.pools = {}              # id -> RebatePool
        self.ledgers = {}            # id -> RebateLedger
        self.agreements = {}         # id -> ComplianceAgreement
        self.plans = {}              # id -> CapacityPlan
        self.variances = {}          # id -> FoodCostVariance
        self.compliance_reports = {}  # report_id -> report
        self.clock = Clock()


db = DB()

import threading

from util import initial_clock


class DB:
    """In-memory data store. Empty on every boot — no seeding."""

    def __init__(self):
        self.lock = threading.RLock()
        self.clock = initial_clock()
        self.broker_orgs = {}
        self.carrier_orgs = {}
        self.subscription_plans = {}
        self.subscriptions = {}
        self.load_posts = {}
        self.truck_posts = {}
        self.bookings = {}
        self.rate_transactions = {}
        self.credit_report_events = {}
        self.credit_disputes = {}
        self.fraud_alerts = {}
        self.authority_verifications = {}


db = DB()

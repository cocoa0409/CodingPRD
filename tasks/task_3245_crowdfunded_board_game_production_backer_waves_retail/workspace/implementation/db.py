"""In-memory data store. Fresh on every process boot — no seeding."""
import threading


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.campaigns = {}
        self.pledges = {}
        self.quotes = {}
        self.production_runs = {}
        self.freight_shipments = {}
        self.waves = {}
        self.allocations = {}
        self.replacement_requests = {}
        self.localizations = {}
        self.reprint_decisions = {}


db = Store()

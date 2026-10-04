"""In-memory data store. Starts empty on every boot - no seeding."""
import threading


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.members = {}
        self.accounts = {}
        self.deposits = {}
        self.early_postings = {}
        self.returns = {}
        self.advances = {}
        self.allocations = {}
        self.profiles = {}
        self.adjustments = {}
        self.abuse_events = {}
        self.ledger_entries = {}
        self.runs = {}
        self.disputes = {}
        # idempotency for advance creation: key -> (payload_signature, advance_id)
        self.advance_idempotency = {}


store = Store()

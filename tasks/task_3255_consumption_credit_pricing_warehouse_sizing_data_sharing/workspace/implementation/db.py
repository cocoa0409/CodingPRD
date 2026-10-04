"""In-memory data store.  Emptied on every process start.

Nothing is seeded, preloaded or hardcoded here: every entity is created by a
client through the declared API surface.  All collections are plain lists of
dicts, ordered by insertion so list endpoints can sort by created_at.
"""


class Store:
    def __init__(self):
        self.accounts = []
        self.warehouses = []
        self.sessions = []
        self.contracts = []
        self.drawdowns = []
        self.storage_records = []
        self.shares = []
        self.share_usage_events = []
        self.listings = []
        self.paid_usage = []
        self.monitors = []
        self.replications = []
        self.ledger = []

    def clear(self):
        self.__init__()


db = Store()


def find(collection, entity_id):
    for row in collection:
        if row.get("id") == entity_id:
            return row
    return None

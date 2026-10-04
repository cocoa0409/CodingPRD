"""In-memory data store.

Storage is process-local only: plain dicts keyed by the entity's ``id``.  There
is no disk persistence of any kind, so re-invoking ``start.sh`` wipes every byte
of state.  Nothing in this module -- and nothing at import time -- seeds,
preloads or registers an entity; every row any caller observes was created
through a declared endpoint.

Intrinsic row bookkeeping that is NOT part of an entity's declared field set
(creation sequence numbers, replay-guard request ids, cancellation reasons) lives
in the side tables below rather than being injected into serialised resources.
"""
from util import DEFAULT_CLOCK


class Store(object):
    def __init__(self):
        self.clock = DEFAULT_CLOCK
        self.role_permissions = {}
        self.admin_role_permissions = None
        self.seq = {}          # entity name -> monotone creation counter
        self.order = {}        # entity name -> list of ids in creation order
        # ----- intrinsic, non-declared bookkeeping -----
        self.requests = set()      # (store_id, request_id) replay guards
        self.progress = {}         # (ticket_id, batch_id) -> station consumed
        self.cancel_reason = {}    # catering order id -> cancellation reason
        self.payments = []         # simulated deposit outcomes
        # ----- entity tables -----
        self.stores = {}
        self.items = {}
        self.associates = {}
        self.certifications = {}
        self.batches = {}
        self.slicers = {}
        self.sanitation_cycles = {}
        self.sub_tickets = {}
        self.promotions = {}
        self.bread_orders = {}
        self.price_files = {}
        self.labels = {}
        self.catering_orders = {}
        self.waste_records = {}

    # ------------------------------------------------------------------ clock
    def now(self):
        return self.clock


_db = Store()


def get():
    return _db


def reset():
    global _db
    _db = Store()
    return _db


def all_rows(table):
    return list(table.values())
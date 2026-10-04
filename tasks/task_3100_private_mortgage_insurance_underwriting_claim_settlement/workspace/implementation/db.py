"""In-memory data store.

Storage is a set of plain dictionaries keyed by id. The store starts EMPTY on
every boot: no entity is seeded, preloaded, registered or hardcoded here or
anywhere else in the implementation. Every record a test needs is built through
the declared API surface.
"""

from collections import OrderedDict


class Store(object):
    def __init__(self):
        self.master_policies = OrderedDict()
        self.rate_cards = OrderedDict()
        self.reinsurance_treaties = OrderedDict()
        self.servicers = OrderedDict()
        self.lenders = OrderedDict()
        self.coverage_applications = OrderedDict()
        self.loans = OrderedDict()
        self.delinquency_reports = OrderedDict()
        self.cancellation_notices = OrderedDict()
        self.external_reports = OrderedDict()
        self.curtailment_disputes = OrderedDict()
        self.claims = OrderedDict()
        self.claim_settlement_options = OrderedDict()
        self.portfolio_snapshots = OrderedDict()
        self.reinsurance_cessions = OrderedDict()

    def reset(self):
        self.__init__()
        _SEQUENCE["next"] = 0


db = Store()


def insert(collection, record):
    collection[record["id"]] = record
    return record


def touch(record, clock_now=None):
    """Bump the audit quartet: updated_at moves and version advances by one.

    PRD 2.4: version begins at 1 on creation and is incremented by exactly one
    every time the row is mutated; updated_at moves with it.
    """
    from common import now_iso

    record["updated_at"] = now_iso() if clock_now is None else clock_now
    record["version"] = int(record.get("version", 1)) + 1
    return record


_SEQUENCE = {"next": 0}


def new_row(clock_now=None):
    """Mint the audit quartet (PRD 2.4) plus an internal insertion ordinal.

    The ordinal is never serialized; it exists only so that list endpoints can
    return items in creation order when many rows share one logical-clock
    instant (PRD 2.3: ordered by creation timestamp ascending).
    """
    from common import new_id, now_iso

    stamp = now_iso() if clock_now is None else clock_now
    _SEQUENCE["next"] += 1
    return {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": _SEQUENCE["next"],
    }
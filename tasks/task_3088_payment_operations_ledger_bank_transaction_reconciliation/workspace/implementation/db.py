"""In-memory data store.

Nothing is seeded.  Every dict below starts empty on every process boot and the
implementation never constructs an entity at import time.  All state is lost when
the process exits, which is what the per-test-server isolation mode requires.
"""

import uuid


class Store(object):
    def __init__(self):
        # entity collections, keyed by id
        self.ledgers = {}
        self.legal_entities = {}
        self.counterparties = {}
        self.relationships = {}
        self.bank_accounts = {}
        self.virtual_accounts = {}
        self.statements = {}
        self.statement_lines = {}
        self.payment_orders = {}
        self.transactions = {}
        self.exceptions = {}
        self.audit_events = {}
        self.settlement_pools = {}
        self.pool_memberships = {}
        self.release_requests = {}
        self.calendar_cells = {}

        # helper indexes
        self.idempotency = {}     # (legal_entity_id, idempotency_key) -> order_id
        self.dup_signatures = {}  # signature -> last_seen instant (ms epoch)
        self.rails_outcomes = {}  # payment_order_id -> {outcome, return_reason}

        # global monotonic creation ordinal
        self.seq = 0

        # the injected logical clock (PRD S2.11: startup default 2026-09-01T00:00:00Z)
        self.clock_ms = 1788220800000

    def next_seq(self):
        self.seq += 1
        return self.seq

    def new_id(self):
        return str(uuid.uuid4())


def new_store():
    return Store()
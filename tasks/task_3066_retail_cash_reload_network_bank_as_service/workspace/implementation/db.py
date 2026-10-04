"""In-memory data store.

Storage is Python dictionaries keyed by id, created empty at import time.  No
file, no cache, no preload: re-invoking start.sh wipes every byte of state.
"""

import uuid


def new_id():
    # A server-minted UUID with no type prefix or human-readable segment.
    return str(uuid.uuid4())


# --- collections -------------------------------------------------------------
bank_sponsors = {}
programs = {}
brand_partners = {}
retailer_agreements = {}
reload_locations = {}
card_accounts = {}
load_transactions = {}
aml_alerts = {}
dispute_cases = {}
loss_allocations = {}
settlement_batches = {}
float_windows = {}

ALL = (
    bank_sponsors,
    programs,
    brand_partners,
    retailer_agreements,
    reload_locations,
    card_accounts,
    load_transactions,
    aml_alerts,
    dispute_cases,
    loss_allocations,
    settlement_batches,
    float_windows,
)

# --- insertion-order registry ------------------------------------------------
# "List responses are ordered by creation time, oldest first - that is,
# ascending created_at."  The logical clock can be moved backwards by the
# operator, so timestamps alone are not a total order; sequence number breaks
# ties and keeps the ordering deterministic.
_seq = {}
_counter = {"n": 0}


def register(store, row):
    _counter["n"] += 1
    _seq[row["id"]] = _counter["n"]
    store[row["id"]] = row
    return row


def ordered(rows):
    return sorted(rows, key=lambda r: (_seq.get(r["id"], 0), r["id"]))
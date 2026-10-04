import itertools

# In-memory stores keyed by id. Store starts EMPTY on every boot.
stores = {
    "consortiums": {},
    "libraries": {},
    "funds": {},
    "patrons": {},
    "titles": {},
    "licenses": {},
    "holds": {},
    "loans": {},
    "orders": {},
    "invoices": {},
    "events": {},
    "snapshots": {},
}

_event_seq = itertools.count(1)

"""In-memory data store. The store starts empty on every boot — no seeding."""

COLLECTIONS = [
    "seasons", "troops", "products", "accounts", "orders", "lines",
    "sites", "pos", "transfers", "locations", "slots", "requests",
    "digital_orders", "agreements", "recalls",
]

_db = {name: {} for name in COLLECTIONS}
_seq = {name: 0 for name in COLLECTIONS}


def coll(name):
    return _db[name]


def next_seq(name):
    _seq[name] += 1
    return _seq[name]


def insert(name, rec):
    _db[name][rec["id"]] = rec
    return rec


def get(name, rid):
    return _db[name].get(rid)


def all_recs(name):
    return list(_db[name].values())


def find(name, **filters):
    out = []
    for rec in _db[name].values():
        ok = True
        for k, v in filters.items():
            if rec.get(k) != v:
                ok = False
                break
        if ok:
            out.append(rec)
    return out

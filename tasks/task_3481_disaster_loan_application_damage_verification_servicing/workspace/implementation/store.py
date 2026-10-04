"""In-memory data store. Empty at every boot; no seeding (per build contract)."""

import uuid

# kind -> {id: row}
db = {
    "declarations": {},
    "applicants": {},
    "applications": {},
    "credit_reviews": {},
    "verifications": {},
    "loans": {},
    "tranches": {},
    "milestones": {},
    "modifications": {},
    "settlements": {},
    "receivables": {},
    "servicing_actions": {},
    "payments": {},
    "grants": {},
}

_seq = [0]


def next_seq():
    _seq[0] += 1
    return _seq[0]


def new_id():
    return str(uuid.uuid4())


def put(kind, row):
    row["_seq"] = next_seq()
    db[kind][row["id"]] = row
    return row


def get(kind, rid):
    return db[kind].get(rid)


def all_rows(kind):
    """All rows of a kind in insertion (created_at) order."""
    return sorted(db[kind].values(), key=lambda r: r["_seq"])


def remove(kind, rid):
    db[kind].pop(rid, None)

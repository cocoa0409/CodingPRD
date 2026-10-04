# In-memory store (PRD: no persistence requirement; harness reboots per test).
# All dicts start EMPTY at boot — no seeding of any kind.
import itertools
import uuid


dealers = {}
end_users = {}
agreements = {}
families = {}
configurations = {}
orders = {}
phases = {}
windows = {}
punches = {}
claims = {}

# Monotonic insertion sequence: stable secondary sort after created_at (PRD 2.3
# default sort is created_at ascending; the logical clock makes ties common).
_seq = itertools.count(1)


def new_id():
    """Server-minted UUID with no type prefix (PRD 2.5)."""
    return str(uuid.uuid4())


def next_seq():
    return next(_seq)


def touch(entity):
    """Stamp a mutation: updated_at from the logical clock, version + 1 (PRD 2.5)."""
    import clock
    entity["updated_at"] = clock.now_iso()
    entity["version"] += 1

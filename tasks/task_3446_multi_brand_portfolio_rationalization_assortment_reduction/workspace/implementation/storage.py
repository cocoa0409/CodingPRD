"""In-memory data store.

Plain dicts keyed by id, created empty at boot. No seeding, no disk
persistence: every start.sh invocation yields a byte-fresh server.
"""

import itertools
import threading
import uuid

# Entity stores: id -> record (plain mutable dict).
brands = {}
items = {}
plants = {}
retailers = {}
cases = {}
divestitures = {}
tsas = {}
transfers = {}
runs = {}
negotiations = {}
cycles = {}
projects = {}

# Monotonic insertion sequence, used only as a stable (never-id) tie-break
# when created_at values coincide under the logical clock.
_seq = itertools.count(1)
_seq_lock = threading.Lock()


def next_seq():
    with _seq_lock:
        return next(_seq)


def new_id():
    """Server-minted UUID with no type prefix (PRD §2.5)."""
    return str(uuid.uuid4())

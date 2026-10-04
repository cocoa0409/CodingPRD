"""In-memory data store. Process-local dicts only — per-test-server restarts
wipe all state. NO seeding: the store starts empty on every boot."""
import uuid

from clock import CLOCK

carriers = {}
shippers = {}
tariffs = {}
contracts = {}
agreements = {}
licenses = {}
invoices = {}
disputes = {}
complaints = {}
proceedings = {}
congestion_reports = {}

_seq = 0


def next_seq():
    global _seq
    _seq += 1
    return _seq


def new_id():
    # Standard dashed UUID, e.g. "3f6b2a10-...." — never uuid4().hex.
    return str(uuid.uuid4())


def base_record(versioned=True):
    rec = {
        "id": new_id(),
        "created_at": CLOCK.now(),
        "_seq": next_seq(),
    }
    if versioned:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    return rec


def touch(rec):
    """Refresh updated_at and increment version on a mutated resource."""
    rec["updated_at"] = CLOCK.now()
    rec["version"] += 1

"""In-memory data stores. Plain dicts keyed by id; empty at every boot.
No seeding, no file persistence."""
import uuid

import clock

manufacturers = {}
factories = {}
standards = {}
jurisdictions = {}
projects = {}
samples = {}
construction_records = {}
certifications = {}
substitution_requests = {}
inspections = {}
mark_licenses = {}
label_batches = {}
field_evaluations = {}
withdrawal_notices = {}

_seq = 0
_listing_seq = 0


def next_seq():
    global _seq
    _seq += 1
    return _seq


def new_id():
    return str(uuid.uuid4())


def mint_listing_number():
    """'E' + zero-padded 6-digit sequence in creation order."""
    global _listing_seq
    _listing_seq += 1
    return "E%06d" % _listing_seq


def new_entity(store, fields):
    """Create an entity dict with the four system-managed common fields
    (PRD 2.4): id, created_at, updated_at, version (starts at 1)."""
    entity = {
        "id": new_id(),
        "created_at": clock.now(),
        "updated_at": clock.now(),
        "version": 1,
        "_seq": next_seq(),
    }
    entity.update(fields)
    store[entity["id"]] = entity
    return entity


def mutate(entity):
    """Every mutation refreshes updated_at and increments version (PRD 2.4),
    including automatic transitions and cascades."""
    entity["updated_at"] = clock.now()
    entity["version"] = int(entity.get("version", 1)) + 1
    return entity


def sorted_items(store):
    """created_at ascending (PRD 2.3); stable over insertion order for ties."""
    return sorted(store.values(), key=lambda e: (e["created_at"], e["_seq"]))

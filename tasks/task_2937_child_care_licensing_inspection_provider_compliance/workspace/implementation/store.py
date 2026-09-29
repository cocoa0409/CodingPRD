"""In-memory store. Every collection starts empty on every boot; nothing is seeded."""

import itertools
import uuid

import clock

_SEQ = itertools.count(1)

providers = {}
inspectors = {}
checklist_items = {}
staff_members = {}
background_checks = {}
rosters = {}
inspections = {}
violations = {}
complaints = {}
caps = {}
actions = {}
amendments = {}
reports = {}
postings = {}


def new_id():
    return str(uuid.uuid4())


def create(collection, rec, versioned=True):
    rec["id"] = new_id()
    rec["created_at"] = clock.now()
    rec["_seq"] = next(_SEQ)
    if versioned:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    collection[rec["id"]] = rec
    return rec


def touch(rec):
    """Refresh updated_at and increment version, exactly as a direct mutation does."""
    rec["updated_at"] = clock.now()
    rec["version"] = rec.get("version", 0) + 1
    return rec


def ordered(collection):
    """All rows ordered by created_at ascending (creation sequence breaks ties)."""
    return sorted(collection.values(), key=lambda r: (r["created_at"], r["_seq"]))


def by_provider(collection, provider_id):
    return [r for r in ordered(collection) if r.get("provider_id") == provider_id]


def provider_inspections(provider_id):
    return by_provider(inspections, provider_id)


def inspection_violations(inspection_id):
    return [r for r in ordered(violations) if r["inspection_id"] == inspection_id]


def provider_violations(provider_id):
    out = []
    for insp in provider_inspections(provider_id):
        out.extend(inspection_violations(insp["id"]))
    return out


def staff_of(provider_id):
    return by_provider(staff_members, provider_id)


def checks_of(staff_member_id):
    return [r for r in ordered(background_checks) if r["staff_member_id"] == staff_member_id]


def rosters_of(provider_id):
    return by_provider(rosters, provider_id)


def caps_of_inspection(inspection_id):
    return [r for r in ordered(caps) if r["inspection_id"] == inspection_id]


def checklist_by_code(code):
    for r in ordered(checklist_items):
        if r["code"] == code:
            return r
    return None

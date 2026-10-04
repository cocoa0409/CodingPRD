"""In-memory data store. Module-level dicts keyed by id; fresh process = empty.

NO seeding, preloading, or hardcoded entities at startup (skill contract).
created_at / updated_at / version follow PRD section 2.5: timestamps are
ISO 8601 UTC with three fractional digits taken from the logical clock (the
system runs on a logical clock, never wall-clock time), and version starts at
1 and increments by exactly 1 on every mutation, cascade-driven ones included.
"""
import uuid

import clock

device_makers = {}
programs = {}
compositions = {}
qual_cycles = {}
tanks = {}
campaigns = {}
commitments = {}
allocations = {}
licenses = {}
usage_reports = {}


def base_fields():
    """Common system-managed properties for a freshly created entity."""
    ts = clock.now()
    return {"id": str(uuid.uuid4()), "created_at": ts, "updated_at": ts, "version": 1}


def touch(entity):
    """Record a mutation: version +1 and updated_at refreshed (PRD 2.5)."""
    entity["version"] += 1
    entity["updated_at"] = clock.now()

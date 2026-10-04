"""In-memory data store.

Pure dicts keyed by id. The store starts completely empty on every boot;
nothing is seeded, preloaded, or hardcoded. Every entity is constructed
through the declared API surface.

Common system fields (PRD 2.5): id (server-minted UUID, no type prefix),
created_at / updated_at (ISO 8601 UTC, three fractional digits), version
(integer, starts at 1, +1 on every mutation including cascaded side effects).
"""

import uuid

from clock import wall_now_iso
from errors import ApiError, HTTP_STATUS

jurisdictions = {}
clients = {}
intake_requests = {}
cases = {}
evidence_items = {}
records_requests = {}
testing_authorizations = {}
lab_analyses = {}
legal_petitions = {}
compensation_claims = {}
reentry_providers = {}
reentry_referrals = {}
policy_initiatives = {}


def new_entity():
    """Base system fields for a freshly created entity."""
    now = wall_now_iso()
    return {
        "id": str(uuid.uuid4()),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }


def touch(entity):
    """Record a mutation: refresh updated_at and increment version."""
    entity["updated_at"] = wall_now_iso()
    entity["version"] += 1


def lookup(store, rid, error_id):
    """Existence check for a path or body id.

    A missing key, a null value, or a value of the wrong type all resolve to
    "does not exist" -> 404 (existence is priority 3, ahead of request-shape
    checks at priority 3.8).
    """
    ent = store.get(rid) if isinstance(rid, str) else None
    if ent is None:
        raise ApiError(error_id, HTTP_STATUS[error_id],
                       "Referenced resource does not exist: %r" % (rid,))
    return ent

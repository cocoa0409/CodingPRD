"""In-memory data store. Starts empty on every boot; no seeding."""
import uuid
from datetime import datetime, timezone

from envelope import now_iso


# Entity collections: id -> record dict
orgs = {}
credit_pools = {}
license_products = {}
license_grants = {}
extension_grants = {}
named_users = {}
deployment_servers = {}
compat_rules = {}
content_items = {}
api_keys = {}
credit_batches = {}
eligibility_verifications = {}

# Idempotency: idempotency_key -> (payload dict, batch id)
idempotency_index = {}

# Deterministic logical clock; default 2026-09-01T00:00:00Z, never wall clock.
DEFAULT_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
clock_current = DEFAULT_CLOCK


def new_id():
    return str(uuid.uuid4())


def new_record():
    """Common system fields for a fresh record."""
    ts = now_iso()
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1}


def touch(rec):
    rec["updated_at"] = now_iso()
    rec["version"] += 1


def pool_for_org(org_id):
    for p in credit_pools.values():
        if p["organization_id"] == org_id:
            return p
    return None

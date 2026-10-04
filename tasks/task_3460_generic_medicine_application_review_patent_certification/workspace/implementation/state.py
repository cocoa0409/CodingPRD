"""In-memory store. Starts empty on every boot; nothing is seeded anywhere."""
import uuid

from clock import now_iso

KINDS = (
    "applicants",
    "reference_products",
    "patents",
    "protections",
    "applications",
    "studies",
    "certifications",
    "notices",
    "cycles",
    "amendments",
    "facilities",
    "inspections",
    "supplements",
    "awards",
)

STORE = {kind: {} for kind in KINDS}

# Global monotonic commit order: breaks created_at ties and orders
# "latest outcome commit" lookups (facility clearance, PRD 3.6).
_seq = [0]


def next_seq():
    _seq[0] += 1
    return _seq[0]


def create_entity(kind, fields):
    ent = {
        "id": str(uuid.uuid4()),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
        "seq": next_seq(),
    }
    ent.update(fields)
    STORE[kind][ent["id"]] = ent
    return ent


def touch(ent):
    """Every mutation of a resource bumps version by one and re-stamps it."""
    ent["updated_at"] = now_iso()
    ent["version"] += 1
    ent["seq"] = next_seq()


def get(kind, entity_id):
    return STORE[kind].get(entity_id)

"""Entity factory helpers: common fields (id, created_at, updated_at, version)."""
import uuid

from db import store, fmt_dt


def new_entity(with_version=True):
    """Return the common-field skeleton for a new entity."""
    now = store.now()
    e = {
        "id": str(uuid.uuid4()),
        "created_at": fmt_dt(now),
    }
    if with_version:
        e["updated_at"] = fmt_dt(now)
        e["version"] = 1
    return e


def touch(entity):
    """Bump updated_at + version on an entity (mutation discipline)."""
    entity["updated_at"] = fmt_dt(store.now())
    entity["version"] = entity.get("version", 0) + 1

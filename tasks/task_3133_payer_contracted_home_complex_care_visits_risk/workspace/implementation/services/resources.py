"""Resource helpers: UUID minting, common fields, touch (version bump)."""
import uuid

from services.clock import now_iso


def new_id():
    return str(uuid.uuid4())


def base_fields():
    """Common system-managed fields per PRD §2.4."""
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }


def touch(entity):
    """Refresh updated_at and increment version by exactly 1 (PRD §2.4)."""
    entity["updated_at"] = now_iso()
    entity["version"] = int(entity.get("version", 1)) + 1


def refresh_timestamp_only(entity):
    """Refresh updated_at without a version bump (rarely used)."""
    entity["updated_at"] = now_iso()

"""Entity helpers: UUIDs, common fields, serialization."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict

from services.calculations import to_iso8601_ms, now_iso


def new_uuid() -> str:
    return str(uuid.uuid4())


def stamp_new(entity: Dict[str, Any]) -> Dict[str, Any]:
    """Set id/created_at/updated_at/version on a fresh entity."""
    ts = now_iso()
    entity["id"] = new_uuid()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    return entity


def stamp_new_log(entity: Dict[str, Any]) -> Dict[str, Any]:
    """Append-only log row: id + created_at only."""
    entity["id"] = new_uuid()
    entity["created_at"] = now_iso()
    return entity


def touch(entity: Dict[str, Any]) -> None:
    """Refresh updated_at and increment version."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1


def iso_from_dt(dt: datetime) -> str:
    return to_iso8601_ms(dt)

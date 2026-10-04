"""In-memory data store. Starts empty on every boot."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional


# Logical clock: server-maintained, never wall-clock. Startup default is
# exactly 2026-09-01T00:00:00Z; advanced only via POST /_clock/set_current_utc.
_DEFAULT_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


class DB:
    def __init__(self) -> None:
        self.vendors: Dict[str, dict] = {}
        self.jurisdiction_rules: Dict[str, dict] = {}
        self.stores: Dict[str, dict] = {}
        self.lots: Dict[str, dict] = {}
        self.screenings: Dict[str, dict] = {}
        self.allocations: Dict[str, dict] = {}
        self.aisle_assignments: Dict[str, dict] = {}
        self.members: Dict[str, dict] = {}
        self.events: Dict[str, dict] = {}
        self.purchases: Dict[str, dict] = {}
        self.dispositions: Dict[str, dict] = {}
        self.clock: datetime = _DEFAULT_CLOCK

    def new_id(self) -> str:
        return str(uuid.uuid4())

    def now(self) -> datetime:
        return self.clock

    def now_iso(self) -> str:
        return format_ts(self.clock)

    def bump(self, entity: dict) -> None:
        entity["updated_at"] = self.now_iso()
        entity["version"] = entity.get("version", 1) + 1


db = DB()


def format_ts(dt: datetime) -> str:
    """ISO 8601 UTC with three fractional digits, e.g. 2026-09-01T00:00:00.000Z"""
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms


def parse_ts(s: Any) -> Optional[datetime]:
    """Parse an ISO 8601 timestamp. Returns None on failure."""
    if not isinstance(s, str):
        return None
    text = s.strip()
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def round_half_up_cents(value) -> int:
    from decimal import Decimal, ROUND_HALF_UP
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2dp(value) -> str:
    """Round to 2 decimal places, half-up. Returns string for exact comparison."""
    from decimal import Decimal, ROUND_HALF_UP
    return str(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

"""In-memory data store for the Broker Price Opinion & Valuation Services API.

All data lives in plain Python dicts keyed by resource id. The store starts
empty on every process boot (no seeding, no persistence).
"""

import itertools
import uuid
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Logical clock (PRD section 2.10)
# ---------------------------------------------------------------------------

_logical_now: datetime = None  # set in init_store()


def init_clock() -> None:
    global _logical_now
    _logical_now = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def logical_now() -> datetime:
    return _logical_now


def set_logical_now(dt: datetime) -> None:
    global _logical_now
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    _logical_now = dt.astimezone(timezone.utc)


def fmt_ts(dt) -> str:
    """Format a datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso() -> str:
    return fmt_ts(_logical_now)


def parse_iso(s):
    """Parse an ISO 8601 string to a timezone-aware UTC datetime.

    Returns None on failure.
    """
    if s is None or not isinstance(s, str):
        return None
    cleaned = s.strip()
    if not cleaned:
        return None
    if cleaned.endswith("Z") or cleaned.endswith("z"):
        cleaned = cleaned[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(cleaned)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Stores — one dict per entity type, keyed by id (UUID string, no prefix)
# ---------------------------------------------------------------------------

client_accounts: dict = {}
brokers: dict = {}
broker_licenses: dict = {}
state_regulations: dict = {}  # keyed by id
properties: dict = {}
orders: dict = {}
comparables: dict = {}
photos: dict = {}
fee_lines: dict = {}
qc_reviews: dict = {}
revision_requests: dict = {}
payout_batches: dict = {}
volume_forecasts: dict = {}

# Global monotonically increasing insertion sequence (stable list ordering)
_seq = itertools.count(1)


def next_seq() -> int:
    return next(_seq)


def new_id() -> str:
    return str(uuid.uuid4())


def find_state_regulation_by_code(state_code: str):
    for reg in state_regulations.values():
        if reg["state_code"] == state_code:
            return reg
    return None


def init_store() -> None:
    """Reset all stores to empty. Called once at startup."""
    client_accounts.clear()
    brokers.clear()
    broker_licenses.clear()
    state_regulations.clear()
    properties.clear()
    orders.clear()
    comparables.clear()
    photos.clear()
    fee_lines.clear()
    qc_reviews.clear()
    revision_requests.clear()
    payout_batches.clear()
    volume_forecasts.clear()
    init_clock()


def stamp_new(record: dict) -> dict:
    """Populate common system fields on a freshly created mutable record."""
    ts = logical_now()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    record["_seq"] = next_seq()
    return record


def stamp_new_append_only(record: dict) -> dict:
    """Populate system fields for append-only records (no updated_at/version).

    Applies to PhotoEvidence, QCRevisionRequest, VolumeForecast (PRD 2.4).
    """
    record["created_at"] = logical_now()
    record["_seq"] = next_seq()
    return record


def touch(record: dict) -> None:
    """Refresh updated_at and increment version by exactly 1 (PRD 2.4/2.7)."""
    record["updated_at"] = logical_now()
    record["version"] = record.get("version", 1) + 1

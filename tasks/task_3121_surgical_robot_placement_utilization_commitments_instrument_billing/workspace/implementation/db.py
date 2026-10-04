"""In-memory data store, logical clock and shared coercion helpers.

Storage is process-local Python dicts only. There is deliberately no file, no
/tmp cache and no external persistence, so re-launching start.sh (which the
per-test-server isolation does before every pytest test) starts from a
completely empty store.

Nothing here is seeded at import time: every collection below starts as an
empty dict and the module owns no entity data whatsoever.
"""

import uuid
from datetime import datetime, timedelta, timezone

DAY = timedelta(days=1)
HOUR = timedelta(hours=1)

# PRD §2.4 — the fixed startup default the logical clock reads before any call.
DEFAULT_CLOCK = "2026-09-01T00:00:00Z"


class Store:
    """One dict per entity collection, keyed by the entity's own id."""

    COLLECTIONS = (
        "hospital_accounts",
        "site_readiness_reviews",
        "system_configurations",
        "placement_agreements",
        "robot_systems",
        "surgeon_training_records",
        "credentialing_evidence",
        "utilization_cycles",
        "procedure_cases",
        "loaner_dispatches",
        "service_contracts",
        "incidents",
        "software_releases",
        "software_deployments",
        "expansion_reviews",
        "consumption_ledgers",
        "transfer_transactions",
        "proctor_cases",
    )

    def __init__(self):
        for name in self.COLLECTIONS:
            setattr(self, name, {})
        # Logical clock (PRD §2.4). Every timestamp in this API comes from this
        # clock; the server never reads real wall-clock time.
        self.clock = parse_iso8601(DEFAULT_CLOCK)
        self.seq = 0


# ---------------------------------------------------------------------------
# Datetime helpers
# ---------------------------------------------------------------------------

def parse_iso8601(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_iso(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD §2.7 / §2.2)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


# kept for readability at call sites
stamp = to_iso
to_z = to_iso


# The single process-local store. Constructed after the helpers above so the
# fixed startup clock can be parsed at import time.
DB = Store()


# ---------------------------------------------------------------------------
# Identity / common fields
# ---------------------------------------------------------------------------

def new_id():
    return str(uuid.uuid4())


def next_seq():
    DB.seq += 1
    return DB.seq


def touch(record, instant=None):
    """Refresh updated_at and bump version — PRD §2.7."""
    if record is None:
        return None
    if instant is None:
        instant = DB.clock
    record["updated_at"] = to_iso(instant)
    record["version"] = int(record.get("version", 0)) + 1
    return record


def base_record(extra=None, instant=None):
    if instant is None:
        instant = DB.clock
    rec = {
        "id": new_id(),
        "created_at": to_iso(instant),
        "updated_at": to_iso(instant),
        "version": 1,
        "_seq": next_seq(),
    }
    if extra:
        rec.update(extra)
    return rec


def check_version(record, body, field):
    """Optimistic concurrency on a resource's own version (PRD §2.14).

    An absent field is not an error (the check is skipped); a supplied field
    that differs from the stored value is ERR_STALE_VERSION.
    """
    from errors import ApiError
    if isinstance(body, dict) and field in body and body.get(field) is not None:
        if as_int(body.get(field)) != int(record.get("version", 0)):
            raise ApiError("ERR_STALE_VERSION")
    return record


# ---------------------------------------------------------------------------
# Scalar coercion for request bodies
# ---------------------------------------------------------------------------

def as_int(value, default=0):
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default


def as_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "y", "on")
    return bool(value)


def as_str(value, default=""):
    if value is None:
        return default
    return str(value)


def as_list(value, default=None):
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [] if default is None else default


def combo_key(cycle_start, index):
    return "%s|%s" % (to_iso(cycle_start), index)
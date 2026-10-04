"""In-memory data store. Starts completely empty on every process boot;
no entity is ever seeded or preloaded. The logical clock defaults to
2026-09-01T00:00:00Z and only moves via POST /_clock/set_current_utc."""
import uuid
from datetime import datetime, timezone

# Entity tables, keyed by id.
schools = {}
teachers = {}
vendors = {}
catalog_items = {}
projects = {}
project_items = {}
donors = {}
donations = {}
match_campaigns = {}
purchase_orders = {}
thank_you_packages = {}
fraud_cases = {}
equity_funds = {}

# Monotonic creation sequence: stable tiebreak for created_at ordering.
_seq = [0]

# Server-side logical clock (never falls back to wall-clock time).
_logical_now = [datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)]


def next_seq():
    _seq[0] += 1
    return _seq[0]


def new_id():
    return str(uuid.uuid4())


def wall_now():
    return datetime.now(timezone.utc)


def logical_now():
    return _logical_now[0]


def set_logical_now(dt):
    _logical_now[0] = dt


def base_record():
    """Common system-managed fields for every primary resource
    (ThankYouPackage excepted: it carries only id and created_at)."""
    now = wall_now()
    return {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next_seq(),
    }


def bare_record():
    """id + created_at only (ThankYouPackage)."""
    return {"id": new_id(), "created_at": wall_now(), "_seq": next_seq()}


def touch(rec):
    """Refresh updated_at and bump the OCC version on every mutation."""
    rec["updated_at"] = wall_now()
    rec["version"] += 1

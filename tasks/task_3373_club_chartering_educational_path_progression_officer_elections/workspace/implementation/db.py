"""In-memory data store.

The store is a set of plain dicts keyed by server-minted id.  It starts EMPTY on
every process boot: nothing is seeded, preloaded or hardcoded here.  Every entity
any caller sees was created through a declared endpoint.
"""

import uuid
from datetime import datetime, timedelta, timezone

from errors import bad_request

# --- collections (dict preserves insertion order == creation order) ----------
CLUBS = {}
MEMBERS = {}
MEMBERSHIPS = {}
PATHS = {}
COMPLETIONS = {}
MEETINGS = {}
ASSIGNMENTS = {}
OFFICER_TERMS = {}
CONTESTS = {}
ENTRIES = {}
VISITS = {}

COLLECTIONS = {
    "clubs": CLUBS,
    "members": MEMBERS,
    "memberships": MEMBERSHIPS,
    "education_paths": PATHS,
    "project_completions": COMPLETIONS,
    "meetings": MEETINGS,
    "role_assignments": ASSIGNMENTS,
    "officer_terms": OFFICER_TERMS,
    "contests": CONTESTS,
    "contest_entries": ENTRIES,
    "area_visits": VISITS,
}


def new_id():
    """Server-minted opaque UUID with no type prefix (PRD section 2.4)."""
    return str(uuid.uuid4())


# --- timestamps -------------------------------------------------------------
def utcnow():
    return datetime.now(timezone.utc)


def iso(dt):
    """ISO 8601 UTC rendered with exactly three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(value, field="timestamp"):
    """Parse a caller-supplied ISO 8601 instant; ERR_INVALID_REQUEST when bad."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str):
        raise bad_request("Field '%s' must be an ISO 8601 timestamp." % field)
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise bad_request("Field '%s' is not a valid ISO 8601 timestamp." % field)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def days(n):
    return timedelta(days=n)


# --- entity lifecycle -------------------------------------------------------
def create(collection, fields):
    """Insert a new row: stamps id, created_at, updated_at and version=1."""
    now = utcnow()
    row = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    row.update(fields)
    collection[row["id"]] = row
    return row


def touch(row):
    """Any mutation of a resource refreshes updated_at and bumps version.

    PRD section 2.4: a server-side recomputation of a derived field is a
    mutation of the resource that owns it, exactly like a caller-driven edit.
    """
    row["updated_at"] = utcnow()
    row["version"] = row.get("version", 1) + 1
    return row


def get(collection, entity_id):
    """Fetch a row by id; raises ERR_NOT_FOUND when absent."""
    from errors import ApiError

    row = collection.get(entity_id)
    if row is None:
        raise ApiError("ERR_NOT_FOUND")
    return row


def find(collection, entity_id):
    if entity_id is None:
        return None
    return collection.get(entity_id)


# --- request payload helpers ------------------------------------------------
def require(body, field):
    if not isinstance(body, dict) or field not in body or body[field] is None:
        raise bad_request("Field '%s' is required." % field)
    return body[field]


def require_str(body, field, allow_empty=False):
    value = require(body, field)
    if not isinstance(value, str):
        raise bad_request("Field '%s' must be a string." % field)
    if not allow_empty and value.strip() == "":
        raise bad_request("Field '%s' must be a non-empty string." % field)
    return value


def optional(body, field, default=None):
    if not isinstance(body, dict):
        return default
    value = body.get(field)
    return default if value is None else value


def require_int(body, field):
    value = require(body, field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad_request("Field '%s' must be an integer." % field)
    return value


def require_enum(body, field, allowed):
    value = require(body, field)
    if value not in allowed:
        raise bad_request(
            "Field '%s' must be one of %s." % (field, ", ".join(sorted(allowed)))
        )
    return value


def optional_enum(body, field, allowed, default=None):
    value = body.get(field) if isinstance(body, dict) else None
    if value is None:
        return default
    if value not in allowed:
        raise bad_request(
            "Field '%s' must be one of %s." % (field, ", ".join(sorted(allowed)))
        )
    return value


def require_bool(body, field):
    value = require(body, field)
    if not isinstance(value, bool):
        raise bad_request("Field '%s' must be a boolean." % field)
    return value


def optional_bool(body, field, default=False):
    value = body.get(field) if isinstance(body, dict) else None
    if value is None:
        return default
    if not isinstance(value, bool):
        raise bad_request("Field '%s' must be a boolean." % field)
    return value


def optional_int(body, field, default=None):
    value = body.get(field) if isinstance(body, dict) else None
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad_request("Field '%s' must be an integer." % field)
    return value


def paginate(items, limit, offset):
    """Slice a filtered collection for a paged list read."""
    total = len(items)
    window = items[offset : offset + limit]
    return window, total, (offset + len(window)) < total


def parse_pagination(query):
    """limit defaults to 10 and lies between 1 and 100; offset defaults to 0."""
    limit_raw = query.get("limit")
    offset_raw = query.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None and limit_raw != "":
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise bad_request("Query parameter 'limit' must be an integer.")
    if offset_raw is not None and offset_raw != "":
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise bad_request("Query parameter 'offset' must be an integer.")
    if limit < 1 or limit > 100:
        raise bad_request("Query parameter 'limit' must lie between 1 and 100.")
    if offset < 0:
        raise bad_request("Query parameter 'offset' must be at least 0.")
    return limit, offset

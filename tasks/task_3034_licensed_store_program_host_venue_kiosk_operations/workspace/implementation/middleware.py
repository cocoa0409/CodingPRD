"""Auth header extraction and role checking (PRD §2.1, SCAFFOLD validations p1-p4)."""
import re
import uuid as uuid_mod
from datetime import datetime, date, timezone

from flask import request

from db import db
import errors as E

KNOWN_ROLES = {
    "BrandProgramAdmin",
    "LicenseeManager",
    "HostVenueManager",
    "DistributorAgent",
    "BrandInspector",
    "LoyaltyMember",
}


def auth():
    """Validate X-User-ID / X-User-Role headers. Returns (user_id, role)."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in KNOWN_ROLES:
        raise E.err_unauthenticated()
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        raise E.err_forbidden()


def licensee_of_store(store):
    ag = db.license_agreements[store["agreement_id"]]
    return ag["licensee_id"]


def check_licensee_scope(uid, role, licensee_id):
    """If the caller is a LicenseeManager, its X-User-ID must equal licensee_id."""
    if role == "LicenseeManager" and uid != licensee_id:
        raise E.err_forbidden()


def check_member_scope(uid, role, member_id):
    if role == "LoyaltyMember" and uid != member_id:
        raise E.err_forbidden()


# ---------------------------------------------------------------------------
# Body / field helpers
# ---------------------------------------------------------------------------

def body():
    if not request.data:
        return {}
    try:
        b = request.get_json(force=False, silent=False)
    except Exception:
        raise E.err_invalid_request("Request body must be valid JSON")
    if b is None:
        return {}
    if not isinstance(b, dict):
        raise E.err_invalid_request("Request body must be a JSON object")
    return b


def req_str(b, name):
    v = b.get(name)
    if not isinstance(v, str):
        raise E.err_invalid_request(f"Field '{name}' is required and must be a string")
    return v


def req_bool(b, name):
    v = b.get(name)
    if not isinstance(v, bool):
        raise E.err_invalid_request(f"Field '{name}' is required and must be a boolean")
    return v


def req_int(b, name, minimum=None, maximum=None):
    v = b.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise E.err_invalid_request(f"Field '{name}' is required and must be an integer")
    if minimum is not None and v < minimum:
        raise E.err_invalid_request(f"Field '{name}' is out of range")
    if maximum is not None and v > maximum:
        raise E.err_invalid_request(f"Field '{name}' is out of range")
    return v


def opt_str(b, name, default=None):
    v = b.get(name, default)
    if v is not None and not isinstance(v, str):
        raise E.err_invalid_request(f"Field '{name}' must be a string")
    return v


def opt_bool(b, name, default=None):
    v = b.get(name, default)
    if v is not None and not isinstance(v, bool):
        raise E.err_invalid_request(f"Field '{name}' must be a boolean")
    return v


def opt_int(b, name, default=None, minimum=None, maximum=None):
    v = b.get(name, default)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise E.err_invalid_request(f"Field '{name}' must be an integer")
    if minimum is not None and v < minimum:
        raise E.err_invalid_request(f"Field '{name}' is out of range")
    if maximum is not None and v > maximum:
        raise E.err_invalid_request(f"Field '{name}' is out of range")
    return v


def req_enum(b, name, allowed):
    v = req_str(b, name)
    if v not in allowed:
        raise E.err_invalid_request(f"Field '{name}' must be one of {sorted(allowed)}")
    return v


def req_date(b, name):
    v = req_str(b, name)
    try:
        return date.fromisoformat(v)
    except Exception:
        raise E.err_invalid_request(f"Field '{name}' must be an ISO date (YYYY-MM-DD)")


def opt_date(b, name, default=None):
    v = b.get(name)
    if v is None:
        return default
    if not isinstance(v, str):
        raise E.err_invalid_request(f"Field '{name}' must be an ISO date (YYYY-MM-DD)")
    try:
        return date.fromisoformat(v)
    except Exception:
        raise E.err_invalid_request(f"Field '{name}' must be an ISO date (YYYY-MM-DD)")


_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def req_time_hhmm(b, name):
    v = req_str(b, name)
    if not _TIME_RE.match(v):
        raise E.err_invalid_request(f"Field '{name}' must be HH:MM 24h")
    return v


def opt_time_hhmm(b, name, default=None):
    v = b.get(name)
    if v is None:
        return default
    if not isinstance(v, str) or not _TIME_RE.match(v):
        raise E.err_invalid_request(f"Field '{name}' must be HH:MM 24h")
    return v


def req_datetime(b, name):
    v = req_str(b, name)
    return parse_iso8601(v)


def opt_datetime(b, name, default=None):
    v = b.get(name)
    if v is None:
        return default
    if not isinstance(v, str):
        raise E.err_invalid_request(f"Field '{name}' must be an ISO 8601 datetime")
    return parse_iso8601(v)


def parse_iso8601(v):
    if not isinstance(v, str):
        raise E.err_invalid_request("Expected an ISO 8601 timestamp string")
    s = v.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except Exception:
        raise E.err_invalid_request(f"Malformed ISO 8601 timestamp: {v!r}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_clock(dt):
    """Format a logical-clock datetime as ISO 8601 UTC with three fractional digits."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:23] + "Z"


# ---------------------------------------------------------------------------
# Pagination (SCAFFOLD response_envelope.pagination_fields/defaults)
# ---------------------------------------------------------------------------

def pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise E.err_invalid_request("'limit' must be an integer")
        if limit < 1 or limit > 100:
            raise E.err_invalid_request("'limit' must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise E.err_invalid_request("'offset' must be an integer")
        if offset < 0:
            raise E.err_invalid_request("'offset' must be >= 0")
    return limit, offset


def paginate(items, extra_sort=None):
    limit, offset = pagination()
    ordered = list(items)
    if extra_sort:
        ordered.sort(key=extra_sort)
    else:
        ordered.sort(key=lambda x: (x["created_at"], x["id"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, limit, offset, total


def query_filter(request_args, name):
    v = request_args.get(name)
    return v


def new_id():
    return str(uuid_mod.uuid4())


def sys_ts():
    """created_at/updated_at timestamps: ISO 8601 UTC, three fractional digits."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:23] + "Z"


def make_resource(fields):
    now = sys_ts()
    r = {"id": new_id(), "created_at": now, "updated_at": now, "version": 1}
    r.update(fields)
    return r


def touch(res):
    res["updated_at"] = sys_ts()
    res["version"] += 1

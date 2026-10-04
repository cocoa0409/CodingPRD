"""Auth, pagination, field validation, and date helpers."""
import re
from datetime import datetime, date, timedelta, timezone

from flask import request

from store import err, CLOCK

ROLES = {
    "ProRegistrar",
    "ProLicensingAdmin",
    "RateCourtOfficer",
    "RoyaltyDistributor",
    "FinanceOfficer",
    "Publisher",
    "Songwriter",
    "Licensee",
    "ProSystemAdmin",
}

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def auth():
    """Return (user_id, role). Raises ERR_UNAUTHENTICATED on missing/invalid."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or invalid X-User-ID / X-User-Role headers")
    return user_id, role


def require_role(role, allowed):
    if role not in allowed:
        raise err("ERR_FORBIDDEN", f"Role {role} is not permitted for this endpoint")


def get_json():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise err("ERR_VALIDATION", "Request body must be a JSON object")
    return data


def parse_limit_offset():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err("ERR_VALIDATION", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_VALIDATION", "limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err("ERR_VALIDATION", "offset must be an integer")
        if offset < 0:
            raise err("ERR_VALIDATION", "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    items = sorted(items, key=lambda r: (r["created_at"], r["id"]))
    total = len(items)
    return items[offset : offset + limit], total


def parse_iso_date(value, field):
    """Validate an ISO date string YYYY-MM-DD and return a datetime.date."""
    if not isinstance(value, str) or not _DATE_RE.match(value):
        raise err("ERR_VALIDATION", f"{field} must be an ISO date (YYYY-MM-DD)")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise err("ERR_VALIDATION", f"{field} must be a valid ISO date")


def parse_iso_datetime(value, field):
    if not isinstance(value, str):
        raise err("ERR_VALIDATION", f"{field} must be an ISO 8601 datetime string")
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        raise err("ERR_VALIDATION", f"{field} must be a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def require_enum(value, allowed, field):
    if not isinstance(value, str) or value not in allowed:
        raise err(
            "ERR_VALIDATION",
            f"{field} must be one of {sorted(allowed)}",
        )
    return value


def require_int(value, field, min_value=None, max_value=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise err("ERR_VALIDATION", f"{field} must be an integer")
    if min_value is not None and value < min_value:
        raise err("ERR_VALIDATION", f"{field} must be >= {min_value}")
    if max_value is not None and value > max_value:
        raise err("ERR_VALIDATION", f"{field} must be <= {max_value}")
    return value


def require_str(value, field):
    if not isinstance(value, str) or not value:
        raise err("ERR_VALIDATION", f"{field} must be a non-empty string")
    return value


def clock_date():
    return CLOCK.now().date()


def add_days(d, days):
    return d + timedelta(days=days)

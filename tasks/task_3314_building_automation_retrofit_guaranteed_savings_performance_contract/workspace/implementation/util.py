"""Shared utilities: ids, timestamps, field validation, pagination, auth."""
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError

ROLES = ("PlatformAdmin", "ESCOEngineer", "OwnerRep", "LenderOfficer")

_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$")


def new_id():
    return str(uuid.uuid4())


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_dt(value, field):
    if not isinstance(value, str) or not _ISO_RE.match(value):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"{field} must be an ISO 8601 datetime")
    s = value
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"{field} is not a valid datetime")
    if dt.tzinfo is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"{field} must include a timezone")
    return dt.astimezone(timezone.utc)


def body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def req_string(data, field):
    v = data.get(field)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_INVALID_REQUEST", 400, f"{field} is required and must be a string")
    return v


def opt_string(data, field):
    v = data.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"{field} must be a string")
    return v


def req_int(data, field, min_v=None, max_v=None):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"{field} must be an integer")
    if min_v is not None and v < min_v:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"{field} is below its minimum")
    if max_v is not None and v > max_v:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"{field} exceeds its maximum")
    return v


def req_number(data, field, min_v=None, max_v=None, strict_min=False):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"{field} must be a number")
    try:
        d = Decimal(str(v))
    except InvalidOperation:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"{field} must be a number")
    if min_v is not None:
        if strict_min and d <= Decimal(str(min_v)):
            raise ApiError("ERR_INVALID_REQUEST", 400, f"{field} must be greater than {min_v}")
        if not strict_min and d < Decimal(str(min_v)):
            raise ApiError("ERR_INVALID_REQUEST", 400, f"{field} must be at least {min_v}")
    if max_v is not None and d > Decimal(str(max_v)):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"{field} must be at most {max_v}")
    return d


def opt_number(data, field, min_v=None, max_v=None, strict_min=False):
    if field not in data or data.get(field) is None:
        return None
    return req_number(data, field, min_v, max_v, strict_min)


def req_enum(data, field, allowed):
    v = data.get(field)
    if v not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"{field} must be one of {sorted(allowed)}")
    return v


def validate_rate_schedule(rs):
    if not isinstance(rs, list) or len(rs) == 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "rate_schedule must be a non-empty array of tiers")
    tiers = []
    for i, tier in enumerate(rs):
        if not isinstance(tier, dict) or "up_to_kwh" not in tier or "cents_per_kwh" not in tier:
            raise ApiError("ERR_INVALID_REQUEST", 400, "each rate_schedule tier needs up_to_kwh and cents_per_kwh")
        up_to = tier.get("up_to_kwh")
        price = tier.get("cents_per_kwh")
        if up_to is not None and (isinstance(up_to, bool) or not isinstance(up_to, (int, float)) or up_to <= 0):
            raise ApiError("ERR_INVALID_REQUEST", 400, "up_to_kwh must be a positive number or null")
        if isinstance(price, bool) or not isinstance(price, (int, float)) or price <= 0:
            raise ApiError("ERR_INVALID_REQUEST", 400, "cents_per_kwh must be a positive number")
        tiers.append({"up_to_kwh": up_to, "cents_per_kwh": price})
    if tiers[0]["up_to_kwh"] is None:
        # a single unbounded tier is fine only if it is also the last; first tier
        # must be > 0 per spec — null means unbounded which is only allowed last.
        if len(tiers) > 1:
            raise ApiError("ERR_INVALID_REQUEST", 400, "only the final tier may be unbounded")
    for tier in tiers[:-1]:
        if tier["up_to_kwh"] is None:
            raise ApiError("ERR_INVALID_REQUEST", 400, "only the final tier may be unbounded")
    if tiers[-1]["up_to_kwh"] is not None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "the final rate_schedule tier must have up_to_kwh null")
    for i in range(1, len(tiers)):
        if tiers[i]["up_to_kwh"] is not None and tiers[i]["up_to_kwh"] <= tiers[i - 1]["up_to_kwh"]:
            raise ApiError("ERR_INVALID_REQUEST", 400, "rate_schedule tiers must be contiguous and increasing")
    return tiers


def paginate_args():
    try:
        limit = int(request.args.get("limit", 10))
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "limit and offset must be integers")
    if limit < 1 or limit > 100:
        raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be between 1 and 100")
    if offset < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be >= 0")
    return limit, offset


def paginate_list(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + limit) < total
    return page, {"limit": limit, "offset": offset, "total_count": total, "has_more": has_more}


def require_roles(*allowed):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not isinstance(uid, str) or not role or role not in ROLES:
        raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
                       "X-User-ID and X-User-Role headers are required and must be well-formed")
    if allowed and role not in allowed:
        raise ApiError("ERR_INSUFFICIENT_PERMISSIONS", 403, "role is not permitted to call this endpoint")
    return uid, role


def touch(rec):
    rec["updated_at"] = now_iso()
    rec["version"] += 1

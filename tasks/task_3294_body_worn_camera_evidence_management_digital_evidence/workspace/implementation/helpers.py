import random
import re
import string
import uuid
from datetime import datetime, timezone

from flask import jsonify, request

import db
from errors import ApiError, err_validation

ALLOWED_UNKNOWN_FIELDS = {"payload", "content", "media", "data", "file", "bytes"}


def iso_now():
    """Current logical UTC timestamp with 3 fractional digits."""
    if db.use_wallclock():
        dt = datetime.now(timezone.utc)
    else:
        dt = parse_dt(db.get_clock())
    return format_dt(dt)


def format_dt(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    ms = dt.microsecond // 1000
    return "%s.%03dZ" % (base, ms)


def format_dt_plain(dt):
    """Derived logical timestamps (retention_due_at, expires_at, unlinked_at)
    render without the fractional part when the value lands on a whole
    second; envelope timestamps (created_at/updated_at/api_request_timestamp)
    keep the three fractional digits required by PRD section 2."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return format_dt(dt)


def parse_dt(value):
    if value is None:
        return None
    s = str(value).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def new_id():
    return str(uuid.uuid4())


def request_id():
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return "req_" + suffix


def make_meta():
    return {"api_request_id": request_id(), "api_request_timestamp": iso_now()}


def success_obj(data, status=200):
    body = {"meta": make_meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def success_arr(items, total, limit, offset, status=200):
    meta = make_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(items)) < total
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status


def error_response(err):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def parse_pagination(args):
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err_validation("limit must be an integer")
        if limit < 1 or limit > 100:
            raise err_validation("limit must be between 1 and 100")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err_validation("offset must be an integer")
        if offset < 0:
            raise err_validation("offset must be >= 0")
    return limit, offset


def paginate(items):
    items = sorted(items, key=lambda x: (x.get("created_at") or "", x.get("id") or ""))
    total = len(items)
    limit, offset = parse_pagination(request.args)
    page = items[offset:offset + limit]
    return success_arr(page, total, limit, offset)


def body():
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        raise err_validation("Request body must be a JSON object")
    return data


def get_field(data, name, required=True, allowed=None, allow_null=False):
    present = name in data and data[name] is not None
    if not present:
        if allow_null and name in data:
            return None
        if required:
            raise err_validation("Missing required field: %s" % name)
        return None
    return data[name]


def reject_unknown(data, allowed_fields):
    for key in data:
        if key not in allowed_fields and key.lower() not in ALLOWED_UNKNOWN_FIELDS:
            raise err_validation("Unknown field: %s" % key)


def require_bool(data, name, required=True):
    v = get_field(data, name, required=required)
    if v is None:
        return None
    if not isinstance(v, bool):
        raise err_validation("%s must be a boolean" % name)
    return v


def require_int(data, name, required=True, allow_null=False):
    v = get_field(data, name, required=required, allow_null=allow_null)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_validation("%s must be an integer" % name)
    return v


def require_str(data, name, required=True, allow_null=False):
    v = get_field(data, name, required=required, allow_null=allow_null)
    if v is None:
        return None
    if not isinstance(v, str):
        raise err_validation("%s must be a string" % name)
    return v


def require_enum(data, name, values, required=True, allow_null=False):
    v = require_str(data, name, required=required, allow_null=allow_null)
    if v is None:
        return None
    if v not in values:
        raise err_validation("%s must be one of %s" % (name, ", ".join(values)))
    return v


HEX64 = re.compile(r"^[0-9a-f]{64}$")


def require_hash(data, name, required=True):
    v = require_str(data, name, required=required)
    if v is None:
        return None
    if not HEX64.match(v):
        raise err_validation("%s must be exactly 64 lowercase hex characters" % name)
    return v


def require_dt(data, name, required=True):
    v = require_str(data, name, required=required)
    if v is None:
        return None
    dt = parse_dt(v)
    if dt is None:
        raise err_validation("%s must be an ISO 8601 timestamp" % name)
    return format_dt(dt)


def touch(resource):
    """Bump updated_at and version on a mutable resource."""
    resource["updated_at"] = iso_now()
    resource["version"] = resource.get("version", 1) + 1


def new_resource(fields):
    now = iso_now()
    r = {"id": new_id(), "created_at": now, "updated_at": now, "version": 1}
    r.update(fields)
    return r


def new_log_entry(fields):
    r = {"id": new_id(), "created_at": iso_now()}
    r.update(fields)
    return r


def write_audit(agency_id, actor, action, entity_type, entity_id, detail=""):
    entry = new_log_entry({
        "agency_id": agency_id,
        "actor_role": actor["role"],
        "actor_id": actor["user_id"],
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "detail": detail,
    })
    db.collection("audit_log")[entry["id"]] = entry
    return entry


def write_custody(agency_id, recording_id, event_type, actor, hash_at_event=None):
    entry = new_log_entry({
        "agency_id": agency_id,
        "recording_id": recording_id,
        "event_type": event_type,
        "actor_role": actor["role"],
        "actor_id": actor["user_id"],
        "hash_at_event": hash_at_event,
    })
    db.collection("custody_events")[entry["id"]] = entry
    return entry


SYSTEM_ACTOR = {"role": "SYSTEM", "user_id": "SYSTEM"}


def find_by_id(collection, rid):
    return db.collection(collection).get(rid)


def get_agency_or_404(agency_id):
    agency = db.collection("agencies").get(agency_id)
    if agency is None:
        from errors import err_not_found
        raise err_not_found("Agency not found")
    return agency


def get_scoped(collection, agency, rid, label):
    res = db.collection(collection).get(rid)
    if res is None or res.get("agency_id") != agency["id"]:
        from errors import err_not_found
        raise err_not_found("%s not found" % label)
    return res


def active_policy(agency_id):
    for p in db.collection("policies").values():
        if p["agency_id"] == agency_id and p["status"] == "ACTIVE":
            return p
    return None


def active_plan(agency_id):
    for p in db.collection("plans").values():
        if p["agency_id"] == agency_id and p["status"] == "ACTIVE":
            return p
    return None


def add_days(iso_ts, days):
    dt = parse_dt(iso_ts)
    from datetime import timedelta
    return format_dt_plain(dt + timedelta(days=days))

"""Record construction, common fields, sorting and pagination."""
from . import config as C
from .errors import bad_request

HIDDEN_PREFIX = "_"

COMMON_DEFAULTS = {
    "created_at": None,
    "updated_at": None,
    "version": 1,
}


def new_record(kind, common=True, **fields):
    """Mint a record. `common` false means id + created_at only."""
    rec = {"id": C.new_id(), "created_at": C.iso(C.stamp())}
    if common:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    rec["_kind"] = kind
    rec.update(fields)
    return rec


def touch(rec):
    """Refresh updated_at and bump the change counter by exactly one."""
    rec["updated_at"] = C.iso(C.stamp())
    if "version" in rec:
        rec["version"] = int(rec.get("version") or 0) + 1
    return rec


def public(rec):
    """The wire form of a record: internal bookkeeping is stripped."""
    if rec is None:
        return None
    out = {}
    for key, value in rec.items():
        if key.startswith(HIDDEN_PREFIX):
            continue
        out[key] = value
    return out


def public_many(recs):
    return [public(r) for r in recs]


def sort_default(recs):
    """created_at ascending; ties stay in insertion order and never use id."""
    return sorted(recs, key=lambda r: (r.get("created_at") or "", _seq(r)))


_seq_counter = [0]


def _seq(rec):
    if "_seq" not in rec:
        _seq_counter[0] += 1
        rec["_seq"] = _seq_counter[0]
    return rec["_seq"]


def as_int(value, field="value", low=None, high=None, required=True):
    if value is None:
        if required:
            raise bad_request("%s is required" % field)
        return None
    if isinstance(value, bool):
        raise bad_request("%s must be an integer" % field)
    if isinstance(value, int):
        number = value
    elif isinstance(value, str):
        text = value.strip()
        try:
            number = int(text)
        except ValueError:
            raise bad_request("%s must be an integer" % field)
    elif isinstance(value, float):
        if value != int(value):
            raise bad_request("%s must be an integer" % field)
        number = int(value)
    else:
        raise bad_request("%s must be an integer" % field)
    if low is not None and number < low:
        raise bad_request("%s must be at least %s" % (field, low))
    if high is not None and number > high:
        raise bad_request("%s must be at most %s" % (field, high))
    return number


def as_bool(value, field="value", required=True):
    if value is None:
        if required:
            raise bad_request("%s is required" % field)
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        low = value.strip().lower()
        if low in ("true", "1", "yes"):
            return True
        if low in ("false", "0", "no"):
            return False
    raise bad_request("%s must be a boolean" % field)


def as_text(value, field="value", required=True, pattern=None):
    import re
    if value is None:
        if required:
            raise bad_request("%s is required" % field)
        return None
    if not isinstance(value, str):
        raise bad_request("%s must be a string" % field)
    text = value.strip()
    if required and text == "":
        raise bad_request("%s must not be empty" % field)
    if pattern is not None and not re.match(pattern, text):
        raise bad_request("%s has an invalid format" % field)
    return text


def as_enum(value, allowed, field="value", required=True):
    if value is None:
        if required:
            raise bad_request("%s is required" % field)
        return None
    if not isinstance(value, str):
        raise bad_request("%s must be one of %s" % (field, ", ".join(allowed)))
    text = value.strip()
    if text not in allowed:
        raise bad_request(
            "%s must be one of %s" % (field, ", ".join(allowed))
        )
    return text


def as_cents(value, field="value", required=True, low=0, high=None, strictly_positive=False):
    number = as_int(value, field, required=required)
    if number is None:
        return None
    if strictly_positive:
        if number <= 0:
            raise bad_request("%s must be greater than zero" % field)
        return number
    if low is not None and number < low:
        raise bad_request("%s must be at least %s" % (field, low))
    if high is not None and number > high:
        raise bad_request("%s must be at most %s" % (field, high))
    return number


def as_instant(value, field="value", required=True):
    if value is None:
        if required:
            raise bad_request("%s is required" % field)
        return None
    if not isinstance(value, str):
        raise bad_request("%s must be an ISO 8601 instant" % field)
    dt = C.parse_dt(value)
    if dt is None:
        raise bad_request("%s must be a valid ISO 8601 instant" % field)
    return C.iso(dt)


def as_instant_dt(value, field="value", required=True):
    text = as_instant(value, field, required)
    return C.parse_dt(text)


def get_body(body):
    return body if isinstance(body, dict) else {}


def paginate(recs, args, sorter=None):
    """Apply limit/offset from the query string and build the meta block."""
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    limit = as_int(limit_raw, "limit", low=1, high=100, required=False)
    if limit is None:
        limit = 10
    offset = as_int(offset_raw, "offset", low=0, required=False)
    if offset is None:
        offset = 0
    ordered = sorter(recs) if sorter else sort_default(recs)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return page, meta


def scalar_arg(args, name, cast=None):
    """Read an optional scalar query filter."""
    raw = args.get(name)
    if raw is None or raw == "":
        return None
    if cast == "int":
        return as_int(raw, name, required=False)
    if cast == "bool":
        low = str(raw).strip().lower()
        if low in ("true", "1", "yes"):
            return True
        if low in ("false", "0", "no"):
            return False
        raise bad_request("the %s filter must be a boolean" % name)
    return raw
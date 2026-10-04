"""Field validators, enum sets, the barrier rank order, and shared request
helpers. Field/shape failures map to ERR_INVALID_REQUEST (400); enum
membership failures map to ERR_INVALID_ENUM (400)."""
from flask import request

from responses import ApiError, success_list
from store import db, parse_dt, sort_key

# PRD 2.6 barrier health-status rank order.
BARRIER_RANK = {"CONVENTIONAL": 1, "MPF": 2, "VF": 3, "GERM_FREE": 4}
BARRIER_LEVELS = list(BARRIER_RANK.keys())
RANK_DOWN = {
    "GERM_FREE": "VF",
    "VF": "MPF",
    "MPF": "CONVENTIONAL",
    "CONVENTIONAL": "CONVENTIONAL",
}

SPECIES = ["MOUSE", "RAT"]
IMMUNE_CLASSES = ["IMMUNOCOMPETENT", "IMMUNOCOMPROMISED"]
BREEDING_TYPES = ["INBRED", "OUTBRED", "HYBRID"]
PANEL_TYPES = ["QUARTERLY_SENTINEL", "OUTBREAK_DIAGNOSTIC", "PRE_SHIPMENT"]
INSPECTION_TYPES = ["ROUTINE", "FOR_CAUSE", "PRE_PLACEMENT"]
CONTRACT_TYPES = ["CUSTOM_GENERATION", "CRYOPRESERVATION"]
IP_OWNERSHIP = ["CUSTOMER_EXCLUSIVE", "SHARED", "VENDOR_RETAINED"]
SEVERITIES = ["MINOR", "SIGNIFICANT"]
VERIFY_OUTCOMES = ["VERIFIED_OK", "VERIFIED_FAILED"]
SNP_RESULTS = ["CLEAR", "DRIFT_DETECTED"]

LIVE_COHORT_STATUSES = ["WEANED", "HOLD", "PARTIALLY_ALLOCATED", "FULLY_ALLOCATED"]


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def invalid(msg):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def body():
    """Request JSON body as a dict; anything else is treated as empty."""
    b = request.get_json(silent=True)
    return b if isinstance(b, dict) else {}


def get_or_404(coll, entity_id):
    ent = db[coll].get(entity_id)
    if ent is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Resource %s not found" % entity_id)
    return ent


def req(b, name):
    if name not in b or b[name] is None:
        raise invalid("Missing required field: %s" % name)
    return b[name]


def v_str(b, name):
    v = req(b, name)
    if not isinstance(v, str) or v == "":
        raise invalid("Field %s must be a non-empty string" % name)
    return v


def v_int(b, name, minv=None):
    v = req(b, name)
    if not is_int(v):
        raise invalid("Field %s must be an integer" % name)
    if minv is not None and v < minv:
        raise invalid("Field %s must be >= %d" % (name, minv))
    return v


def opt_int(b, name, default, minv=None):
    if name not in b or b[name] is None:
        return default
    return v_int(b, name, minv=minv)


def v_num(b, name, minv=None, exclusive_min=False):
    v = req(b, name)
    if not is_num(v):
        raise invalid("Field %s must be a number" % name)
    if minv is not None:
        if exclusive_min and not v > minv:
            raise invalid("Field %s must be > %s" % (name, minv))
        if not exclusive_min and v < minv:
            raise invalid("Field %s must be >= %s" % (name, minv))
    return v


def opt_bool(b, name, default):
    if name not in b or b[name] is None:
        return default
    if not isinstance(b[name], bool):
        raise invalid("Field %s must be a boolean" % name)
    return b[name]


def v_dt(b, name):
    v = req(b, name)
    try:
        return parse_dt(v)
    except (ValueError, TypeError):
        raise invalid("Field %s must be an ISO-8601 timestamp" % name)


def v_enum(b, name, allowed):
    v = req(b, name)
    if not isinstance(v, str):
        raise invalid("Field %s must be a string" % name)
    if v not in allowed:
        raise ApiError(
            "ERR_INVALID_ENUM",
            400,
            "Field %s must be one of %s" % (name, ", ".join(allowed)),
        )
    return v


def opt_enum(b, name, allowed, default):
    if name not in b or b[name] is None:
        return default
    return v_enum(b, name, allowed)


def paginate(items, serializer):
    """Sort by created_at ascending (creation-sequence tie-break) and apply
    limit/offset with the envelope pagination fields of PRD 2.3."""
    args = request.args
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            raise invalid("limit must be an integer")
        if isinstance(limit, bool) or limit < 1 or limit > 100:
            raise invalid("limit must lie between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            raise invalid("offset must be an integer")
        if offset < 0:
            raise invalid("offset must be >= 0")
    ordered = sorted(items, key=sort_key)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return success_list([serializer(e) for e in page], total, limit, offset)

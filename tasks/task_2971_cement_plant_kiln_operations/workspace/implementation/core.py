"""Foundation: errors, envelope, logical clock, in-memory store, shape helpers.

Every structural name here is taken from PRD.md:
  * headers            X-User-ID / X-User-Role                      (PRD 2.1)
  * envelope           meta / response_type / data                  (PRD 2.2)
  * error body         error_id / message                           (PRD 2.2)
  * pagination         limit / offset / total_count / has_more      (PRD 2.3)
  * concurrency        version                                      (PRD 2.4 / 2.6)
"""

import random
import re
import string
import threading
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import g, jsonify, request

API_PREFIX = "/cement-ops"

# --- PRD 2.1: the eight roles, spelled exactly ------------------------------
INTERNAL_ROLES = [
    "PlantAdmin",
    "ProcessEngineer",
    "KilnOperator",
    "LabTechnician",
    "QualityManager",
    "EnvironmentalOfficer",
    "LogisticsPlanner",
]
ALL_ROLES = INTERNAL_ROLES + ["Customer"]
READ_ROLES = list(INTERNAL_ROLES)
READ_ROLES_PLUS_CUSTOMER = list(INTERNAL_ROLES) + ["Customer"]

# --- PRD 5: complete error catalogue (74 identifiers) -----------------------
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_CUSTOMER_SCOPE_VIOLATION": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_PAGINATION": 400,
    "ERR_PLANT_NOT_FOUND": 404,
    "ERR_RAW_MATERIAL_NOT_FOUND": 404,
    "ERR_FUEL_NOT_FOUND": 404,
    "ERR_CUSTOMER_NOT_FOUND": 404,
    "ERR_DESIGN_NOT_FOUND": 404,
    "ERR_PILE_NOT_FOUND": 404,
    "ERR_BURN_TEST_NOT_FOUND": 404,
    "ERR_KILN_NOT_FOUND": 404,
    "ERR_KILN_RUN_NOT_FOUND": 404,
    "ERR_OUTAGE_NOT_FOUND": 404,
    "ERR_SILO_NOT_FOUND": 404,
    "ERR_BATCH_NOT_FOUND": 404,
    "ERR_LAB_TEST_NOT_FOUND": 404,
    "ERR_CERTIFICATE_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_STALE_DESIGN_VERSION": 412,
    "ERR_STALE_SILO_VERSION": 412,
    "ERR_STALE_CERTIFICATE_VERSION": 412,
    "ERR_INVALID_DESIGN_STATE": 409,
    "ERR_INVALID_PILE_STATE": 409,
    "ERR_INVALID_BURN_TEST_STATE": 409,
    "ERR_INVALID_RUN_STATE": 409,
    "ERR_INVALID_OUTAGE_STATE": 409,
    "ERR_INVALID_BATCH_STATE": 409,
    "ERR_INVALID_CERTIFICATE_STATE": 409,
    "ERR_INVALID_ORDER_STATE": 409,
    "ERR_SILO_BLOCKED": 409,
    "ERR_DESIGN_NOT_APPROVED": 409,
    "ERR_PILE_EMPTY": 409,
    "ERR_KILN_UNAVAILABLE": 409,
    "ERR_BATCH_FEED_SHORT": 409,
    "ERR_REVISION_LIMIT_EXCEEDED": 409,
    "ERR_KILN_WINDOW_CONFLICT": 409,
    "ERR_OUTAGE_WINDOW_CONFLICT": 409,
    "ERR_LAB_SUBJECT_STATE_INVALID": 409,
    "ERR_BATCH_NOT_QUALIFIED": 409,
    "ERR_CHLORINE_INPUT_EXCEEDED": 422,
    "ERR_TSR_CAP_EXCEEDED": 422,
    "ERR_BURN_TEST_NOT_AUTHORIZED": 422,
    "ERR_BURN_TEST_EXPIRED": 422,
    "ERR_NOX_BUDGET_EXCEEDED": 422,
    "ERR_FREE_LIME_OUT_OF_SPEC": 422,
    "ERR_PERMIT_NOX_INTENSITY_EXCEEDED": 422,
    "ERR_INVALID_WINDOW": 422,
    "ERR_RUN_WINDOW_NOT_ACTIVE": 422,
    "ERR_RUN_WINDOW_NOT_ELAPSED": 422,
    "ERR_LOADOUT_WINDOW_NOT_ACTIVE": 422,
    "ERR_SILO_KIND_MISMATCH": 422,
    "ERR_TEST_SUBJECT_INVALID": 422,
    "ERR_COMPONENTS_SUM_INVALID": 422,
    "ERR_MODULE_TARGET_DEVIATION": 422,
    "ERR_ALT_RAW_SUBSTITUTION_EXCEEDED": 422,
    "ERR_PILE_LSF_OFF_TARGET": 422,
    "ERR_LIMESTONE_LIMIT_EXCEEDED": 422,
    "ERR_SO3_LIMIT_EXCEEDED": 422,
    "ERR_CUSTOMER_SPEC_NOT_MET": 422,
    "ERR_PEAK_SEASON_OUTAGE": 422,
    "ERR_NO_ELIGIBLE_CUSTOMERS": 422,
    "ERR_INSUFFICIENT_KILN_FEED": 422,
    "ERR_SILO_CAPACITY_EXCEEDED": 422,
    "ERR_INSUFFICIENT_CLINKER": 422,
    "ERR_INSUFFICIENT_CEMENT": 422,
    "ERR_CERTIFICATE_NOT_ISSUED": 422,
    "ERR_CERTIFICATE_CUSTOMER_MISMATCH": 422,
    "ERR_CERTIFICATE_ALLOCATION_EXCEEDED": 422,
    "ERR_CERTIFIED_TONNES_EXCEED_BATCH": 422,
    "ERR_SILO_SPOUT_CAPACITY": 422,
    "ERR_DRAW_RATE_EXCEEDED": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or _default_message(error_id)


def _default_message(error_id):
    words = error_id[4:].replace("_", " ").lower() if error_id.startswith("ERR_") else error_id
    return "Request rejected: %s." % words


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# --- PRD 2.5: rounding is ROUND_HALF_UP everywhere --------------------------
def D(value):
    """Decimal from an arbitrary JSON number without binary-float drift."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rnd(value, places):
    return D(value).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def r2(value):
    return float(rnd(value, 2))


def r3(value):
    return float(rnd(value, 3))


def r4(value):
    return float(rnd(value, 4))


ZERO = Decimal("0")


# --- PRD 2.4: the logical clock --------------------------------------------
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class _Clock:
    def __init__(self):
        self.current = CLOCK_EPOCH

    def set(self, instant):
        self.current = instant

    def reset(self):
        self.current = CLOCK_EPOCH


CLOCK = _Clock()


def now():
    """The logical clock: the ONLY source of 'now' for windows and stamps."""
    return CLOCK.current


def fmt_ts(instant):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.4)."""
    if instant is None:
        return None
    instant = instant.astimezone(timezone.utc)
    return "%s.%03dZ" % (instant.strftime("%Y-%m-%dT%H:%M:%S"), instant.microsecond // 1000)


def now_iso():
    return fmt_ts(now())


_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"(?:[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.(\d{1,9}))?"
    r"(Z|z|[+-]\d{2}:?\d{2})?)?$"
)


def parse_iso(value):
    """Parse an ISO 8601 UTC instant. Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hh, mm, ss, frac, off = m.groups()
    try:
        micro = 0
        if frac:
            micro = int((frac + "000000")[:6])
        base = datetime(
            int(year), int(month), int(day),
            int(hh or 0), int(mm or 0), int(ss or 0), micro, tzinfo=timezone.utc,
        )
    except ValueError:
        return None
    if off and off not in ("Z", "z"):
        sign = 1 if off[0] == "+" else -1
        off = off[1:].replace(":", "")
        delta = timedelta(hours=int(off[:2]), minutes=int(off[2:4]))
        base = base - sign * delta
    return base


# --- request-scoped wall clock for created_at ------------------------------
_LAST_SYS_TS = [None]


def sys_now():
    """Strictly monotonic wall-clock instant, millisecond resolution.

    PRD 2.4 lists the logical clock as the source of every *computed* stamp
    (sealed_at, lit_at, ...). created_at/updated_at are row bookkeeping, and
    list ordering (PRD 2.3) plus every cascade walk depends on created_at
    ascending being insertion order, so they are minted from the wall clock
    and forced strictly increasing.
    """
    t = datetime.now(timezone.utc)
    t = t.replace(microsecond=(t.microsecond // 1000) * 1000)
    if _LAST_SYS_TS[0] is not None and t <= _LAST_SYS_TS[0]:
        t = _LAST_SYS_TS[0] + timedelta(milliseconds=1)
    _LAST_SYS_TS[0] = t
    return t


# --- in-memory store (empty on every boot; nothing is ever seeded) ---------
COLLECTIONS = [
    "plants",
    "raw_materials",
    "fuels",
    "customers",
    "designs",
    "piles",
    "burn_tests",
    "kilns",
    "kiln_runs",
    "outages",
    "silos",
    "batches",
    "lab_tests",
    "certificates",
    "orders",
]


class Store:
    def __init__(self):
        for name in COLLECTIONS:
            setattr(self, name, {})

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})


DB = Store()
LOCK = threading.RLock()

NOT_FOUND = {
    "plants": "ERR_PLANT_NOT_FOUND",
    "raw_materials": "ERR_RAW_MATERIAL_NOT_FOUND",
    "fuels": "ERR_FUEL_NOT_FOUND",
    "customers": "ERR_CUSTOMER_NOT_FOUND",
    "designs": "ERR_DESIGN_NOT_FOUND",
    "piles": "ERR_PILE_NOT_FOUND",
    "burn_tests": "ERR_BURN_TEST_NOT_FOUND",
    "kilns": "ERR_KILN_NOT_FOUND",
    "kiln_runs": "ERR_KILN_RUN_NOT_FOUND",
    "outages": "ERR_OUTAGE_NOT_FOUND",
    "silos": "ERR_SILO_NOT_FOUND",
    "batches": "ERR_BATCH_NOT_FOUND",
    "lab_tests": "ERR_LAB_TEST_NOT_FOUND",
    "certificates": "ERR_CERTIFICATE_NOT_FOUND",
    "orders": "ERR_ORDER_NOT_FOUND",
}


def new_row(collection, common_fields=True):
    """Mint a row with a bare UUID id (PRD 2.4) and its bookkeeping fields."""
    stamp = sys_now()
    row = {"id": str(uuid.uuid4()), "created_at": stamp}
    if common_fields:
        row["updated_at"] = stamp
        row["version"] = 1
    row["__coll"] = collection
    return row


def touch(row):
    """PRD 2.4/2.12: every mutation bumps version and refreshes updated_at."""
    if "version" in row:
        row["version"] = row["version"] + 1
        row["updated_at"] = sys_now()
    return row


def get_row(collection, row_id):
    return getattr(DB, collection).get(row_id)


def put_row(collection, row):
    getattr(DB, collection)[row["id"]] = row
    return row


def path_row(collection, row_id):
    """Ladder priority 30: path identifier resolves, else the entity's 404."""
    row = get_row(collection, row_id)
    if row is None:
        fail(NOT_FOUND[collection])
    return row


def rows(collection):
    return list(getattr(DB, collection).values())


def sort_key(row):
    """PRD 2.3: created_at ascending, id ascending as the only tie-break."""
    return (row["created_at"], row["id"])


def ordered(collection_rows):
    return sorted(collection_rows, key=sort_key)


# --- envelope --------------------------------------------------------------
_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_ts(datetime.now(timezone.utc)),
    }
    if extra:
        meta.update(extra)
    return meta


def respond_object(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def respond_list(items, limit, offset, total_count):
    meta = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    })
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def respond_error(error_id, message, status=None):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    if status is None:
        status = ERROR_STATUS.get(error_id, 400)
    return jsonify(body), status


# --- ladder rungs 10 and 20 ------------------------------------------------
def authenticate(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id == "" or role is None or role == "":
        fail("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        fail("ERR_UNAUTHORIZED")
    g.user_id = user_id
    g.role = role
    return user_id, role


def actor():
    return g.user_id


def actor_role():
    return g.role


# --- ladder rung 42 -------------------------------------------------------
_INT_RE = re.compile(r"^[+-]?\d+$")


def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        if raw is None or not _INT_RE.match(raw.strip()):
            fail("ERR_INVALID_PAGINATION")
        limit = int(raw.strip())
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_PAGINATION")
    if "offset" in args:
        raw = args.get("offset")
        if raw is None or not _INT_RE.match(raw.strip()):
            fail("ERR_INVALID_PAGINATION")
        offset = int(raw.strip())
        if offset < 0:
            fail("ERR_INVALID_PAGINATION")
    return limit, offset


def paginate(all_rows, limit, offset, serializer):
    total = len(all_rows)
    page = all_rows[offset:offset + limit]
    return respond_list([serializer(r) for r in page], limit, offset, total)


# --- request body + ladder rung 40 helpers --------------------------------
def body():
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        fail("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if not isinstance(payload, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return payload


def _bad(field, why):
    fail("ERR_INVALID_REQUEST", "Field '%s' %s." % (field, why))


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def need(payload, field):
    if field not in payload or payload[field] is None:
        _bad(field, "is required")
    return payload[field]


def want_str(payload, field, required=True):
    if field not in payload or payload[field] is None:
        if required:
            _bad(field, "is required")
        return None
    value = payload[field]
    if not isinstance(value, str) or value == "":
        _bad(field, "must be a non-empty string")
    return value


def want_num(payload, field, required=True, non_negative=True):
    if field not in payload or payload[field] is None:
        if required:
            _bad(field, "is required")
        return None
    value = payload[field]
    if not is_number(value):
        _bad(field, "must be a number")
    if non_negative and D(value) < ZERO:
        _bad(field, "must not be negative")
    return value


def want_int(payload, field, required=True, non_negative=True):
    if field not in payload or payload[field] is None:
        if required:
            _bad(field, "is required")
        return None
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(field, "must be an integer")
    if non_negative and value < 0:
        _bad(field, "must not be negative")
    return value


def want_bool(payload, field, required=True, default=None):
    if field not in payload or payload[field] is None:
        if required:
            _bad(field, "is required")
        return default
    value = payload[field]
    if not isinstance(value, bool):
        _bad(field, "must be a boolean")
    return value


def want_enum(payload, field, values, required=True):
    if field not in payload or payload[field] is None:
        if required:
            _bad(field, "is required")
        return None
    value = payload[field]
    if not isinstance(value, str) or value not in values:
        _bad(field, "must be one of %s" % ", ".join(values))
    return value


def want_dt(payload, field, required=True):
    if field not in payload or payload[field] is None:
        if required:
            _bad(field, "is required")
        return None
    parsed = parse_iso(payload[field])
    if parsed is None:
        _bad(field, "must be an ISO 8601 UTC datetime")
    return parsed


def want_array(payload, field, required=True):
    if field not in payload or payload[field] is None:
        if required:
            _bad(field, "is required")
        return None
    value = payload[field]
    if not isinstance(value, list):
        _bad(field, "must be an array")
    return value


def fk_ref(payload, field, collection, required=True):
    """Ladder rung 35: a foreign key in the body must resolve, else its 404.

    Absent / non-string values fall through to rung 40 (request shape).
    """
    if field not in payload or payload[field] is None:
        return None
    value = payload[field]
    if not isinstance(value, str):
        return None
    row = get_row(collection, value)
    if row is None:
        fail(NOT_FOUND[collection])
    return row


def hours_between(start, end):
    """PRD 3.4 / 3.9: window length in hours, rounded half up to 2 decimals."""
    seconds = D((end - start).total_seconds())
    return r2(seconds / D(3600))


# --- endpoint plumbing -----------------------------------------------------
import functools  # noqa: E402


def guard(allowed_roles):
    """Wrap a handler: serialise it under the store lock, then run rungs 10/20.

    PRD 2.8 puts authentication and role permission ahead of everything else,
    and a single lock keeps the optimistic-concurrency rules of PRD 2.6 and the
    multi-hop cascades of PRD 2.12 atomic under the harness's concurrency.
    """
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            with LOCK:
                authenticate(allowed_roles)
                return fn(*args, **kwargs)
        return wrapper
    return decorator


def _norm(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def field_eq(name):
    return lambda row, raw: _norm(row.get(name)) == raw


def computed_eq(fn):
    return lambda row, raw: _norm(fn(row)) == raw


def filtered_list(collection, serializer, filters=None, prefilter=None):
    """Rung 42 then the endpoint's declared filters, then PRD 2.3 ordering.

    `prefilter` narrows the collection before the caller's query filters run;
    it carries the Customer visibility scope of rung 45.
    """
    limit, offset = pagination()
    all_rows = ordered(rows(collection))
    if prefilter is not None:
        all_rows = [r for r in all_rows if prefilter(r)]
    for arg, predicate in (filters or {}).items():
        raw = request.args.get(arg)
        if raw is not None:
            all_rows = [r for r in all_rows if predicate(r, raw)]
    return paginate(all_rows, limit, offset, serializer)


def query_int(name, required=True):
    raw = request.args.get(name)
    if raw is None or raw == "":
        if required:
            _bad(name, "is required")
        return None
    if not _INT_RE.match(raw.strip()):
        _bad(name, "must be an integer")
    return int(raw.strip())

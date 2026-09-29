"""Foundation: logical clock, in-memory store, response envelope, errors,
auth, body-shape validation and pagination.

Every structural name here is taken from PRD.md sections 2.1 - 2.9.
"""
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import g, request

UTC = timezone.utc

# PRD 2.1 - six roles, spelled exactly
ROLES = (
    "CenterAdmin",
    "AccessCoordinator",
    "FacilityCoordinator",
    "Interventionalist",
    "SedationRN",
    "Coder",
)

# PRD 2.4 - at startup the logical clock reads exactly 2026-08-01T00:00:00Z
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)

# ---------------------------------------------------------------------------
# Error catalogue (PRD section 5)
# ---------------------------------------------------------------------------
ERRORS = {
    "ERR_UNAUTHENTICATED": (401, "authentication headers missing or role not recognized"),
    "ERR_UNAUTHORIZED": (403, "role not permitted for this operation"),
    "ERR_FACILITY_NOT_FOUND": (404, "dialysis facility not found"),
    "ERR_PATIENT_NOT_FOUND": (404, "patient not found"),
    "ERR_ACCESS_NOT_FOUND": (404, "vascular access not found"),
    "ERR_READING_NOT_FOUND": (404, "surveillance reading not found"),
    "ERR_REFERRAL_NOT_FOUND": (404, "referral not found"),
    "ERR_ROOM_NOT_FOUND": (404, "procedure room not found"),
    "ERR_CLINICIAN_NOT_FOUND": (404, "clinician not found"),
    "ERR_PROCEDURE_NOT_FOUND": (404, "procedure not found"),
    "ERR_DEVICE_LOT_NOT_FOUND": (404, "device lot not found"),
    "ERR_DEVICE_USAGE_NOT_FOUND": (404, "device usage not found"),
    "ERR_PLAN_NOT_FOUND": (404, "access conversion plan not found"),
    "ERR_INFECTION_EVENT_NOT_FOUND": (404, "infection event not found"),
    "ERR_INVALID_REQUEST": (422, "request body failed shape validation"),
    "ERR_FACILITY_SCOPE_VIOLATION": (403, "facility coordinator may only act on its own facility"),
    "ERR_CLINICIAN_ROLE_MISMATCH": (422, "clinician does not hold the required staffing role"),
    "ERR_NOT_ASSIGNED_CLINICIAN": (403, "acting clinician is not the one assigned to this case"),
    "ERR_REFERRAL_NOT_TRIAGED": (409, "referral must be TRIAGED before a procedure can be booked"),
    "ERR_REFERRAL_STATE_INVALID": (409, "referral is not in a state that allows this transition"),
    "ERR_PROCEDURE_NOT_SCHEDULED": (409, "procedure is not in SCHEDULED"),
    "ERR_PROCEDURE_NOT_IN_ROOM": (409, "procedure is not in IN_ROOM"),
    "ERR_PROCEDURE_NOT_IN_RECOVERY": (409, "procedure is not in RECOVERY"),
    "ERR_PROCEDURE_TERMINAL": (409, "procedure has reached a terminal clinical state"),
    "ERR_CODING_STATE_INVALID": (409, "coding state does not allow this revenue-cycle transition"),
    "ERR_PLAN_STATE_INVALID": (409, "conversion plan is not in a state that allows this transition"),
    "ERR_DEVICE_LOT_STATE_INVALID": (409, "device lot is not in a state that allows this transition"),
    "ERR_ACCESS_TRANSITION_NOT_ALLOWED": (409, "vascular access cannot make the requested status transition"),
    "ERR_STALE_REFERRAL_VERSION": (412, "referral has been modified since it was read"),
    "ERR_STALE_DEVICE_LOT_VERSION": (412, "device lot has been modified since it was read"),
    "ERR_STALE_ACCESS_VERSION": (412, "vascular access has been modified since it was read"),
    "ERR_SEDATION_CREDENTIAL_INVALID": (422, "sedation registered nurse is not validly credentialed for moderate sedation"),
    "ERR_DEVICE_LOT_QUARANTINED": (422, "device lot is quarantined and cannot be reserved"),
    "ERR_DEVICE_LOT_EXPIRED": (422, "device lot has lapsed"),
    "ERR_RECOVERY_CRITERIA_NOT_MET": (422, "recovery criteria for discharge are not satisfied"),
    "ERR_ACCESS_ABANDONED": (409, "vascular access has been abandoned"),
    "ERR_SEGREGATION_OF_DUTIES": (403, "the clinician who performed the case may not code it"),
    "ERR_ATTESTATION_NOT_OPERATOR": (403, "only the primary operator may attest medical necessity"),
    "ERR_MEDICAL_NECESSITY_UNSUPPORTED": (422, "cited surveillance reading does not support medical necessity"),
    "ERR_SCHEDULE_IN_PAST": (422, "scheduled start is before the current clock"),
    "ERR_SAME_DAY_WINDOW_MISSED": (422, "booking falls outside the urgency window earned at triage"),
    "ERR_ROOM_OCCUPIED": (409, "procedure room is occupied for the requested interval"),
    "ERR_SEDATION_CAPACITY_EXCEEDED": (409, "sedation registered nurse has no remaining concurrent capacity"),
    "ERR_RECOVERY_BAY_UNAVAILABLE": (409, "no recovery bay is free for the projected recovery window"),
    "ERR_FACILITY_SUSPENDED": (409, "referring facility is suspended"),
    "ERR_INSUFFICIENT_SURVEILLANCE": (422, "no surveillance reading exists for this access"),
    "ERR_ROOM_DAILY_CAP_REACHED": (409, "procedure room has no remaining capacity for that calendar day"),
    "ERR_DUPLICATE_CODE_RANK": (409, "a code line with that rank already exists on the procedure"),
    "ERR_DUPLICATE_FACILITY_CODE": (409, "facility_code already in use"),
    "ERR_DUPLICATE_MRN": (409, "mrn already in use"),
    "ERR_DUPLICATE_NPI": (409, "npi already in use"),
    "ERR_DUPLICATE_ROOM_CODE": (409, "room_code already in use"),
    "ERR_DUPLICATE_LOT_NUMBER": (409, "lot_number already in use for that device_type"),
    "ERR_CONVERSION_NOT_INDICATED": (422, "conversion is not clinically indicated for this access"),
    "ERR_TARGET_ACCESS_NOT_CONVERTIBLE": (409, "target access cannot receive a conversion"),
    "ERR_ACCESS_HAS_OPEN_CASE": (409, "vascular access still has an open case"),
    "ERR_REBILL_LIMIT_REACHED": (409, "rebill limit reached for this procedure"),
    "ERR_LOT_DEPLETED": (409, "device lot has no units left"),
    "ERR_INSUFFICIENT_DEVICE_STOCK": (409, "requested quantity exceeds available stock"),
    "ERR_NO_ELIGIBLE_LOT": (422, "no eligible device lot exists for that device type"),
    "ERR_CODE_DEVICE_MISMATCH": (422, "a billed procedural code has no matching consumed device"),
    "ERR_SESSION_CAP_EXCEEDED": (409, "allowed amount exceeds the per-session cap"),
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        status, default_message = ERRORS[error_id]
        self.error_id = error_id
        self.http_status = status
        self.message = message or default_message


# ---------------------------------------------------------------------------
# In-memory store.  Starts completely empty on every boot: no seeding.
# ---------------------------------------------------------------------------
class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = CLOCK_EPOCH
        self._seq = 0
        self.facilities = {}
        self.patients = {}
        self.accesses = {}
        self.readings = {}
        self.referrals = {}
        self.rooms = {}
        self.clinicians = {}
        self.procedures = {}
        self.codes = {}
        self.observations = {}
        self.lots = {}
        self.usages = {}
        self.plans = {}
        self.infections = {}

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


# ---------------------------------------------------------------------------
# Timestamp / date helpers (PRD 2.5)
# ---------------------------------------------------------------------------
def iso3(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def now_dt():
    return db.clock


def now_str():
    return iso3(db.clock)


def clock_date():
    return db.clock.date()


def parse_dt(value):
    """Parse an ISO 8601 UTC datetime.  Returns an aware datetime or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def parse_date(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except (ValueError, AttributeError):
        return None


def round_half_up(value):
    """Round a Decimal half up to a whole integer."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def base_record(versioned=True):
    rec = {"id": new_id(), "created_at": now_str()}
    if versioned:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    rec["_seq"] = db.next_seq()
    return rec


def touch(rec):
    """Refresh a row and advance its version.

    PRD 2.5: ``version`` "increases by exactly one on every mutation of the row, including
    mutations the row undergoes as a cascade victim rather than as the direct target of a
    request", and PRD 2.10: "every row a cascade touches is mutated in its own right.  Its
    ``updated_at`` is refreshed and its ``version`` increases by one, exactly as if it had
    been the direct target of a request."  A row therefore advances by exactly one per
    request that mutates it, even when the request writes it more than once -- a quarantine
    that both flips the lot's ``status`` and restores its ``quantity_reserved`` is one
    mutation of that lot, not two.
    """
    rec["updated_at"] = now_str()
    seen = None
    try:
        seen = g._touched_rows
    except (AttributeError, RuntimeError):
        try:
            seen = set()
            g._touched_rows = seen
        except RuntimeError:
            seen = None
    if seen is not None:
        marker = id(rec)
        if marker in seen:
            return
        seen.add(marker)
    rec["version"] = rec.get("version", 0) + 1


def public(rec):
    if rec is None:
        return None
    ordered = {}
    for key, value in rec.items():
        if key.startswith("_"):
            continue
        ordered[key] = value
    return ordered


def sort_key_created(rec):
    return (rec["created_at"], rec["_seq"])


# ---------------------------------------------------------------------------
# Response envelope (PRD 2.2)
# ---------------------------------------------------------------------------
_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def meta_base():
    return {"api_request_id": request_id(), "api_request_timestamp": now_str()}


def envelope_object(data):
    return {"meta": meta_base(), "response_type": "object", "data": data}


def envelope_array(items, limit=None, offset=None, total_count=None, has_more=None):
    meta = meta_base()
    if limit is not None:
        meta["limit"] = limit
        meta["offset"] = offset
        meta["total_count"] = total_count
        meta["has_more"] = has_more
    return {"meta": meta, "response_type": "array", "data": items}


def envelope_error(error_id, message):
    return {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


# ---------------------------------------------------------------------------
# Auth (PRD 2.1, ladder rungs 1 and 2)
# ---------------------------------------------------------------------------
def authenticate(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    return user_id, role


def facility_scope(role, user_id, facility_id):
    """Ladder rung 6 - the FacilityCoordinator ownership rule."""
    if role == "FacilityCoordinator" and user_id != facility_id:
        raise ApiError("ERR_FACILITY_SCOPE_VIOLATION")


# ---------------------------------------------------------------------------
# Existence (ladder rungs 3 and 5)
# ---------------------------------------------------------------------------
def must_get(collection, row_id, error_id):
    if not isinstance(row_id, str):
        raise ApiError(error_id)
    row = collection.get(row_id)
    if row is None:
        raise ApiError(error_id)
    return row


# ---------------------------------------------------------------------------
# Body shape validation (ladder rung 4 -> ERR_INVALID_REQUEST)
# ---------------------------------------------------------------------------
def get_body():
    raw = request.get_data(cache=True)
    if not raw:
        return {}
    parsed = request.get_json(silent=True)
    if parsed is None:
        raise ApiError("ERR_INVALID_REQUEST")
    if not isinstance(parsed, dict):
        raise ApiError("ERR_INVALID_REQUEST")
    return parsed


def _bad():
    raise ApiError("ERR_INVALID_REQUEST")


def req_str(body, key, min_len=1, max_len=None):
    value = body.get(key)
    if not isinstance(value, str):
        _bad()
    if len(value) < min_len:
        _bad()
    if max_len is not None and len(value) > max_len:
        _bad()
    return value


def opt_str(body, key, default=None, min_len=1, max_len=None):
    if key not in body or body.get(key) is None:
        return default
    return req_str(body, key, min_len=min_len, max_len=max_len)


def req_enum(body, key, members):
    value = body.get(key)
    if not isinstance(value, str) or value not in members:
        _bad()
    return value


def opt_enum(body, key, members, default=None):
    if key not in body or body.get(key) is None:
        return default
    return req_enum(body, key, members)


def _as_int(value):
    if isinstance(value, bool) or not isinstance(value, int):
        _bad()
    return value


def req_int(body, key, minimum=None, maximum=None):
    if key not in body:
        _bad()
    value = _as_int(body.get(key))
    if minimum is not None and value < minimum:
        _bad()
    if maximum is not None and value > maximum:
        _bad()
    return value


def opt_int(body, key, default, minimum=None, maximum=None):
    if key not in body or body.get(key) is None:
        return default
    return req_int(body, key, minimum=minimum, maximum=maximum)


def req_num(body, key, minimum=None, maximum=None):
    value = body.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad()
    if minimum is not None and value < minimum:
        _bad()
    if maximum is not None and value > maximum:
        _bad()
    return value


def req_bool(body, key):
    value = body.get(key)
    if not isinstance(value, bool):
        _bad()
    return value


def opt_bool(body, key, default):
    if key not in body or body.get(key) is None:
        return default
    return req_bool(body, key)


def req_date(body, key):
    value = body.get(key)
    if parse_date(value) is None:
        _bad()
    return value.strip()


def req_dt(body, key):
    value = body.get(key)
    parsed = parse_dt(value)
    if parsed is None:
        _bad()
    return value.strip(), parsed


def req_id(body, key):
    value = body.get(key)
    if not isinstance(value, str) or not value:
        _bad()
    return value


def opt_id(body, key):
    if key not in body or body.get(key) is None:
        return None
    return req_id(body, key)


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------
def page_params():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except ValueError:
            limit = 10
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    raw_offset = request.args.get("offset")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except ValueError:
            offset = 0
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(rows):
    limit, offset = page_params()
    total = len(rows)
    window = rows[offset:offset + limit]
    has_more = (offset + limit) < total
    return window, limit, offset, total, has_more


def list_response(rows):
    window, limit, offset, total, has_more = paginate(rows)
    return envelope_array([public(r) for r in window], limit, offset, total, has_more), 200


def filter_equals(rows, field, raw):
    if raw is None or raw == "":
        return rows
    return [r for r in rows if r.get(field) == raw]


def filter_bool(rows, field, raw):
    if raw is None or raw == "":
        return rows
    lowered = raw.strip().lower()
    if lowered in ("true", "1"):
        wanted = True
    elif lowered in ("false", "0"):
        wanted = False
    else:
        return rows
    return [r for r in rows if r.get(field) is wanted]


def days_between_dates(later, earlier):
    return (later - earlier).days


def plus_days(dt, days):
    return dt + timedelta(days=days)

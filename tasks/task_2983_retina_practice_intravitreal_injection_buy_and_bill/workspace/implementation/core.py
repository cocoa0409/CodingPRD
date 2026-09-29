"""Core infrastructure: error catalogue, response envelope, in-memory store,
logical clock, validation primitives and the auth/RBAC decorator.

Everything here traces to PRD sections 2.1 - 2.12 and section 5.
"""
import random
import string
import threading
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import g, jsonify, request

# ---------------------------------------------------------------- roles (PRD 2.1)
ROLE_RETINA = "RetinaSpecialist"
ROLE_TECH = "PharmacyTech"
ROLE_BILLING = "BillingSpecialist"
ROLE_COMPLIANCE = "ComplianceOfficer"
ROLE_ADMIN = "PracticeAdmin"
ROLE_PATIENT = "Patient"

ROLES = (
    ROLE_RETINA,
    ROLE_TECH,
    ROLE_BILLING,
    ROLE_COMPLIANCE,
    ROLE_ADMIN,
    ROLE_PATIENT,
)

READ_ROLES = [ROLE_ADMIN, ROLE_RETINA, ROLE_TECH, ROLE_BILLING, ROLE_COMPLIANCE]

# ------------------------------------------------------- error catalogue (PRD 5)
ERROR_STATUS = {
    "ERR_MISSING_AUTH_HEADERS": 401,
    "ERR_UNKNOWN_ROLE": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_ACTING_IDENTITY_NOT_FOUND": 403,
    "ERR_NOT_NOTIFICATION_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_ADJUDICATOR_IS_INJECTOR": 403,
    "ERR_RECALL_CLOSER_CONFLICT": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_PAYER_NOT_FOUND": 404,
    "ERR_DRUG_NOT_FOUND": 404,
    "ERR_POLICY_NOT_FOUND": 404,
    "ERR_PATIENT_NOT_FOUND": 404,
    "ERR_CLINICIAN_NOT_FOUND": 404,
    "ERR_IMAGING_STUDY_NOT_FOUND": 404,
    "ERR_PLAN_NOT_FOUND": 404,
    "ERR_LOT_NOT_FOUND": 404,
    "ERR_VIAL_NOT_FOUND": 404,
    "ERR_AUTHORIZATION_NOT_FOUND": 404,
    "ERR_ENCOUNTER_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    "ERR_ENROLLMENT_NOT_FOUND": 404,
    "ERR_ADVERSE_EVENT_NOT_FOUND": 404,
    "ERR_RECALL_NOT_FOUND": 404,
    "ERR_NOTIFICATION_NOT_FOUND": 404,
    "ERR_STALE_PLAN_VERSION": 412,
    "ERR_PLAN_NOT_TREATABLE": 409,
    "ERR_PLAN_STATE_INVALID": 409,
    "ERR_AUTHORIZATION_STATE_INVALID": 409,
    "ERR_ENCOUNTER_STATE_INVALID": 409,
    "ERR_CLAIM_LINE_STATE_INVALID": 409,
    "ERR_LOT_STATE_INVALID": 409,
    "ERR_RECALL_STATE_INVALID": 409,
    "ERR_NOTIFICATION_STATE_INVALID": 409,
    "ERR_ENROLLMENT_STATE_INVALID": 409,
    "ERR_ADVERSE_EVENT_STATE_INVALID": 409,
    "ERR_VIAL_STATE_INVALID": 409,
    "ERR_CLINICIAN_NOT_ELIGIBLE": 409,
    "ERR_IMAGING_EYE_MISMATCH": 422,
    "ERR_IMAGING_STUDY_STALE": 422,
    "ERR_INJECTION_INTERVAL_VIOLATION": 409,
    "ERR_CLINICIAN_DAY_CAPACITY_EXCEEDED": 409,
    "ERR_OVERRIDE_REASON_REQUIRED": 422,
    "ERR_PAYER_POLICY_MISSING": 409,
    "ERR_DRUG_EXCLUDED_BY_PAYER": 422,
    "ERR_AUTHORIZATION_MISSING": 409,
    "ERR_AUTHORIZATION_EXPIRED": 409,
    "ERR_AUTHORIZATION_DRUG_MISMATCH": 409,
    "ERR_AUTHORIZATION_EXHAUSTED": 409,
    "ERR_NO_ELIGIBLE_VIAL": 409,
    "ERR_LOT_NOT_AVAILABLE": 409,
    "ERR_DOSE_EXCEEDS_VIAL_FILL": 422,
    "ERR_PREP_ATTESTATION_REQUIRED": 422,
    "ERR_ATTESTED_WASTAGE_MISMATCH": 422,
    "ERR_STEP_THERAPY_NOT_SATISFIED": 422,
    "ERR_APPROVED_INJECTIONS_EXCEED_POLICY": 422,
    "ERR_AUTHORIZATION_WINDOW_OVERLAP": 409,
    "ERR_APPEAL_WINDOW_CLOSED": 409,
    "ERR_DUPLICATE_LOT_NUMBER": 409,
    "ERR_DUPLICATE_ACTIVE_PLAN": 409,
    "ERR_DUPLICATE_CLAIM": 409,
    "ERR_COPAY_CARD_FEDERAL_INELIGIBLE": 422,
    "ERR_DUPLICATE_ACTIVE_ENROLLMENT": 409,
    "ERR_RECALL_ALREADY_OPEN": 409,
    "ERR_NO_QUARANTINED_VIALS": 409,
    "ERR_CREDIT_EXCEEDS_EXPECTED": 422,
    "ERR_PATIENT_NOTIFICATIONS_INCOMPLETE": 409,
    "ERR_OPEN_ADVERSE_EVENT": 409,
    "ERR_DUPLICATE_RESOURCE": 409,
    "ERR_INVALID_REFERENCE_DRUG": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS[error_id]
        self.message = message or error_id.replace("ERR_", "").replace("_", " ").lower()


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# ------------------------------------------------------------- time helpers
UTC = timezone.utc
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)


def iso3(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.2 / 2.4)."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(value):
    """Parse an ISO 8601 instant. Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def whole_days(a, b):
    """Whole days from instant a to instant b, truncated toward zero (PRD 2.5)."""
    return int((b - a).total_seconds() // 86400) if b >= a else -int((a - b).total_seconds() // 86400)


def add_days(dt, days):
    return dt + timedelta(days=int(days))


# ------------------------------------------------------------ decimal helpers
def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value, places=0):
    q = Decimal(1).scaleb(-places)
    return dec(value).quantize(q, rounding=ROUND_HALF_UP)


def cents(value):
    """Round half up to a whole cent and return an int (PRD 2.7)."""
    return int(round_half_up(value, 0))


def decimal_places(value):
    d = dec(value).normalize()
    exp = d.as_tuple().exponent
    return -exp if exp < 0 else 0


# ------------------------------------------------------------------- store
class Store:
    """In-memory only. Wiped by process restart; nothing is ever seeded."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.payers = {}
        self.drugs = {}
        self.policies = {}
        self.patients = {}
        self.clinicians = {}
        self.imaging_studies = {}
        self.plans = {}
        self.lots = {}
        self.vials = {}
        self.authorizations = {}
        self.encounters = {}
        self.claims = {}
        self.enrollments = {}
        self.adverse_events = {}
        self.recalls = {}
        self.notifications = {}
        self.clock = DEFAULT_CLOCK
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


DB = Store()
LOCK = threading.RLock()


def now_clock():
    return DB.clock


def base_row(versioned=True):
    row = {
        "id": str(uuid.uuid4()),
        "created_at": DB.clock,
        "_seq": DB.next_seq(),
    }
    if versioned:
        row["updated_at"] = DB.clock
        row["version"] = 1
    return row


def touch(row):
    """Refresh updated_at and advance version once per request (PRD 2.4)."""
    if "version" not in row:
        return
    seen = getattr(g, "touched", None)
    if seen is None:
        seen = set()
        g.touched = seen
    if row["id"] in seen:
        row["updated_at"] = DB.clock
        return
    seen.add(row["id"])
    row["updated_at"] = DB.clock
    row["version"] = int(row["version"]) + 1


def sort_key(row):
    return (row["created_at"], row["_seq"])


def ordered(rows):
    """Default list ordering: created_at ascending (PRD 2.3)."""
    return sorted(rows, key=sort_key)


# ------------------------------------------------------- response envelope
_ALNUM = string.ascii_uppercase + string.digits


def _meta():
    return {
        "api_request_id": "req_" + "".join(random.choice(_ALNUM) for _ in range(20)),
        "api_request_timestamp": iso3(datetime.now(UTC)),
    }


def publish(value):
    if isinstance(value, dict):
        return {k: publish(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, list):
        return [publish(v) for v in value]
    if isinstance(value, datetime):
        return iso3(value)
    if isinstance(value, Decimal):
        return float(value)
    return value


def ok(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": publish(data or {})}), status


def created(data):
    return ok(data, 201)


def ok_list(rows, limit, offset, total):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(rows)) < total
    return jsonify({"meta": meta, "response_type": "array", "data": [publish(r) for r in rows]}), 200


def error_response(exc):
    return (
        jsonify(
            {
                "meta": _meta(),
                "response_type": "error",
                "data": {"error_id": exc.error_id, "message": exc.message},
            }
        ),
        exc.http_status,
    )


# --------------------------------------------------------------- auth (PRD 2.1)
def api(roles):
    """Steps 1-4 of the PRD 2.8 precedence ladder, plus the global request lock."""

    def decorator(fn):
        def wrapper(*args, **kwargs):
            with LOCK:
                g.touched = set()
                try:
                    uid = request.headers.get("X-User-ID")
                    role = request.headers.get("X-User-Role")
                    if uid is None or role is None or not uid.strip() or not role.strip():
                        fail("ERR_MISSING_AUTH_HEADERS", "X-User-ID and X-User-Role are required")
                    if role not in ROLES:
                        fail("ERR_UNKNOWN_ROLE", "unknown role %r" % role)
                    if role not in roles:
                        fail("ERR_ROLE_NOT_PERMITTED", "role %s may not call this endpoint" % role)
                    if role == ROLE_RETINA and uid not in DB.clinicians:
                        fail("ERR_ACTING_IDENTITY_NOT_FOUND", "acting clinician does not exist")
                    if role == ROLE_PATIENT and uid not in DB.patients:
                        fail("ERR_ACTING_IDENTITY_NOT_FOUND", "acting patient does not exist")
                    g.user_id = uid
                    g.role = role
                    return fn(*args, **kwargs)
                except ApiError as exc:
                    return error_response(exc)

        wrapper.__name__ = fn.__name__
        wrapper.__doc__ = fn.__doc__
        return wrapper

    return decorator


# ------------------------------------------------ payload validation (step 5)
class Field:
    def __init__(
        self,
        name,
        kind,
        required=False,
        default=None,
        values=None,
        minlen=None,
        maxlen=None,
        minimum=None,
        maximum=None,
        gt=None,
        max_dp=None,
        digits=None,
        nullable=False,
    ):
        self.name = name
        self.kind = kind
        self.required = required
        self.default = default
        self.values = values
        self.minlen = minlen
        self.maxlen = maxlen
        self.minimum = minimum
        self.maximum = maximum
        self.gt = gt
        self.max_dp = max_dp
        self.digits = digits
        self.nullable = nullable


def _bad(name, why):
    fail("ERR_INVALID_REQUEST", "field %s %s" % (name, why))


def get_body():
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        fail("ERR_INVALID_REQUEST", "request body is not valid JSON")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        fail("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return parsed


def _coerce(field, raw):
    kind = field.kind
    if kind == "string":
        if not isinstance(raw, str):
            _bad(field.name, "must be a string")
        if field.minlen is not None and len(raw) < field.minlen:
            _bad(field.name, "is too short")
        if field.maxlen is not None and len(raw) > field.maxlen:
            _bad(field.name, "is too long")
        if field.digits is not None and (len(raw) != field.digits or not raw.isdigit()):
            _bad(field.name, "must be exactly %d digits" % field.digits)
        return raw
    if kind == "enum":
        if not isinstance(raw, str):
            _bad(field.name, "must be a string enum member")
        if raw not in field.values:
            _bad(field.name, "is not a recognised value")
        return raw
    if kind == "boolean":
        if not isinstance(raw, bool):
            _bad(field.name, "must be a boolean")
        return raw
    if kind == "integer":
        if isinstance(raw, bool):
            _bad(field.name, "must be an integer")
        if isinstance(raw, int):
            value = int(raw)
        elif isinstance(raw, float) and float(raw).is_integer():
            value = int(raw)
        else:
            _bad(field.name, "must be an integer")
        if field.minimum is not None and value < field.minimum:
            _bad(field.name, "is below its minimum")
        if field.maximum is not None and value > field.maximum:
            _bad(field.name, "is above its maximum")
        if field.gt is not None and value <= field.gt:
            _bad(field.name, "must be greater than %s" % field.gt)
        return value
    if kind == "number":
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            _bad(field.name, "must be a number")
        value = dec(raw)
        if field.max_dp is not None and decimal_places(value) > field.max_dp:
            _bad(field.name, "carries more than %d decimal places" % field.max_dp)
        if field.minimum is not None and value < dec(field.minimum):
            _bad(field.name, "is below its minimum")
        if field.maximum is not None and value > dec(field.maximum):
            _bad(field.name, "is above its maximum")
        if field.gt is not None and value <= dec(field.gt):
            _bad(field.name, "must be greater than %s" % field.gt)
        return value
    if kind == "datetime":
        parsed = parse_dt(raw)
        if parsed is None:
            _bad(field.name, "must be an ISO 8601 UTC instant")
        return parsed
    if kind == "id":
        if not isinstance(raw, str) or not raw.strip():
            _bad(field.name, "must be a non-empty identifier string")
        return raw
    raise AssertionError("unknown field kind " + kind)


def validate(body, fields):
    out = {}
    for field in fields:
        present = field.name in body
        raw = body.get(field.name)
        if not present or raw is None:
            if field.required and (not present or raw is None):
                if present and raw is None and field.nullable:
                    out[field.name] = None
                    continue
                _bad(field.name, "is required")
            out[field.name] = field.default
            continue
        out[field.name] = _coerce(field, raw)
    return out


# --------------------------------------------------- query params (PRD 2.3)
def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(str(raw).strip())
        except (TypeError, ValueError):
            _bad("limit", "must be an integer")
        if limit < 1 or limit > 100:
            _bad("limit", "must be between 1 and 100")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(str(raw).strip())
        except (TypeError, ValueError):
            _bad("offset", "must be an integer")
        if offset < 0:
            _bad("offset", "must be at least 0")
    return limit, offset


_TRUE = ("true", "1")
_FALSE = ("false", "0")


def query_filters(spec):
    """spec maps query-parameter name -> (row_field, kind, enum_values)."""
    out = {}
    for param, definition in spec.items():
        if param not in request.args:
            continue
        raw = request.args.get(param)
        field_name, kind = definition[0], definition[1]
        values = definition[2] if len(definition) > 2 else None
        if kind == "enum":
            if raw not in values:
                _bad(param, "is not a recognised value")
            out[field_name] = raw
        elif kind == "boolean":
            low = str(raw).strip().lower()
            if low in _TRUE:
                out[field_name] = True
            elif low in _FALSE:
                out[field_name] = False
            else:
                _bad(param, "must be a boolean")
        elif kind == "integer":
            try:
                out[field_name] = int(str(raw).strip())
            except (TypeError, ValueError):
                _bad(param, "must be an integer")
        elif kind == "datetime":
            parsed = parse_dt(raw)
            if parsed is None:
                _bad(param, "must be an ISO 8601 UTC instant")
            out[field_name] = parsed
        else:
            out[field_name] = raw
    return out


def apply_filters(rows, filters):
    result = []
    for row in rows:
        keep = True
        for key, wanted in filters.items():
            if row.get(key) != wanted:
                keep = False
                break
        if keep:
            result.append(row)
    return result


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset: offset + limit], total


def listing(rows, filters, limit, offset):
    rows = apply_filters(ordered(rows), filters)
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


# ------------------------------------------------- path lookups (step 6 / 7)
def _lookup(table, ident, error_id):
    row = table.get(ident)
    if row is None:
        fail(error_id, "%s does not exist" % ident)
    return row


def get_payer(ident):
    return _lookup(DB.payers, ident, "ERR_PAYER_NOT_FOUND")


def get_drug(ident):
    return _lookup(DB.drugs, ident, "ERR_DRUG_NOT_FOUND")


def get_policy(ident):
    return _lookup(DB.policies, ident, "ERR_POLICY_NOT_FOUND")


def get_patient(ident):
    return _lookup(DB.patients, ident, "ERR_PATIENT_NOT_FOUND")


def get_clinician(ident):
    return _lookup(DB.clinicians, ident, "ERR_CLINICIAN_NOT_FOUND")


def get_study(ident):
    return _lookup(DB.imaging_studies, ident, "ERR_IMAGING_STUDY_NOT_FOUND")


def get_plan(ident):
    return _lookup(DB.plans, ident, "ERR_PLAN_NOT_FOUND")


def get_lot(ident):
    return _lookup(DB.lots, ident, "ERR_LOT_NOT_FOUND")


def get_vial(ident):
    return _lookup(DB.vials, ident, "ERR_VIAL_NOT_FOUND")


def get_authorization(ident):
    return _lookup(DB.authorizations, ident, "ERR_AUTHORIZATION_NOT_FOUND")


def get_encounter(ident):
    return _lookup(DB.encounters, ident, "ERR_ENCOUNTER_NOT_FOUND")


def get_claim(ident):
    return _lookup(DB.claims, ident, "ERR_CLAIM_NOT_FOUND")


def get_enrollment(ident):
    return _lookup(DB.enrollments, ident, "ERR_ENROLLMENT_NOT_FOUND")


def get_adverse_event(ident):
    return _lookup(DB.adverse_events, ident, "ERR_ADVERSE_EVENT_NOT_FOUND")


def get_recall(ident):
    return _lookup(DB.recalls, ident, "ERR_RECALL_NOT_FOUND")


def get_notification(ident):
    return _lookup(DB.notifications, ident, "ERR_NOTIFICATION_NOT_FOUND")

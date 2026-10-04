"""Core: in-memory store, logical clock, response envelope, errors, auth/role guards."""

import uuid
from datetime import datetime, timedelta, timezone

from flask import request, jsonify, g

API_PREFIX = "/psc"

# ---------------------------------------------------------------------------
# Constants (read from PRD / scaffold §1.3)
# ---------------------------------------------------------------------------
DEFAULT_CLOCK = "2026-09-01T00:00:00Z"

SLOT_MINUTES_DEFAULT = 15
DRAW_HOLD_MINUTES_DEFAULT = 30

BAND_IMMEDIATE_MAX = 10
BAND_WITHIN_WINDOW_MAX = 30

EARLY_CHECKIN_MINUTES = 30
GRACE_MINUTES = 15
WAIT_MAX_CALL_WAIT_MINUTES = 30

COURIER_CHECKIN_LEAD_MINUTES = 30
COURIER_CHECKIN_GRACE_MINUTES = 0
COURIER_WINDOW_MINUTES = 720
COURIER_COMMIT_LEAD_MINUTES = 1080
COURIER_CUTOFF_BEFORE_DISPATCH_MINUTES = 15
COURIER_MAX_SPECIMENS_PER_RUN = 40

STABILITY_FACTOR = 1.0

ATTEMPTS_MAX_TOTAL = 2
ATTEMPTS_SAME_DAY_MINUTES_SINCE_FIRST = 60

REJECTION_DAY_CAP = 3

REPEAT_WINDOW_HOURS = 24

TIME_MAX_FUTURE_BOOKING_MINUTES = 10080

PEDIATRIC_AGE_MAX_YEARS = 18

ATTENDED_COLLECTED_RATE = 0.20
PEDIATRIC_FEE_MULTIPLIER = 1.10
EXPIRED_PLAN_DISCOUNT_PCT = 0.20
CLSI_MAX_SAFETY_ORDER = 6

ROLES = {"IntakeCoordinator", "Phlebotomist", "Patient", "LabLiaison",
         "CenterSupervisor", "LabSystem"}

TEST_PANELS = {"CMP", "CBC", "LIPID", "A1C", "TSH", "PT_INR", "FERRITIN",
               "HCG_QUAL", "LACTATE", "GTT"}
TUBE_PANELS = TEST_PANELS | {"BMP"}
COLLECTION_MODES = {"SELF_SERVICE", "STANDARD", "PEDIATRIC", "DIFFICULT_DRAW"}
CREDENTIALS = {"PBT", "PBT_PEDIATRIC", "RN"}
TUBE_CODES = {"EDTA_LAVENDER", "SST_GOLD", "SODIUM_CITRATE_BLUE",
              "SODIUM_FLUORIDE_GRAY", "SODIUM_HEPARIN_GREEN"}
PLAN_TYPES = {"HMO"}
PLAN_STATUS = {"ACTIVE", "TERMINATED"}
SPECIMEN_STATUSES = {"UNASSIGNED", "ASSIGNED", "IN_TRANSIT", "RECEIVED",
                     "COMPROMISED", "REJECTED", "RECOLLECTED"}
TEST_ORDER_STATUSES = {"RECEIVED", "SCHEDULED", "IN_PROGRESS", "COLLECTED",
                       "CANCELLED"}
APPOINTMENT_DRAW_STATES = {"SCHEDULED", "CHECKED_IN", "STAFF_PENDING", "IN_DRAW",
                           "ATTEMPT_LIMIT_REACHED", "DRAWN", "RESCHEDULED",
                           "NO_SHOW"}
APPOINTMENT_QUEUE_STATES = {"NONE", "WAITING", "CALLED", "AT_STATION",
                            "COMPLETED", "ABANDONED"}
COURIER_DIRECTIONS = {"OUTBOUND", "INBOUND"}
COURIER_STATUSES = {"PLANNED", "DISPATCHED", "IN_TRANSIT", "DELIVERED",
                    "CANCELLED"}
PHLEBOTOMIST_STATUSES = {"ON_DUTY", "OFF_DUTY"}
NECESSITY_STATUSES = {"PASS", "FAIL", "PENDING"}
INSURANCE_STATUSES = {"UNVERIFIED", "ELIGIBLE", "INELIGIBLE", "EXPIRED",
                      "NOT_COVERED"}
ESTIMATE_VARIANTS = {"PROVISIONAL_ELIGIBLE", "SELF_PAY_LIST", "ATTENDED_COLLECTED"}
COMPROMISE_REASONS = {"HEMOLYZED", "CLOTTED", "INSUFFICIENT_VOLUME"}

TUBE_PANEL_PROVIDER = {
    "CMP": "BMP",
    "LIPID": "CMP",
    "GTT": "SODIUM_FLUORIDE_GRAY",
}

# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.service_centers = {}
        self.patients = {}
        self.phlebotomists = {}
        self.insurance_plans = {}
        self.necessity_rules = {}
        self.tube_requirements = {}
        self.test_orders = {}
        self.appointments = {}
        self.specimens = {}
        self.courier_runs = {}
        self.estimates = {}
        self.runtime = {}


db = Store()


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
def utcnow():
    return datetime.strptime(DEFAULT_CLOCK, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc)


def parse_iso(v):
    """Parse an ISO 8601 instant (or bare date) into an aware UTC datetime."""
    if v is None:
        return None
    if isinstance(v, datetime):
        dt = v
    else:
        s = str(v).strip()
        try:
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            dt = datetime.fromisoformat(s)
        except ValueError:
            try:
                dt = datetime.strptime(str(v)[:10], "%Y-%m-%d")
            except ValueError:
                raise ApiError("ERR_INVALID_REQUEST", "Unparseable timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso(dt):
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return iso(get_clock())


def get_clock():
    return db.runtime["clock"]


def set_clock(dt):
    db.runtime["clock"] = dt


DEFAULT_CLOCK_DT = utcnow()
db.runtime["clock"] = DEFAULT_CLOCK_DT


def local_minute_of_day(dt, center):
    shifted = dt + timedelta(minutes=center["timezone_offset_minutes"])
    return shifted.hour * 60 + shifted.minute


def local_calendar_day(dt, center):
    shifted = dt + timedelta(minutes=center["timezone_offset_minutes"])
    return shifted.date()


# ---------------------------------------------------------------------------
# Rounding
# ---------------------------------------------------------------------------
def cents(x):
    """round_half_up on a non-negative real."""
    return int(x + 0.5)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, message="", http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = http_status or ERROR_STATUS[error_id]


ERROR_STATUS = {
    "ERR_MISSING_AUTH": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_SERVICE_CENTER_NOT_FOUND": 404,
    "ERR_PATIENT_NOT_FOUND": 400,
    "ERR_TEST_ORDER_NOT_FOUND": 400,
    "ERR_APPOINTMENT_NOT_FOUND": 404,
    "ERR_SPECIMEN_NOT_FOUND": 404,
    "ERR_COURIER_RUN_NOT_FOUND": 404,
    "ERR_INSURANCE_PLAN_NOT_FOUND": 400,
    "ERR_TUBE_REQUIREMENT_MISSING": 400,
    "ERR_DUPLICATE_MRN": 400,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_ALREADY_TERMINAL": 409,
    "ERR_CONCURRENT_CHILD_OPEN": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_PEDIATRIC_CENTER_NOT_CAPABLE": 422,
    "ERR_PEDIATRIC_DRAW_FLOOR_VIOLATION": 422,
    "ERR_ORDER_OF_DRAW_VIOLATION": 422,
    "ERR_FASTING_WINDOW_VIOLATED": 422,
    "ERR_STAFF_CREDENTIAL_INSUFFICIENT": 422,
    "ERR_COLLECTION_MODE_MISMATCH": 422,
    "ERR_MEDICAL_NECESSITY_FAILED": 402,
    "ERR_MEDICAL_NECESSITY_PENDING": 402,
    "ERR_INSURANCE_UNVERIFIED": 402,
    "ERR_INSURANCE_INELIGIBLE": 402,
    "ERR_INSURANCE_EXPIRED": 402,
    "ERR_NOT_COVERED_PANEL": 402,
    "ERR_PREPAY_REQUIRED": 402,
    "ERR_SLOT_ALREADY_TAKEN": 409,
    "ERR_STATION_CAPACITY_EXCEEDED": 409,
    "ERR_STAFFING_BUSY": 409,
    "ERR_DRAW_HOLD_CONFLICT": 409,
    "ERR_OUTSIDE_OPERATING_HOURS": 409,
    "ERR_NO_ELIGIBLE_COURIER_RUN": 422,
    "ERR_FUTURE_APPOINTMENT_TOO_FAR": 422,
}

MESSAGES = {
    "ERR_MISSING_AUTH": "Authentication headers are missing or the role is not recognized.",
    "ERR_FORBIDDEN_ROLE": "The calling role is not permitted for this operation.",
    "ERR_SERVICE_CENTER_NOT_FOUND": "The referenced service center does not exist.",
    "ERR_PATIENT_NOT_FOUND": "The referenced patient does not exist.",
    "ERR_TEST_ORDER_NOT_FOUND": "The referenced test order does not exist.",
    "ERR_APPOINTMENT_NOT_FOUND": "The referenced appointment does not exist.",
    "ERR_SPECIMEN_NOT_FOUND": "The referenced specimen does not exist.",
    "ERR_COURIER_RUN_NOT_FOUND": "The referenced courier run does not exist.",
    "ERR_INSURANCE_PLAN_NOT_FOUND": "The referenced insurance plan does not exist.",
    "ERR_TUBE_REQUIREMENT_MISSING": "No tube requirement matches the panel and tube code.",
    "ERR_DUPLICATE_MRN": "A patient already holds the supplied medical record number.",
    "ERR_INVALID_REQUEST": "The request is malformed.",
    "ERR_INVALID_STATE": "The resource is not in a state that permits this operation.",
    "ERR_ALREADY_TERMINAL": "The resource is already in a terminal state.",
    "ERR_CONCURRENT_CHILD_OPEN": "A concurrent child resource is already open.",
    "ERR_STALE_VERSION": "The supplied version does not match the current version.",
    "ERR_PEDIATRIC_CENTER_NOT_CAPABLE": "The center is not pediatric capable.",
    "ERR_PEDIATRIC_DRAW_FLOOR_VIOLATION": "A drawn tube is below the pediatric volume floor.",
    "ERR_ORDER_OF_DRAW_VIOLATION": "Specimen order of draw is not non-decreasing.",
    "ERR_FASTING_WINDOW_VIOLATED": "The fasting window had closed at the serving instant.",
    "ERR_STAFF_CREDENTIAL_INSUFFICIENT": "No on-duty phlebotomist credential covers the collection mode.",
    "ERR_COLLECTION_MODE_MISMATCH": "The requested collection mode disagrees with the order.",
    "ERR_MEDICAL_NECESSITY_FAILED": "Medical necessity resolved to FAIL.",
    "ERR_MEDICAL_NECESSITY_PENDING": "Medical necessity is still pending.",
    "ERR_INSURANCE_UNVERIFIED": "Insurance eligibility could not be verified.",
    "ERR_INSURANCE_INELIGIBLE": "The patient is ineligible under this plan.",
    "ERR_INSURANCE_EXPIRED": "The insurance plan is expired.",
    "ERR_NOT_COVERED_PANEL": "The panel is not covered under this plan.",
    "ERR_PREPAY_REQUIRED": "The required prepayment has not been collected.",
    "ERR_SLOT_ALREADY_TAKEN": "The occupancy interval collides with an existing one.",
    "ERR_STATION_CAPACITY_EXCEEDED": "The station-minute capacity has been exceeded.",
    "ERR_STAFFING_BUSY": "The phlebotomist shift listing overlaps an existing listing.",
    "ERR_DRAW_HOLD_CONFLICT": "A non-expired staff hold occupies the station.",
    "ERR_OUTSIDE_OPERATING_HOURS": "The occupancy falls outside the centre operating hours.",
    "ERR_NO_ELIGIBLE_COURIER_RUN": "No eligible courier run was found for this window.",
    "ERR_FUTURE_APPOINTMENT_TOO_FAR": "The booked start is beyond the booking horizon.",
}


def fail(error_id, message=None):
    raise ApiError(error_id, message or MESSAGES.get(error_id, error_id))


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _req_id():
    return "req_" + uuid.uuid4().hex[:20].upper()


def _meta(extra=None):
    m = {"api_request_id": _req_id(), "api_request_timestamp": now_iso()}
    if extra:
        m.update(extra)
    return m


def ok(data, response_type="object", status=200, pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


def ok_list(items, status=200):
    limit = g.get("limit", 10)
    offset = g.get("offset", 0)
    total = len(items)
    page = items[offset:offset + limit]
    return ok(page, response_type="array", status=status,
              pagination={"limit": limit, "offset": offset,
                          "total_count": total,
                          "has_more": offset + limit < total})


def ok_empty(status=200):
    return ok({}, status=status)


def read_pagination():
    """Read limit/offset (defaults 10 / 0, limit clamped to 1..100)."""
    limit = request.args.get("limit", default=10, type=int)
    offset = request.args.get("offset", default=0, type=int)
    if limit is None:
        limit = 10
    if offset is None:
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    g.limit = limit
    g.offset = offset
    return limit, offset


def sorted_rows(rows):
    # created_at ascending is the declared tie-break; id is never consulted.
    return sorted(rows, key=lambda r: r["created_at"])


def filter_rows(rows, data, key, param):
    value = request.args.get(param)
    if value is None:
        return rows
    return [r for r in rows if r.get(key) == value]


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
def current_role():
    return request.headers.get("X-User-Role")


def current_user():
    return request.headers.get("X-User-ID")


def require_auth(allowed_roles=None):
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not role or not uid or role not in ROLES:
        fail("ERR_MISSING_AUTH")
    if allowed_roles is not None and role not in allowed_roles:
        fail("ERR_FORBIDDEN_ROLE")
    return role


# ---------------------------------------------------------------------------
# Common field helpers
# ---------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def stamp(row):
    """Set id/created_at/updated_at/version on a new row."""
    row["id"] = new_id()
    row["created_at"] = now_iso()
    row["updated_at"] = row["created_at"]
    row["version"] = 1
    return row


def touch(row):
    row["updated_at"] = now_iso()
    row["version"] = row.get("version", 1) + 1
    return row


def get_center(cid):
    c = db.service_centers.get(cid)
    if c is None:
        fail("ERR_SERVICE_CENTER_NOT_FOUND")
    return c


def get_patient(pid):
    p = db.patients.get(pid)
    if p is None:
        fail("ERR_PATIENT_NOT_FOUND")
    return p


def get_order(oid):
    o = db.test_orders.get(oid)
    if o is None:
        fail("ERR_TEST_ORDER_NOT_FOUND")
    return o


def get_appointment(aid):
    a = db.appointments.get(aid)
    if a is None:
        fail("ERR_APPOINTMENT_NOT_FOUND")
    return a


def get_specimen(sid):
    s = db.specimens.get(sid)
    if s is None:
        fail("ERR_SPECIMEN_NOT_FOUND")
    return s


def get_run(rid):
    r = db.courier_runs.get(rid)
    if r is None:
        fail("ERR_COURIER_RUN_NOT_FOUND")
    return r


def get_plan(pid):
    p = db.insurance_plans.get(pid)
    if p is None:
        fail("ERR_INSURANCE_PLAN_NOT_FOUND")
    return p


def body():
    return request.get_json(silent=True) or {}


def require_fields(data, fields):
    for f in fields:
        if f not in data:
            fail("ERR_INVALID_REQUEST", "Missing required field: %s" % f)


def check_enum(value, allowed, field):
    if value not in allowed:
        fail("ERR_INVALID_REQUEST", "Invalid value for %s" % field)
    return value
"""Foundation layer: constants, logical clock, in-memory store, response
envelope, request-shape validation and identity/RBAC handling.

Every structural name here is taken from PRD.md (Shellfish Harvest
Classification API) and SCAFFOLD.yaml:
  * identity headers            X-User-ID / X-User-Role          (PRD 2.1)
  * envelope                    meta / response_type / data      (PRD 2.2)
  * error body                  error_id / message               (PRD 2.2)
  * pagination                  limit / offset / total_count / has_more
  * OCC fields                  expected_area_version / expected_dealer_version
"""

import random
import re
import string
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import g, request

from errors import ApiError

# --------------------------------------------------------------------------
# Named constants (PRD 3.x)
# --------------------------------------------------------------------------
DEFAULT_RAINFALL_CLOSURE_HOURS = 96
DEFAULT_REOPEN_SAMPLE_COUNT = 3
DEFAULT_CLEAN_SAMPLE_MPN_LIMIT = Decimal("14.0")
DEFAULT_RAINFALL_THRESHOLD_IN = Decimal("1.00")

MIN_SAMPLES_FOR_DECISION = 5
SAMPLE_WINDOW_SIZE = 15
P90_Z = Decimal("1.28")
GEOMEAN_APPROVED_LIMIT = Decimal("14.0")
P90_APPROVED_LIMIT = Decimal("43.0")
GEOMEAN_RESTRICTED_LIMIT = Decimal("88.0")
P90_RESTRICTED_LIMIT = Decimal("260.0")
ADVERSE_WINDOW_HOURS = 120

MAX_REVISION_ROUNDS = 3

DISEASE_CERT_MAX_AGE_DAYS = 30
MIN_NURSERY_DAYS = 21
SURVIVAL_FLOOR_PCT = Decimal("40.00")

FALLOW_DAYS = 14
INSPECTION_MAX_AGE_DAYS = 30
PREDATOR_CONTROL_MAX_AGE_DAYS = 60

DEFAULT_VESSEL_CAPACITY = 2
MAX_AUTHORIZATION_WINDOW_HOURS = 24

INTERTIDAL_PENALTY_MINUTES = 30
REFRIGERATION_CREDIT_MINUTES = 60
MIN_FLOOR_MINUTES = 60
MIN_PLAN_BASELINE_MINUTES = 60

TIER1_MAX_BUSHELS = 500
TIER2_MAX_BUSHELS = 2000
TIER1_RATE_CENTS = 115
TIER2_RATE_CENTS = 95
TIER3_RATE_CENTS = 70
INSPECTION_FEE_CENTS = 2500
INSPECTION_FEE_WAIVER_CENTS = 50000
SURCHARGE_RATE = Decimal("0.03")

TRACEBACK_DAY_WINDOW = 1
DEALER_SUSPENSION_STRIKE_THRESHOLD = 2

# --------------------------------------------------------------------------
# Roles and enumerations
# --------------------------------------------------------------------------
ROLE_AUTHORITY = "ShellfishControlAuthority"
ROLE_REVIEWER = "SitingReviewer"
ROLE_OPERATOR = "FarmOperator"
ROLE_HATCHERY = "HatcheryOperator"
ROLE_DEALER = "SeafoodDealer"
ALL_ROLES = [ROLE_AUTHORITY, ROLE_REVIEWER, ROLE_OPERATOR, ROLE_HATCHERY, ROLE_DEALER]

CLASSIFICATIONS = ["APPROVED", "CONDITIONALLY_APPROVED", "RESTRICTED", "PROHIBITED"]
RESTRICTIVENESS_RANK = {
    "APPROVED": 0,
    "CONDITIONALLY_APPROVED": 1,
    "RESTRICTED": 2,
    "PROHIBITED": 3,
}
HARVEST_STATUSES = ["OPEN", "CLOSED_RAINFALL", "CLOSED_SAMPLE_FAILURE"]
ELIGIBLE_CLASSIFICATIONS = ["INSUFFICIENT_DATA", "APPROVED", "RESTRICTED", "PROHIBITED"]
LEASE_STATUSES = [
    "DRAFT",
    "UNDER_REVIEW",
    "REVISION_REQUESTED",
    "PENDING_DECISION",
    "APPROVED",
    "DENIED",
]
CLEARANCE_VALUES = ["PENDING", "CLEARED", "OBJECTION"]
GEAR_TYPES = ["BOTTOM", "RACK_AND_BAG", "FLOATING_BAG"]
SPECIES = ["CRASSOSTREA_VIRGINICA", "MERCENARIA_MERCENARIA", "MYTILUS_EDULIS"]
SEED_LOT_STATUSES = [
    "RECEIVED",
    "SCREENED",
    "NURSERY",
    "READY_FOR_PLANTING",
    "PLANTED",
    "REJECTED",
]
NURSERY_SYSTEMS = ["UPWELLER", "FLOAT_UPWELLER", "RACK"]
GROWOUT_STATUSES = ["DEPLOYED", "HARVESTING", "RETRIEVED", "VOIDED"]
LOG_TYPES = ["INSPECTION", "PREDATOR_CONTROL", "DENSITY_THINNING", "GEAR_MAINTENANCE"]
PREDATOR_SPECIES = ["OYSTER_DRILL", "BLUE_CRAB", "COWNOSE_RAY", "SEA_STAR"]
CONTROL_METHODS = ["NETTING", "TRAPPING", "MANUAL_REMOVAL", "FENCING"]
SAMPLE_STATUSES = ["ACCEPTED", "SUPERSEDED"]
REFRIGERATION_TYPES = ["NONE", "ICE_SLURRY", "MECHANICAL"]
AUTHORIZATION_STATUSES = ["ISSUED", "ACTIVE", "CLOSED", "VOIDED"]
LOT_STATUSES = ["HARVESTED", "TAGGED", "SHIPPED", "EMBARGOED", "RECALLED", "VOIDED"]
TTT_BASIS_VARIANTS = ["FIRST_HARVEST_BASIS", "LAST_HARVEST_BASIS"]
COMPLIANCE_STATUSES = ["COMPLIANT", "NONCOMPLIANT"]
CERTIFICATION_CATEGORIES = [
    "SHELLSTOCK_SHIPPER",
    "SHUCKER_PACKER",
    "REPACKER",
    "DEPURATION_PROCESSOR",
]
LISTING_STATUSES = ["NOT_LISTED", "LISTED", "SUSPENDED"]
SHIPMENT_STATUSES = ["CREATED", "SHIPPED", "HELD", "RECALLED"]
INVESTIGATION_STATUSES = ["OPEN", "TRACEBACK", "CONFIRMED", "CLOSED_UNSUBSTANTIATED"]
SCOPE_VARIANTS = ["NARROW", "BROAD"]
PATHOGENS = [
    "VIBRIO_PARAHAEMOLYTICUS",
    "VIBRIO_VULNIFICUS",
    "NOROVIRUS",
    "SALMONELLA",
]
PLAN_STATUSES = ["ACTIVE", "SUPERSEDED"]
STAT_VARIANTS = ["SYSTEMATIC_RANDOM", "ADVERSE_CONDITION"]

# --------------------------------------------------------------------------
# Logical clock (PRD 2.5) — never reads the host wall clock.
# --------------------------------------------------------------------------
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class LogicalClock(object):
    def __init__(self):
        self.current = CLOCK_EPOCH

    def reset(self):
        self.current = CLOCK_EPOCH

    def now(self):
        return self.current

    def today(self):
        return self.current.date()

    def set(self, moment):
        self.current = moment


clock = LogicalClock()


# --------------------------------------------------------------------------
# Formatting helpers
# --------------------------------------------------------------------------
def iso(moment):
    """ISO 8601 UTC instant with exactly three fractional-second digits."""
    if moment is None:
        return None
    if not isinstance(moment, datetime):
        return moment
    moment = moment.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        moment.year,
        moment.month,
        moment.day,
        moment.hour,
        moment.minute,
        moment.second,
        moment.microsecond // 1000,
    )


def iso_date(value):
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat()
    return value


def num(value):
    """Serialise a Decimal (or raw JSON number) as a JSON number."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def q(value, places):
    """Round half-up to `places` decimal places."""
    exp = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(exp, rounding=ROUND_HALF_UP)


def new_id():
    return str(uuid.uuid4())


_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def truncated_minutes(start, end):
    """Whole minutes elapsed, truncated toward zero, at second resolution."""
    delta = int((end - start).total_seconds())
    if delta < 0:
        return -((-delta) // 60)
    return delta // 60


def second_resolution(moment):
    return moment.replace(microsecond=0)


# --------------------------------------------------------------------------
# In-memory store.  Starts EMPTY on every boot; nothing is ever seeded.
# --------------------------------------------------------------------------
class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.growing_areas = {}
        self.leases = {}
        self.hatcheries = {}
        self.seed_lots = {}
        self.growout_units = {}
        self.husbandry_logs = {}
        self.water_samples = {}
        self.rainfall_events = {}
        self.vessels = {}
        self.authorizations = {}
        self.harvest_lots = {}
        self.dealers = {}
        self.shipments = {}
        self.investigations = {}
        self.vibrio_plans = {}


db = Store()


def stamp_new(row, versioned=True):
    """Give a fresh row its identity/timestamp/version fields (PRD 2.4)."""
    row["id"] = new_id()
    row["created_at"] = clock.now()
    if versioned:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    return row


def apply_changes(row, changes):
    """Apply `changes`; bump version/updated_at only if something moved.

    A request that changes nothing on a row does not advance its version
    (PRD 2.4).  A row touched several times inside one request — directly and
    then again by a cascade hop or a counter recomputation — advances its
    version by exactly 1, which is what every "version advances by 1" claim in
    the PRD describes.
    """
    moved = False
    for key, value in changes.items():
        if key not in row or row[key] != value:
            row[key] = value
            moved = True
    if moved and "version" in row:
        try:
            bumped = g._bumped_rows
        except (AttributeError, RuntimeError):
            bumped = None
            try:
                bumped = set()
                g._bumped_rows = bumped
            except RuntimeError:
                bumped = None
        if bumped is None:
            row["version"] = row["version"] + 1
            row["updated_at"] = clock.now()
        elif row["id"] not in bumped:
            row["version"] = row["version"] + 1
            row["updated_at"] = clock.now()
            bumped.add(row["id"])
    return moved


def bump(row):
    """Force a version/updated_at advance on an already-mutated row."""
    if "version" in row:
        row["version"] = row["version"] + 1
        row["updated_at"] = clock.now()


def all_rows(table):
    return list(table.values())


# --------------------------------------------------------------------------
# Response envelope (PRD 2.2)
# --------------------------------------------------------------------------
def _meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": iso(clock.now()),
    }


def envelope_object(data):
    return {"meta": _meta(), "response_type": "object", "data": data}


def envelope_array(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    return {"meta": meta, "response_type": "array", "data": rows}


def envelope_error(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


# --------------------------------------------------------------------------
# Request-shape validation (PRD 2.7 rung 5 -> ERR_INVALID_REQUEST / 400)
# --------------------------------------------------------------------------
def invalid(message):
    return ApiError("ERR_INVALID_REQUEST", message)


def json_body():
    """The request body as a JSON object.  Absent body counts as {}."""
    if "_body" in g.__dict__:
        return g._body
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        parsed = {}
    else:
        parsed = request.get_json(silent=True)
        if parsed is None:
            raise invalid("Request body must be a JSON object.")
    if not isinstance(parsed, dict):
        raise invalid("Request body must be a JSON object.")
    g._body = parsed
    return parsed


_MISSING = object()


def _present(body, key, required):
    if key not in body or body[key] is None:
        if required:
            raise invalid("Field '%s' is required." % key)
        return False
    return True


def f_str(body, key, required=True, default=None, min_len=None, max_len=None,
          pattern=None, allow_blank=False):
    if not _present(body, key, required):
        return default
    value = body[key]
    if not isinstance(value, str):
        raise invalid("Field '%s' must be a string." % key)
    if not allow_blank and value.strip() == "":
        raise invalid("Field '%s' must be a non-empty string." % key)
    if min_len is not None and len(value) < min_len:
        raise invalid("Field '%s' must be at least %d characters." % (key, min_len))
    if max_len is not None and len(value) > max_len:
        raise invalid("Field '%s' must be at most %d characters." % (key, max_len))
    if pattern is not None and re.match(pattern, value) is None:
        raise invalid("Field '%s' is malformed." % key)
    return value


def f_int(body, key, required=True, default=None, minimum=None, maximum=None):
    if not _present(body, key, required):
        return default
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise invalid("Field '%s' must be an integer." % key)
    if minimum is not None and value < minimum:
        raise invalid("Field '%s' must be at least %s." % (key, minimum))
    if maximum is not None and value > maximum:
        raise invalid("Field '%s' must be at most %s." % (key, maximum))
    return value


def f_num(body, key, required=True, default=None, minimum=None, maximum=None,
          exclusive_minimum=None):
    """Returns a Decimal (exact, via str) or `default`."""
    if not _present(body, key, required):
        return default
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise invalid("Field '%s' must be a number." % key)
    dec = Decimal(str(value))
    if minimum is not None and dec < Decimal(str(minimum)):
        raise invalid("Field '%s' must be at least %s." % (key, minimum))
    if maximum is not None and dec > Decimal(str(maximum)):
        raise invalid("Field '%s' must be at most %s." % (key, maximum))
    if exclusive_minimum is not None and dec <= Decimal(str(exclusive_minimum)):
        raise invalid("Field '%s' must be greater than %s." % (key, exclusive_minimum))
    return dec


def f_bool(body, key, required=True, default=None):
    if not _present(body, key, required):
        return default
    value = body[key]
    if not isinstance(value, bool):
        raise invalid("Field '%s' must be a boolean." % key)
    return value


def f_enum(body, key, members, required=True, default=None):
    if not _present(body, key, required):
        return default
    value = body[key]
    if not isinstance(value, str) or value not in members:
        raise invalid(
            "Field '%s' must be one of %s." % (key, ", ".join(members))
        )
    return value


_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(\.\d{1,9})?"
    r"([Zz]|[+-]\d{2}:?\d{2})?$"
)


def parse_date(value, key):
    if not isinstance(value, str):
        raise invalid("Field '%s' must be a calendar date in YYYY-MM-DD form." % key)
    match = _DATE_RE.match(value)
    if match is None:
        raise invalid("Field '%s' must be a calendar date in YYYY-MM-DD form." % key)
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        raise invalid("Field '%s' is not a valid calendar date." % key)


def parse_instant(value, key):
    if not isinstance(value, str):
        raise invalid("Field '%s' must be an ISO 8601 UTC instant." % key)
    match = _INSTANT_RE.match(value)
    if match is None:
        raise invalid("Field '%s' must be an ISO 8601 UTC instant." % key)
    frac = match.group(7) or ".0"
    micro = int(round(float(frac) * 1000000))
    try:
        moment = datetime(
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3)),
            int(match.group(4)),
            int(match.group(5)),
            int(match.group(6)),
            micro,
            tzinfo=timezone.utc,
        )
    except ValueError:
        raise invalid("Field '%s' is not a valid instant." % key)
    offset = match.group(8)
    if offset is not None and offset not in ("Z", "z"):
        sign = 1 if offset[0] == "+" else -1
        digits = offset[1:].replace(":", "")
        delta = timedelta(hours=int(digits[0:2]), minutes=int(digits[2:4]))
        moment = moment - sign * delta
    return moment


def f_date(body, key, required=True, default=None):
    if not _present(body, key, required):
        return default
    return parse_date(body[key], key)


def f_instant(body, key, required=True, default=None):
    if not _present(body, key, required):
        return default
    return parse_instant(body[key], key)


def f_str_list(body, key, required=True, default=None, min_items=None,
               max_items=None, unique=False, members=None):
    if not _present(body, key, required):
        return default
    value = body[key]
    if not isinstance(value, list):
        raise invalid("Field '%s' must be an array." % key)
    for item in value:
        if not isinstance(item, str) or item.strip() == "":
            raise invalid("Field '%s' must contain non-empty strings." % key)
        if members is not None and item not in members:
            raise invalid(
                "Field '%s' must be a subset of %s." % (key, ", ".join(members))
            )
    if min_items is not None and len(value) < min_items:
        raise invalid("Field '%s' must hold at least %d entries." % (key, min_items))
    if max_items is not None and len(value) > max_items:
        raise invalid("Field '%s' must hold at most %d entries." % (key, max_items))
    if unique and len(set(value)) != len(value):
        raise invalid("Field '%s' entries must be unique." % key)
    return value


# --------------------------------------------------------------------------
# Pagination and filters (PRD 2.3)
# --------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0
PAGINATION_MIN_OFFSET = 0


def _query_int(name, default, minimum, maximum=None):
    raw = request.args.get(name)
    if raw is None:
        return default
    raw = raw.strip()
    if re.match(r"^[+-]?\d+$", raw) is None:
        raise invalid("Query parameter '%s' must be an integer." % name)
    value = int(raw)
    if value < minimum:
        raise invalid("Query parameter '%s' must be at least %d." % (name, minimum))
    if maximum is not None and value > maximum:
        raise invalid("Query parameter '%s' must be at most %d." % (name, maximum))
    return value


def pagination():
    limit = _query_int(
        "limit", PAGINATION_DEFAULT_LIMIT, PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT
    )
    offset = _query_int(
        "offset", PAGINATION_DEFAULT_OFFSET, PAGINATION_MIN_OFFSET
    )
    return limit, offset


def q_enum(name, members):
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw not in members:
        raise invalid(
            "Query parameter '%s' must be one of %s." % (name, ", ".join(members))
        )
    return raw


def q_str(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw == "":
        raise invalid("Query parameter '%s' must be non-empty." % name)
    return raw


def q_bool(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw in ("true", "True", "TRUE"):
        return True
    if raw in ("false", "False", "FALSE"):
        return False
    raise invalid("Query parameter '%s' must be a boolean." % name)


def q_int(name, minimum=None, maximum=None):
    raw = request.args.get(name)
    if raw is None:
        return None
    raw = raw.strip()
    if re.match(r"^[+-]?\d+$", raw) is None:
        raise invalid("Query parameter '%s' must be an integer." % name)
    value = int(raw)
    if minimum is not None and value < minimum:
        raise invalid("Query parameter '%s' must be at least %d." % (name, minimum))
    if maximum is not None and value > maximum:
        raise invalid("Query parameter '%s' must be at most %d." % (name, maximum))
    return value


def paginate(rows, limit, offset):
    return rows[offset:offset + limit]


def sort_default(rows):
    """Default list ordering: created_at ASC, ties by id ASC (PRD 2.3)."""
    return sorted(rows, key=lambda r: (r["created_at"], r["id"]))


def sort_journal(rows, key, descending):
    """A journal ordering: primary key, ties by created_at ASC then id ASC."""
    ordered = sorted(rows, key=lambda r: (r["created_at"], r["id"]))
    ordered.sort(key=lambda r: r[key], reverse=descending)
    return ordered


# --------------------------------------------------------------------------
# Identity, RBAC and ownership (PRD 2.1, ladder rungs 1-2 and 4)
# --------------------------------------------------------------------------
HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"


def authenticate(allowed_roles):
    user_id = request.headers.get(HEADER_USER_ID)
    role = request.headers.get(HEADER_USER_ROLE)
    if user_id is None or user_id.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role is None or role.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    g.user_id = user_id
    g.role = role
    return user_id, role


def acting_user():
    return g.user_id


def acting_role():
    return g.role


def require_lease_owner(lease):
    """Lease-scoped ownership: the acting FarmOperator must hold the lease."""
    if g.role == ROLE_OPERATOR and lease["operator_user_id"] != g.user_id:
        raise ApiError("ERR_LEASE_OWNERSHIP_VIOLATION")


# --------------------------------------------------------------------------
# Existence lookups (PRD 2.6, ladder rung 3)
# --------------------------------------------------------------------------
def _lookup(table, identifier, error_id):
    if not isinstance(identifier, str) or identifier == "":
        raise ApiError(error_id)
    row = table.get(identifier)
    if row is None:
        raise ApiError(error_id)
    return row


def get_area(identifier):
    return _lookup(db.growing_areas, identifier, "ERR_GROWING_AREA_NOT_FOUND")


def get_lease(identifier):
    return _lookup(db.leases, identifier, "ERR_LEASE_NOT_FOUND")


def get_hatchery(identifier):
    return _lookup(db.hatcheries, identifier, "ERR_HATCHERY_NOT_FOUND")


def get_seed_lot(identifier):
    return _lookup(db.seed_lots, identifier, "ERR_SEED_LOT_NOT_FOUND")


def get_unit(identifier):
    return _lookup(db.growout_units, identifier, "ERR_GROWOUT_UNIT_NOT_FOUND")


def get_vessel(identifier):
    return _lookup(db.vessels, identifier, "ERR_VESSEL_NOT_FOUND")


def get_authorization(identifier):
    return _lookup(db.authorizations, identifier, "ERR_AUTHORIZATION_NOT_FOUND")


def get_lot(identifier):
    return _lookup(db.harvest_lots, identifier, "ERR_HARVEST_LOT_NOT_FOUND")


def get_dealer(identifier):
    return _lookup(db.dealers, identifier, "ERR_DEALER_NOT_FOUND")


def get_shipment(identifier):
    return _lookup(db.shipments, identifier, "ERR_SHIPMENT_NOT_FOUND")


def get_investigation(identifier):
    return _lookup(db.investigations, identifier, "ERR_INVESTIGATION_NOT_FOUND")


def get_plan(identifier):
    return _lookup(db.vibrio_plans, identifier, "ERR_VIBRIO_PLAN_NOT_FOUND")


def body_ref(body, key, error_id):
    """A foreign key inside a request body: presence/type then existence."""
    if key not in body or body[key] is None:
        raise invalid("Field '%s' is required." % key)
    value = body[key]
    if not isinstance(value, str) or value.strip() == "":
        raise invalid("Field '%s' must be a non-empty string." % key)
    return value


# --------------------------------------------------------------------------
# Temporal admissibility (PRD 2.5, ladder rung 10)
# --------------------------------------------------------------------------
def check_not_future_instant(moment):
    if moment is None:
        return
    if moment.replace(microsecond=0) > clock.now().replace(microsecond=0):
        raise ApiError("ERR_FUTURE_DATED_EVENT")


def check_not_future_date(value):
    if value is None:
        return
    if value > clock.today():
        raise ApiError("ERR_FUTURE_DATED_EVENT")


def at_or_after_today(value):
    """A calendar date is current when it is at or after the clock's date."""
    return value is not None and value >= clock.today()

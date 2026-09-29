"""Authentication, role authorisation, department scope and request-shape guards.

The precedence bands of PRD 2.10 are enforced by calling these helpers in
order from each route: auth (1), role (2), scope (3), existence (4), shape (5),
concurrency (6), then the state / safety / temporal / constraint /
referential / fiscal checks that live in the services layer.
"""

from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError
from store import db
from util import dec, parse_date, parse_dt

ROLES = ("RegionalAdmin", "DepartmentManager", "Baker", "Decorator", "CakeDesk")
ANY_ROLE = ROLES

ALLERGEN_CODES = ("PEANUT", "TREE_NUT", "MILK", "EGG", "SOY", "WHEAT", "SESAME")
DAYPARTS = ("MORNING", "MIDDAY", "EVENING")
PRODUCTION_METHODS = ("SCRATCH", "PAR_BAKED", "THAW_AND_SERVE")
ALLERGEN_MODES = ("SHARED", "NUT_FREE_DEDICATED")
OVEN_STATUSES = ("AVAILABLE", "MAINTENANCE")
PLAN_POSTURES = ("DRAFT", "PLANNED", "LOCKED", "CLOSED")
MARKDOWN_AUTHORIZATIONS = ("AUTO", "MANAGER_ONLY")
EXECUTION_STATUSES = ("SCHEDULED", "PROOFING", "BAKING", "COMPLETED", "CANCELLED")
DISPOSITION_STATUSES = ("PENDING", "ON_SHELF", "MARKED_DOWN", "CLEARED")
REPLENISHMENT_STATES = ("OK", "REORDER_DUE", "ON_ORDER")
SLOT_STATUSES = ("OPEN", "CLOSED")
COMPLEXITIES = ("SIMPLE", "STANDARD", "PREMIUM")
CAKE_ORDER_STATUSES = ("INTAKE", "CONFIRMED", "IN_DECORATION", "READY", "PICKED_UP", "EXPIRED")
INGREDIENT_ORDER_STATUSES = ("DRAFT", "SUBMITTED", "RECEIVED_FULL", "RECEIVED_SHORT", "CANCELLED")
INGREDIENT_ORDER_ORIGINS = ("MANUAL", "AUTO_REORDER")
RUN_ORIGINS = ("PLAN_GENERATED", "MANUAL")
DISPOSITION_REASONS = ("DAY_OLD_UNSOLD", "DONATED", "DAMAGED", "BURNT", "OVERPRODUCTION")
RECORD_STATUSES = ("ACTIVE", "VOIDED")


# ---------------------------------------------------------------------------
# band 1 + 2: authentication and role authorisation
# ---------------------------------------------------------------------------

class Caller(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_manager(self):
        return self.role == "DepartmentManager"


def authenticate(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    return Caller(user_id, role)


# ---------------------------------------------------------------------------
# band 3: department scope (writes only -- every role may read everything)
# ---------------------------------------------------------------------------

def scope(caller, department_id):
    if caller.is_manager and department_id is not None and caller.user_id != department_id:
        raise ApiError("ERR_DEPARTMENT_SCOPE_VIOLATION")


def dept_of_bake_day(bake_day):
    return bake_day["department_id"]


def dept_of_run(run):
    bake_day = db.bake_days.get(run["bake_day_id"])
    return bake_day["department_id"] if bake_day else None


def dept_of_slot(slot):
    bake_day = db.bake_days.get(slot["bake_day_id"])
    return bake_day["department_id"] if bake_day else None


def dept_of_cake_order(order):
    bake_day = db.bake_days.get(order["bake_day_id"])
    return bake_day["department_id"] if bake_day else None


def dept_of_waste(record):
    bake_day = db.bake_days.get(record["bake_day_id"])
    return bake_day["department_id"] if bake_day else None


# ---------------------------------------------------------------------------
# band 4: existence
# ---------------------------------------------------------------------------

def find_department(department_id):
    row = db.departments.get(department_id) if isinstance(department_id, str) else None
    if row is None:
        raise ApiError("ERR_DEPARTMENT_NOT_FOUND")
    return row


def find_bake_day(bake_day_id):
    row = db.bake_days.get(bake_day_id) if isinstance(bake_day_id, str) else None
    if row is None:
        raise ApiError("ERR_BAKE_DAY_NOT_FOUND")
    return row


def find_product(product_id):
    row = db.products.get(product_id) if isinstance(product_id, str) else None
    if row is None:
        raise ApiError("ERR_PRODUCT_NOT_FOUND")
    return row


def find_ingredient(ingredient_id):
    row = db.ingredients.get(ingredient_id) if isinstance(ingredient_id, str) else None
    if row is None:
        raise ApiError("ERR_INGREDIENT_NOT_FOUND")
    return row


def find_oven(oven_id):
    row = db.ovens.get(oven_id) if isinstance(oven_id, str) else None
    if row is None:
        raise ApiError("ERR_OVEN_NOT_FOUND")
    return row


def find_run(run_id):
    row = db.runs.get(run_id) if isinstance(run_id, str) else None
    if row is None:
        raise ApiError("ERR_PRODUCTION_RUN_NOT_FOUND")
    return row


def find_slot(slot_id):
    row = db.pickup_slots.get(slot_id) if isinstance(slot_id, str) else None
    if row is None:
        raise ApiError("ERR_PICKUP_SLOT_NOT_FOUND")
    return row


def find_cake_order(order_id):
    row = db.cake_orders.get(order_id) if isinstance(order_id, str) else None
    if row is None:
        raise ApiError("ERR_CAKE_ORDER_NOT_FOUND")
    return row


def find_ingredient_order(order_id):
    row = db.ingredient_orders.get(order_id) if isinstance(order_id, str) else None
    if row is None:
        raise ApiError("ERR_INGREDIENT_ORDER_NOT_FOUND")
    return row


def find_waste_record(record_id):
    row = db.waste_records.get(record_id) if isinstance(record_id, str) else None
    if row is None:
        raise ApiError("ERR_WASTE_RECORD_NOT_FOUND")
    return row


# ---------------------------------------------------------------------------
# band 5: request shape
# ---------------------------------------------------------------------------

def body():
    """The JSON request body as a dict; an absent body is an empty object."""
    if not request.data:
        return {}
    try:
        payload = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return payload


def bad(field, detail):
    raise ApiError("ERR_INVALID_REQUEST", "%s %s" % (field, detail))


def present(payload, field):
    if field not in payload or payload[field] is None:
        bad(field, "is required.")
    return payload[field]


def as_string(payload, field, required=True, min_len=1, max_len=None, default=None):
    if field not in payload or payload[field] is None:
        if required:
            bad(field, "is required.")
        return default
    value = payload[field]
    if not isinstance(value, str):
        bad(field, "must be a string.")
    if min_len is not None and len(value.strip()) < min_len:
        bad(field, "must be a non-blank string of at least %d characters." % min_len)
    if max_len is not None and len(value) > max_len:
        bad(field, "may not exceed %d characters." % max_len)
    return value


def as_int(payload, field, required=True, minimum=None, maximum=None, default=None):
    if field not in payload or payload[field] is None:
        if required:
            bad(field, "is required.")
        return default
    value = payload[field]
    if isinstance(value, bool):
        bad(field, "must be an integer.")
    if isinstance(value, float):
        if value != int(value):
            bad(field, "must be an integer.")
        value = int(value)
    if not isinstance(value, int):
        bad(field, "must be an integer.")
    if minimum is not None and value < minimum:
        bad(field, "must be at least %d." % minimum)
    if maximum is not None and value > maximum:
        bad(field, "may not exceed %d." % maximum)
    return value


def as_decimal(payload, field, required=True, minimum=None, maximum=None,
               exclusive_min=False, exclusive_max=False, default=None):
    if field not in payload or payload[field] is None:
        if required:
            bad(field, "is required.")
        return default
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        bad(field, "must be a number.")
    try:
        number = dec(value)
    except (InvalidOperation, ValueError):
        bad(field, "must be a number.")
    if minimum is not None:
        if exclusive_min and number <= dec(minimum):
            bad(field, "must be greater than %s." % minimum)
        if not exclusive_min and number < dec(minimum):
            bad(field, "must be at least %s." % minimum)
    if maximum is not None:
        if exclusive_max and number >= dec(maximum):
            bad(field, "must be less than %s." % maximum)
        if not exclusive_max and number > dec(maximum):
            bad(field, "may not exceed %s." % maximum)
    return number


def as_bool(payload, field, required=False, default=None):
    if field not in payload or payload[field] is None:
        if required:
            bad(field, "is required.")
        return default
    value = payload[field]
    if not isinstance(value, bool):
        bad(field, "must be a boolean.")
    return value


def as_enum(payload, field, values, required=True, default=None):
    if field not in payload or payload[field] is None:
        if required:
            bad(field, "is required.")
        return default
    value = payload[field]
    if not isinstance(value, str) or value not in values:
        bad(field, "must be one of %s." % ", ".join(values))
    return value


def as_datetime(payload, field, required=True, default=None):
    if field not in payload or payload[field] is None:
        if required:
            bad(field, "is required.")
        return default
    parsed = parse_dt(payload[field])
    if parsed is None:
        bad(field, "must be an ISO-8601 instant.")
    return parsed


def as_calendar_date(payload, field, required=True):
    if field not in payload or payload[field] is None:
        if required:
            bad(field, "is required.")
        return None
    parsed = parse_date(payload[field])
    if parsed is None:
        bad(field, "must be a calendar date in YYYY-MM-DD form.")
    return parsed


def as_allergen_tags(payload, field):
    if field not in payload or payload[field] is None:
        return []
    value = payload[field]
    if not isinstance(value, list):
        bad(field, "must be an array of allergen codes.")
    tags = []
    for entry in value:
        if not isinstance(entry, str) or entry not in ALLERGEN_CODES:
            bad(field, "entries must be one of %s." % ", ".join(ALLERGEN_CODES))
        tags.append(entry)
    return tags


def as_object_array(payload, field, required=True):
    if field not in payload or payload[field] is None:
        if required:
            bad(field, "is required.")
        return []
    value = payload[field]
    if not isinstance(value, list):
        bad(field, "must be an array.")
    for entry in value:
        if not isinstance(entry, dict):
            bad(field, "entries must be objects.")
    return value


def bool_filter(args, name):
    raw = args.get(name)
    if raw is None or raw == "":
        return None
    lowered = str(raw).strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    raise ApiError("ERR_INVALID_REQUEST", "%s must be a boolean." % name)


def enum_filter(args, name, values):
    raw = args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in values:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be one of %s." % (name, ", ".join(values)))
    return raw

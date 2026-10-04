"""Rule-1 request-shape validation, rule-2/3 auth and rule-6/7 existence helpers.

The precedence ladder of PRD 2.5 is applied by the route handlers in this order:
1 body shape/enums/ranges, 2 auth header presence, 3 role authorization,
4-5 ownership, 6 path ids, 7 body foreign keys, 8-9 state, 10 OCC, 11-32 business.
"""

from flask import request

from core import DB, parse_dt
from errors import fail

# --------------------------------------------------------------------------
# Declared enum members (SCAFFOLD entities[].constraints)
# --------------------------------------------------------------------------
DISASTER_TYPES = {"EARTHQUAKE", "FLOOD", "HURRICANE", "WILDFIRE", "CONFLICT", "EPIDEMIC"}
DIETARY_TAGS = {"HALAL", "VEGETARIAN", "VEGAN", "NUT_FREE", "GLUTEN_FREE", "LOW_SODIUM"}
ACCESS_CONSTRAINTS = {"OPEN", "LIMITED", "RESTRICTED", "BLOCKED"}
POWER_SOURCES = {"GRID", "GENERATOR", "SOLAR", "NONE"}
WATER_SOURCES = {"PIPED", "TRUCKED", "WELL", "NONE"}
SITE_TYPES = {"SHELTER", "HOSPITAL", "NEIGHBORHOOD", "SCHOOL", "COMMUNITY_CENTER"}
VEHICLE_TYPES = {"CAR", "VAN", "TRUCK", "MOTORCYCLE"}
EARMARKS = {"UNRESTRICTED", "FIELD_KITCHENS", "RESTAURANT_ACTIVATION",
            "INGREDIENT_SOURCING", "LOGISTICS"}
ASSESSMENT_MODES = {"RAPID", "DURABLE"}

# State sets used for rule-1 to_state / dimension validation.
INCIDENT_STATES = {"MONITORING", "ACTIVE", "WINDING_DOWN", "CLOSED"}
FIELD_KITCHEN_STATES = {"SITED", "UTILITIES_PENDING", "FOOD_SAFETY_CLEARED",
                        "OPERATIONAL", "SUSPENDED", "DEMOBILIZED"}
CONTRACT_STATES = {"PROSPECT", "VETTING", "CONTRACTED", "SUSPENDED", "TERMINATED"}
PRODUCTION_STATES = {"IDLE", "PRODUCING", "AT_CAPACITY", "COOLDOWN"}
MEAL_ORDER_STATES = {"PLACED", "IN_PRODUCTION", "QUALITY_HOLD", "READY",
                     "DISPATCHED", "DELIVERED", "REJECTED", "CANCELLED"}
RUN_STATES = {"PLANNED", "LOADING", "EN_ROUTE", "DELIVERING", "COMPLETED", "ABORTED"}
STOP_STATES = {"PENDING", "DELIVERED", "FAILED", "SKIPPED"}
PURCHASE_STATES = {"REQUESTED", "CONFIRMED", "DELIVERED", "PAID", "DISPUTED", "CANCELLED"}
COMMITMENT_STATES = {"PLEDGED", "RECEIVED", "ALLOCATED", "PARTIALLY_DISBURSED",
                     "CLOSED", "WITHDRAWN"}

_MISSING = object()


# --------------------------------------------------------------------------
# Rule 1 -- body shape, enum members and numeric ranges
# --------------------------------------------------------------------------

def get_body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "The request body must be a well-formed JSON object.")
    return data


def _bad(key, detail):
    fail("ERR_INVALID_REQUEST", "Field '%s' %s." % (key, detail))


def _int_value(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def req_str(body, key, allow_empty=True):
    value = body.get(key, _MISSING)
    if value is _MISSING or not isinstance(value, str):
        _bad(key, "is required and must be a string")
    if not allow_empty and value == "":
        _bad(key, "must not be empty")
    return value


def opt_str(body, key, default=None, allow_empty=True):
    value = body.get(key, _MISSING)
    if value is _MISSING or value is None:
        return default
    if not isinstance(value, str):
        _bad(key, "must be a string")
    if not allow_empty and value == "":
        _bad(key, "must not be empty")
    return value


def req_int(body, key, minimum=None, maximum=None):
    value = _int_value(body.get(key, _MISSING))
    if value is None:
        _bad(key, "is required and must be an integer")
    if minimum is not None and value < minimum:
        _bad(key, "must be >= %s" % minimum)
    if maximum is not None and value > maximum:
        _bad(key, "must be <= %s" % maximum)
    return value


def opt_int(body, key, default=None, minimum=None, maximum=None):
    raw = body.get(key, _MISSING)
    if raw is _MISSING or raw is None:
        return default
    value = _int_value(raw)
    if value is None:
        _bad(key, "must be an integer")
    if minimum is not None and value < minimum:
        _bad(key, "must be >= %s" % minimum)
    if maximum is not None and value > maximum:
        _bad(key, "must be <= %s" % maximum)
    return value


def req_num(body, key, minimum=None, maximum=None, exclusive_min=False):
    raw = body.get(key, _MISSING)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        _bad(key, "is required and must be a number")
    if minimum is not None:
        if exclusive_min and raw <= minimum:
            _bad(key, "must be > %s" % minimum)
        if not exclusive_min and raw < minimum:
            _bad(key, "must be >= %s" % minimum)
    if maximum is not None and raw > maximum:
        _bad(key, "must be <= %s" % maximum)
    return raw


def req_bool(body, key):
    value = body.get(key, _MISSING)
    if not isinstance(value, bool):
        _bad(key, "is required and must be a boolean")
    return value


def req_enum(body, key, allowed):
    value = body.get(key, _MISSING)
    if not isinstance(value, str) or value not in allowed:
        _bad(key, "must be one of %s" % ", ".join(sorted(allowed)))
    return value


def opt_enum(body, key, allowed, default=None):
    value = body.get(key, _MISSING)
    if value is _MISSING or value is None:
        return default
    if not isinstance(value, str) or value not in allowed:
        _bad(key, "must be one of %s" % ", ".join(sorted(allowed)))
    return value


def req_str_list(body, key, allowed=None, default=None):
    raw = body.get(key, _MISSING)
    if raw is _MISSING or raw is None:
        if default is not None:
            return list(default)
        _bad(key, "is required and must be an array of strings")
    if not isinstance(raw, list) or not all(isinstance(x, str) for x in raw):
        _bad(key, "must be an array of strings")
    if allowed is not None:
        for item in raw:
            if item not in allowed:
                _bad(key, "carries an undeclared member '%s'" % item)
    return list(raw)


def req_datetime(body, key):
    value = body.get(key, _MISSING)
    if value is _MISSING or value is None:
        _bad(key, "is required and must be an ISO 8601 instant")
    return parse_dt(value)


def opt_datetime(body, key, default=None):
    value = body.get(key, _MISSING)
    if value is _MISSING or value is None:
        return default
    return parse_dt(value)


# --------------------------------------------------------------------------
# Rule 6 / rule 7 -- path and body identifier resolution
# --------------------------------------------------------------------------

PATH_ENTITY = {
    "incidents": ("incidents", "ERR_INCIDENT_NOT_FOUND"),
    "assessments": ("assessments", "ERR_RESOURCE_NOT_FOUND"),
    "field_kitchens": ("field_kitchens", "ERR_FIELD_KITCHEN_NOT_FOUND"),
    "partner_kitchens": ("partner_kitchens", "ERR_PARTNER_KITCHEN_NOT_FOUND"),
    "meal_orders": ("meal_orders", "ERR_MEAL_ORDER_NOT_FOUND"),
    "suppliers": ("suppliers", "ERR_RESOURCE_NOT_FOUND"),
    "ingredient_purchases": ("ingredient_purchases", "ERR_RESOURCE_NOT_FOUND"),
    "distribution_sites": ("distribution_sites", "ERR_RESOURCE_NOT_FOUND"),
    "distribution_runs": ("distribution_runs", "ERR_DISTRIBUTION_RUN_NOT_FOUND"),
    "distribution_stops": ("distribution_stops", "ERR_DISTRIBUTION_STOP_NOT_FOUND"),
    "donor_commitments": ("donor_commitments", "ERR_RESOURCE_NOT_FOUND"),
}


def path_row(kind, row_id):
    """Rule 6: the {id} in the path must resolve, else the entity's 404 error."""
    table, error_id = PATH_ENTITY[kind]
    row = DB[table].get(row_id)
    if row is None:
        fail(error_id)
    return row


def ref_row(kind, row_id):
    """Rule 7: a foreign key carried in the body must resolve."""
    table, _error_id = PATH_ENTITY[kind]
    row = DB[table].get(row_id)
    if row is None:
        fail("ERR_REFERENCED_ENTITY_NOT_FOUND")
    return row


def optional_ref_row(kind, row_id):
    if row_id is None:
        return None
    return ref_row(kind, row_id)


def same_incident(incident_id, *rows):
    """Rule 31: everything a request touches must belong to one activation."""
    for row in rows:
        if row is None:
            continue
        if row.get("incident_id") != incident_id:
            fail("ERR_CROSS_INCIDENT_REFERENCE")
    return True


# --------------------------------------------------------------------------
# Rules 2 and 3 -- authentication headers and role authorization
# --------------------------------------------------------------------------

def auth_headers():
    role = request.headers.get("X-User-Role") or ""
    user_id = request.headers.get("X-User-ID") or ""
    if not role.strip() or not user_id.strip():
        fail("ERR_MISSING_AUTH_HEADER")
    return role.strip(), user_id.strip()


def require_role(role, allowed):
    if role not in allowed:
        fail("ERR_UNAUTHORIZED_ROLE")


# --------------------------------------------------------------------------
# Pagination and query filters (PRD 2.3)
# --------------------------------------------------------------------------

def parse_pagination():
    args = request.args
    limit = 10
    raw_limit = args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_REQUEST", "Query parameter 'limit' must be between 1 and 100.")
    offset = 0
    raw_offset = args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "Query parameter 'offset' must be an integer.")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "Query parameter 'offset' must be >= 0.")
    return limit, offset


def query_filter(key):
    value = request.args.get(key)
    if value is None or value == "":
        return None
    return value

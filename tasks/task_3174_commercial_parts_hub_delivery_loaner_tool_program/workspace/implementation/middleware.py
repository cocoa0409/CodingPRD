"""Request context: authentication headers, role authorisation and the
parameter helpers every route shares.

PRD 2.1 owns the semantics:

  * both `X-User-ID` and `X-User-Role` are mandatory and the role must be one
    of the eight declared names, otherwise ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER;
  * a valid caller whose role is not authorised for the operation gets
    ERR_INSUFFICIENT_PERMISSIONS;
  * `Any` shares read access with every authenticated role.
"""

import db
import response
from errors import ApiError, bad_request

ROLES = (
    "CommercialSalesRep",
    "DeliveryDriver",
    "ToolCribAttendant",
    "CreditAnalyst",
    "RouteDispatcher",
    "PartsCategoryManager",
    "PlatformAdmin",
    "Any",
)

ROLE_SET = set(ROLES)


class Ctx(object):
    def __init__(self, headers, args, body, method, path):
        self.method = method
        self.path = path
        self.user_id = headers.get("X-User-ID")
        self.role = headers.get("X-User-Role")
        self.args = args
        self.body = body

    @property
    def is_rep(self):
        return self.role == "CommercialSalesRep"


def authenticate(headers):
    """PRD 2.12 step 1: header presence and validity, before anything else."""
    user_id = headers.get("X-User-ID")
    role = headers.get("X-User-Role")
    if user_id is None or str(user_id).strip() == "":
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-ID and X-User-Role headers must both be present.",
        )
    if role is None or str(role).strip() == "":
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-ID and X-User-Role headers must both be present.",
        )
    role = str(role).strip()
    if role not in ROLE_SET:
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-Role is not a declared role.",
        )
    return str(user_id).strip(), role


def authorize(role, allowed, method):
    """PRD 2.12 step 2: the caller's role against the endpoint's roles."""
    if role in allowed:
        return
    # `Any` shares read access with every authenticated role (PRD 2.1).
    if "Any" in allowed and method.upper() == "GET":
        return
    raise ApiError(
        "ERR_INSUFFICIENT_PERMISSIONS",
        "The caller's role is not authorised for this operation.",
    )


# ---------------------------------------------------------------------------
# parameter helpers
# ---------------------------------------------------------------------------

def require_fields(body, fields):
    if not isinstance(body, dict):
        bad_request("A JSON object body is required.")
    for field in fields:
        if field not in body or body[field] is None:
            raise ApiError("ERR_INVALID_REQUEST", "%s is required." % field)


def optional(body, field, default=None):
    if not isinstance(body, dict):
        return default
    value = body.get(field, default)
    return value


def int_field(body, field, default=None, required=False, minimum=None, maximum=None):
    if not isinstance(body, dict):
        bad_request("A JSON object body is required.")
    if field not in body or body[field] is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "%s is required." % field)
        return default
    raw = body[field]
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer." % field)
    if minimum is not None and value < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be at least %s." % (field, minimum))
    if maximum is not None and value > maximum:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be at most %s." % (field, maximum))
    return value


def number_field(body, field, default=None, required=False):
    if not isinstance(body, dict):
        bad_request("A JSON object body is required.")
    if field not in body or body[field] is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "%s is required." % field)
        return default
    try:
        return float(body[field])
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be a number." % field)


def bool_field(body, field, default=False):
    if not isinstance(body, dict):
        return default
    value = body.get(field, default)
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).lower() in ("true", "1", "yes")


def string_field(body, field, default=None, required=False):
    if not isinstance(body, dict):
        bad_request("A JSON object body is required.")
    if field not in body or body[field] is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "%s is required." % field)
        return default
    return str(body[field])


def iso_field(body, field, default=None, required=False):
    from timeutil import parse_iso
    if not isinstance(body, dict):
        bad_request("A JSON object body is required.")
    if field not in body or body[field] is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "%s is required." % field)
        return default
    try:
        parsed = parse_iso(body[field])
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an ISO 8601 instant." % field)
    return parsed


def enum_field(body, field, allowed, default=None, required=False):
    if not isinstance(body, dict):
        bad_request("A JSON object body is required.")
    if field not in body or body[field] is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "%s is required." % field)
        return default
    value = str(body[field])
    if value not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be one of %s." % (field, ", ".join(allowed)))
    return value


def line_items_field(body, field, required=True):
    if not isinstance(body, dict):
        bad_request("A JSON object body is required.")
    if field not in body or body[field] is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "%s is required." % field)
        return None
    lines = body[field]
    if not isinstance(lines, list):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an array." % field)
    out = []
    for entry in lines:
        if not isinstance(entry, dict):
            raise ApiError("ERR_INVALID_REQUEST", "Each order line must be an object.")
        out.append(entry)
    return out


# ---------------------------------------------------------------------------
# existence helpers (PRD 2.12 step 3, validated left to right along the path)
# ---------------------------------------------------------------------------

COLLECTION_OF = {
    "accountId": ("CommercialAccount", "accounts", "ERR_COMMERCIAL_ACCOUNT_NOT_FOUND"),
    "orderId": ("PartOrder", "part_orders", "ERR_PART_ORDER_NOT_FOUND"),
    "loanId": ("ToolLoan", "tool_loans", "ERR_TOOL_LOAN_NOT_FOUND"),
    "coreReturnId": ("CoreReturn", "core_returns", "ERR_CORE_RETURN_NOT_FOUND"),
    "routeId": ("ServiceRoute", "service_routes", "ERR_SERVICE_ROUTE_NOT_FOUND"),
    "stopId": ("RouteStop", "route_stops", "ERR_ROUTE_STOP_NOT_FOUND"),
    "storeId": ("Store", "stores", "ERR_STORE_NOT_FOUND"),
    "partId": ("Part", "parts", "ERR_PART_NOT_FOUND"),
    "vehicleId": ("Vehicle", "vehicles", "ERR_VEHICLE_NOT_FOUND"),
    "repId": ("SalesRep", "sales_reps", "ERR_SALES_REP_NOT_FOUND"),
    "coverageId": ("RepCoverage", "rep_coverages", "ERR_COVERAGE_NOT_FOUND"),
    "toolCatalogId": ("ToolCatalog", "tool_catalog", "ERR_TOOL_CATALOG_NOT_FOUND"),
    "itemId": ("InventoryItem", "inventory_items", "ERR_INVENTORY_ITEM_NOT_FOUND"),
    "registrationId": ("WarrantyRegistration", "warranty_registrations", "ERR_INVALID_REQUEST"),
    "fitmentId": (None, None, None),
    "interchangeId": (None, None, None),
}


def lookup(kind, row_id):
    """Resolve a path identifier to its row, or raise its not-found error."""
    entry = COLLECTION_OF.get(kind)
    if entry is None or entry[1] is None:
        return None
    mapping = getattr(db, entry[1])
    row = mapping.get(row_id)
    if row is None:
        raise ApiError(entry[2], "%s %s does not exist." % (entry[0], row_id))
    return row


def lookup_fitment(row_id):
    row = db.part_fitments.get(row_id) or db.tool_fitments.get(row_id)
    if row is None:
        raise ApiError("ERR_PART_NOT_FOUND", "Fitment %s does not exist." % row_id)
    return row


def lookup_interchange(row_id):
    row = db.part_interchanges.get(row_id)
    if row is None:
        raise ApiError("ERR_PART_NOT_FOUND", "Interchange %s does not exist." % row_id)
    return row


def enforce_rep_ownership(ctx, coverage):
    """PRD 2.1: a RepCoverage is reached through its rep_id, and a
    CommercialSalesRep's X-User-ID is the acting SalesRep's id.  The comparison
    is made when the caller is identifiable as a persisted rep."""
    if not ctx.is_rep:
        return
    if db.sales_reps.get(ctx.user_id) is None:
        return
    if coverage.get("rep_id") != ctx.user_id:
        raise ApiError(
            "ERR_INSUFFICIENT_PERMISSIONS",
            "The coverage assignment belongs to another representative.",
        )


def paginate_and_wrap(ctx, rows_list, as_array=True):
    rows_list = response.sort_by_created(rows_list)
    page, meta = response.paginate(rows_list, ctx.args.get("limit"), ctx.args.get("offset"))
    if as_array:
        return response.array(page, meta)
    return response.ok(page, meta)
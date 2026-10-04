"""Auth header extraction, role checking, body parsing and pagination.

Headers and roles come from SCAFFOLD.yaml validations[priority=1..2] and
PRD SS2.1: `X-User-ID` and `X-User-Role` are mandatory; the declared roles are
exactly the seven names below.
"""

from flask import g, request

from errors import fail

# The declared role names, verbatim from PRD SS2.1 / scaffold SS1.7.
ROLES = (
    "Customer",
    "ClinicContact",
    "PharmacyTechnician",
    "PharmacyManager",
    "CustomerService",
    "ComplianceOfficer",
    "PlatformAdmin",
)

# Roles whose X-User-ID is an opaque operator id (PRD SS2.1).
OPAQUE_ROLES = (
    "PharmacyTechnician",
    "PharmacyManager",
    "CustomerService",
    "ComplianceOfficer",
    "PlatformAdmin",
)


class Caller(object):
    def __init__(self, user_id, role):
        self.id = user_id
        self.role = role

    @property
    def is_customer(self):
        return self.role == "Customer"

    @property
    def is_clinic_contact(self):
        return self.role == "ClinicContact"


def authenticate():
    """Priority 1: header presence and role recognition, before anything else."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        fail(
            "ERR_MISSING_USER_CONTEXT",
            "X-User-ID and X-User-Role headers are required and X-User-Role must "
            "name a declared role.",
        )
    caller = Caller(user_id, role)
    g.caller = caller
    return caller


def enforce_before_routing():
    """Path-independent auth shim.

    PRD SS2.12: authentication precedes everything, so a request with no usable
    role context fails with ERR_MISSING_USER_CONTEXT even when the path it names
    does not exist. Flask routes unmatched paths to its own 404 handler without
    entering any view, so every request is authenticated once here, before the
    URL map is consulted.
    """
    if request.method == "OPTIONS":
        return None
    if request.path == "/" or request.path == "/healthz":
        return None
    authenticate()
    return None


def require_role(caller, allowed):
    """Priority 2: role permission for the target endpoint."""
    if caller.role not in allowed:
        fail(
            "ERR_ROLE_NOT_PERMITTED",
            "Role %s is not permitted on this operation." % caller.role,
        )
    return caller


def body():
    return request.get_json(silent=True) or {}


def require_body(body_dict):
    if not isinstance(body_dict, dict) or not body_dict:
        fail("ERR_INVALID_REQUEST", "A JSON request body is required.")
    return body_dict


def field(body_dict, name, required=True, default=None):
    """Fetch a body field, raising ERR_INVALID_REQUEST when required+absent."""
    if name in body_dict and body_dict[name] is not None:
        return body_dict[name]
    if required:
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
    return default


LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def pagination():
    """Read `limit`/`offset` with the scaffold's defaults and bounds; page a list."""
    raw_limit = request.args.get("limit", LIMIT_DEFAULT)
    raw_offset = request.args.get("offset", OFFSET_DEFAULT)
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "limit must be an integer.")
    try:
        offset = int(raw_offset)
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "offset must be an integer.")
    if limit < LIMIT_MIN:
        limit = LIMIT_MIN
    if limit > LIMIT_MAX:
        limit = LIMIT_MAX
    if offset < 0:
        offset = 0
    return limit, offset


def page(rows):
    """Return (page_rows, limit, offset, total_count) for a list response."""
    limit, offset = pagination()
    total = len(rows)
    return rows[offset : offset + limit], limit, offset, total


def bool_field(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes")
    return bool(value)


def int_field(value, name):
    if isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % name)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value != int(value):
            fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % name)
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % name)
    fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % name)
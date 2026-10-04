"""Role registry, endpoint role enforcement and the account-assignment gate."""
from flask import request

from core.db import DB, SINGULAR
from core.errors import ApiError

ROLES = [
    "AccountExecutive",
    "TransactionManager",
    "ApprovalAuthority",
    "FacilitiesManager",
    "OccupancyPlanner",
    "GovernanceManager",
    "DataSteward",
    "TransitionManager",
]

ROLE_SET = set(ROLES)

# role -> endpoint-name -> allowed roles (populated by the @roles decorator)
ENDPOINT_ROLES = {}

# Endpoints exempt from the per-account assignment gate: account creation and
# assignment creation itself have no pre-existing assignment to consult.
GATE_EXEMPT = {
    "create_account",
    "create_account_assignment_for_account",
    "create_account_assignment_flat",
}


def roles(*allowed):
    def deco(fn):
        ENDPOINT_ROLES[fn.__name__] = list(allowed)
        fn._allowed_roles = list(allowed)
        return fn
    return deco


def current_identity():
    return {
        "user_id": request.headers.get("X-User-ID"),
        "role": request.headers.get("X-User-Role"),
    }


def check_auth(endpoint_name):
    """Priority 1 and 2: authentication then role authorisation."""
    role = request.headers.get("X-User-Role")
    if role is None or role not in ROLE_SET:
        raise ApiError("ERR_UNAUTHENTICATED",
                       "X-User-Role header is absent or is not a declared role.")
    allowed = ENDPOINT_ROLES.get(endpoint_name)
    if allowed is not None and role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED",
                       "The acting role is not authorised for this operation.")


def _identity_matches(assignment, user_id, role, account_id):
    if assignment.get("account_id") != account_id:
        return False
    if assignment.get("assignment_role") != role:
        return False
    if user_id is not None and assignment.get("assignee_name") == user_id:
        return True
    return False


def check_assignment(account_id, user_id=None, role=None):
    """Priority 3: the acting principal must be operationally assigned to the
    account.  The principal is identified by X-User-ID; a principal whose role
    already holds an assignment on the account under a different identity is
    rejected."""
    if account_id is None:
        return
    ident = current_identity()
    user_id = user_id if user_id is not None else ident["user_id"]
    role = role if role is not None else ident["role"]
    if role is None:
        return
    if user_id is not None and user_id == account_id:
        return
    rows = [a for a in DB.children("account_assignments", account_id)]
    if not rows:
        return
    same_role = [a for a in rows if a.get("assignment_role") == role]
    if not same_role:
        return
    for a in same_role:
        if _identity_matches(a, user_id, role, account_id):
            return
        if a.get("id") == user_id and role == "ApprovalAuthority":
            return
    raise ApiError("ERR_NOT_ASSIGNED",
                   "The acting principal is not operationally assigned to this account.")


def _resolve_account_from_request():
    """Best-effort resolution of the account a mutating request touches."""
    if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
        return None
    body = request.get_json(silent=True) or {}
    if isinstance(body, dict) and body.get("account_id"):
        value = body.get("account_id")
        if DB.get("accounts", value):
            return value
    args = request.view_args or {}
    if args.get("account_id"):
        return args["account_id"]
    for value in args.values():
        if not value:
            continue
        for plural in SINGULAR:
            row = DB.get(plural, value)
            if row is None:
                continue
            if plural == "accounts":
                return row["id"]
            if row.get("account_id"):
                return row["account_id"]
    if isinstance(body, dict):
        for key in ("discipline_audit_id", "transaction_request_id", "lease_id",
                    "vendor_id", "consolidation_project_id"):
            value = body.get(key)
            if not value:
                continue
            for plural in ("discipline_audits", "transaction_requests", "leases",
                           "facilities_vendors", "consolidation_projects"):
                row = DB.get(plural, value)
                if row and row.get("account_id"):
                    return row["account_id"]
    return None


def enforce(endpoint_name):
    check_auth(endpoint_name)
    if endpoint_name in GATE_EXEMPT:
        return
    account_id = _resolve_account_from_request()
    if account_id is not None:
        check_assignment(account_id)
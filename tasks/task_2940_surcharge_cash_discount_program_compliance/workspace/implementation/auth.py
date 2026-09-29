"""Authentication, endpoint / action authorisation and path resolution.

Header names and role names are exactly those declared in PRD 2.1:
X-User-ID and X-User-Role over the six roles below.
"""

from flask import request

from errors import ApiError
from store import db

ROLES = (
    "PlatformAdmin",
    "ComplianceOfficer",
    "MerchantOperator",
    "NetworkAuditor",
    "StateRegulator",
    "TerminalAgent",
)

ALL_ROLES = list(ROLES)
READ_ROLES = list(ROLES)
SUMMARY_ROLES = ["PlatformAdmin", "ComplianceOfficer", "NetworkAuditor", "StateRegulator"]


class Actor(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    """Step 1 of the rejection ladder: header validity."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise ApiError("ERR_UNAUTHENTICATED")
    user_id = user_id.strip()
    role = role.strip()
    if user_id == "" or role == "" or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    return Actor(user_id, role)


def authorize(allowed_roles):
    """Steps 1 and 2: header validity then endpoint authorisation."""
    actor = authenticate()
    if actor.role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    return actor


# ---------------------------------------------------------------- step 3
ACTION_ROLES = {
    "program_status": {
        "SUSPEND": ("ComplianceOfficer", "NetworkAuditor"),
        "RESUME": ("ComplianceOfficer",),
        "WITHDRAW": ("ComplianceOfficer",),
    },
    "terminal_state": {
        "ENFORCE": ("MerchantOperator",),
        "RESTORE": ("MerchantOperator",),
        "QUARANTINE": ("MerchantOperator", "ComplianceOfficer"),
    },
    "investigation": {
        "REVIEW": ("ComplianceOfficer",),
        "SUBSTANTIATE": ("NetworkAuditor", "StateRegulator"),
        "DISMISS": ("NetworkAuditor", "StateRegulator"),
    },
    "remediation": {
        "SUBMIT_PLAN": ("ComplianceOfficer",),
        "ACCEPT_PLAN": ("NetworkAuditor", "StateRegulator"),
        "CLOSE": ("NetworkAuditor", "StateRegulator"),
    },
}


def check_action_role(family, action, actor):
    """Action-level authorisation.

    An unrecognised action value is left to the request-shape step so that the
    ladder's 400 for a bogus enum member is not masked by a 403.
    """
    table = ACTION_ROLES[family]
    if not isinstance(action, str) or action not in table:
        return
    if actor.role not in table[action]:
        raise ApiError("ERR_ACTION_ROLE_FORBIDDEN")


# ---------------------------------------------------------------- step 5
def check_merchant_ownership(actor, merchant_id):
    if actor.role == "MerchantOperator" and actor.user_id != merchant_id:
        raise ApiError("ERR_MERCHANT_OWNERSHIP_REQUIRED")


# ---------------------------------------------------------------- step 7
SOURCE_ROLE = {
    "NETWORK": "NetworkAuditor",
    "CARDHOLDER": "NetworkAuditor",
    "ATTORNEY_GENERAL": "StateRegulator",
}


def check_complaint_channel(actor, source):
    """Complaint channel ownership; only the two deciding roles are constrained."""
    if actor.role not in ("NetworkAuditor", "StateRegulator"):
        return
    owner = SOURCE_ROLE.get(source)
    if owner is None:
        return
    if actor.role != owner:
        raise ApiError("ERR_COMPLAINT_SOURCE_ROLE_MISMATCH")


# ---------------------------------------------------------------- step 4 / 10
def _lookup(table, row_id, error_id):
    if not isinstance(row_id, str):
        raise ApiError(error_id)
    row = table.get(row_id)
    if row is None:
        raise ApiError(error_id)
    return row


def get_jurisdiction(row_id):
    return _lookup(db.jurisdictions, row_id, "ERR_JURISDICTION_NOT_FOUND")


def get_merchant(row_id):
    return _lookup(db.merchants, row_id, "ERR_MERCHANT_NOT_FOUND")


def get_cost_documentation(row_id):
    return _lookup(db.cost_documentations, row_id, "ERR_COST_DOCUMENTATION_NOT_FOUND")


def get_program(row_id):
    return _lookup(db.programs, row_id, "ERR_PROGRAM_NOT_FOUND")


def get_rate_rule(row_id):
    return _lookup(db.rate_rules, row_id, "ERR_PROGRAM_NOT_FOUND")


def get_registration(row_id):
    return _lookup(db.registrations, row_id, "ERR_REGISTRATION_NOT_FOUND")


def get_artifact(row_id):
    return _lookup(db.artifacts, row_id, "ERR_ARTIFACT_NOT_FOUND")


def get_terminal(row_id):
    return _lookup(db.terminals, row_id, "ERR_TERMINAL_NOT_FOUND")


def get_transaction(row_id):
    return _lookup(db.transactions, row_id, "ERR_TRANSACTION_NOT_FOUND")


def get_complaint_case(row_id):
    return _lookup(db.complaint_cases, row_id, "ERR_COMPLAINT_NOT_FOUND")


def get_refund(row_id):
    return _lookup(db.refunds, row_id, "ERR_REFUND_NOT_FOUND")

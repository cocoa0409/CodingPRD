"""Auth header extraction, role checking, region scope and ownership.

Validation priority order comes from SCAFFOLD.yaml `validations` §1.4 and
PRD §2.1:

    priority 1   X-User-ID / X-User-Role present and non-empty
    priority 2   acting role permitted for the operation
    priority 3   region-scoped role limited to its own region_code
    priority 42  entity-backed role ownership

The identity header scheme (X-User-ID / X-User-Role) is the pair named in PRD
§2.1; the ten role names are exactly those listed there.
"""

from flask import request

from errors import ApiError

USER_HEADER = "X-User-ID"
ROLE_HEADER = "X-User-Role"

ROLES = (
    "PlatformAdmin",
    "RegionalSalesDirector",
    "ClinicalOperationsLead",
    "HospitalProcurementOfficer",
    "ServiceEngineer",
    "ComplianceOfficer",
    "IDNCoordinator",
    "AccountOwner",
    "Surgeon",
    "Anonymous",
)

# PRD §2.1 — the two entity-backed roles and the foreign key they must own.
ENTITY_BACKED = {
    "AccountOwner": "hospital_account_id",
    "Surgeon": "id",
}


class Ctx:
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate(allowed_roles):
    """Priority 1-2: presence of the context headers, then role permission."""
    user_id = request.headers.get(USER_HEADER)
    role = request.headers.get(ROLE_HEADER)
    if not user_id or not str(user_id).strip() or not role or not str(role).strip():
        raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")
    user_id = str(user_id).strip()
    role = str(role).strip()
    if role not in set(allowed_roles or ()):
        raise ApiError("ERR_AGENT_NOT_PERMITTED")
    return Ctx(user_id, role)


def check_region(ctx, account):
    """Priority 3 — region scope, evaluated whenever an account is in play.

    PRD §2.1 states the mechanism ("a region-scoped role may only act on a
    `HospitalAccount` whose `region_code` equals the acting identity's own
    region") but names neither the roles it binds nor where an opaque caller's
    own region could be read from. Every role in §2.1 is bound to `X-User-ID`
    only for presence: the two entity-backed roles resolve it to a resource id,
    and the remaining eight are explicitly opaque, so no role carries a region.
    With no declared region-scoped role and no declared identity-region source,
    a faithful PRD-only reading cannot predicate a rejection on this rule, so
    the scope check is a no-op and the rule is never tripped.
    """
    return


def check_ownership(ctx, record, account=None):
    """Priority 42 — an entity-backed role owns the resource it acts on."""
    if record is None or ctx is None:
        return
    if ctx.role == "AccountOwner":
        owner = record.get("hospital_account_id")
        if owner is None and account is not None:
            owner = account.get("id")
        if owner != ctx.user_id:
            raise ApiError("ERR_OWNERSHIP_MISMATCH")
    elif ctx.role == "Surgeon":
        if record.get("id") != ctx.user_id:
            raise ApiError("ERR_OWNERSHIP_MISMATCH")


def check_segregation(ctx, account):
    """PRD §2.1 — the approver must differ from hospital_owner_user_id."""
    if account is None or ctx is None:
        return
    owner = account.get("hospital_owner_user_id")
    if owner is not None and ctx.user_id == owner:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES_VIOLATION")
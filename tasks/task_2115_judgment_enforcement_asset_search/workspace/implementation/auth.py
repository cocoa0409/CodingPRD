"""Identity headers, roles and ownership (PRD sections 2.1 / 2.8 rungs 1-4)."""

from flask import request

from errors import ApiError

ROLES = (
    "CaseManager",
    "AssetInvestigator",
    "EnforcementOfficer",
    "ComplianceOfficer",
    "Creditor",
    "Debtor",
)
ROLE_SET = set(ROLES)
ENTITY_BACKED = ("Creditor", "Debtor")

ALL_STAFF = ("CaseManager", "AssetInvestigator", "EnforcementOfficer", "ComplianceOfficer")


class Ctx(object):
    __slots__ = ("role", "user_id")

    def __init__(self, role, user_id):
        self.role = role
        self.user_id = user_id

    @property
    def is_creditor(self):
        return self.role == "Creditor"

    @property
    def is_debtor(self):
        return self.role == "Debtor"

    @property
    def entity_backed(self):
        return self.role in ENTITY_BACKED


def authenticate(allowed_roles):
    # rung 1 - X-User-Role present and one of the six declared roles
    role = request.headers.get("X-User-Role")
    if role is None or role not in ROLE_SET:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role must name one of the six declared roles.")
    user_id = request.headers.get("X-User-ID")
    # rung 2 - entity-backed roles must identify themselves
    if role in ENTITY_BACKED and not user_id:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID is required for entity-backed roles.")
    # rung 3 - the acting role appears in the endpoint's authorized list
    if role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED", "Role %s may not call this endpoint." % role)
    return Ctx(role, user_id)


def check_judgment_ownership(ctx, judgment):
    """rung 4 - entity-backed ownership against the governing judgment."""
    if judgment is None:
        return
    if ctx.role == "Creditor" and judgment.get("creditor_id") != ctx.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Caller does not own this judgment.")
    if ctx.role == "Debtor" and judgment.get("debtor_id") != ctx.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Caller does not own this judgment.")


def owns_judgment(ctx, judgment):
    if judgment is None:
        return False
    if ctx.role == "Creditor":
        return judgment.get("creditor_id") == ctx.user_id
    if ctx.role == "Debtor":
        return judgment.get("debtor_id") == ctx.user_id
    return True

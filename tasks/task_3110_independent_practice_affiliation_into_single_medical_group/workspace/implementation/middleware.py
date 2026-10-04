"""Auth middleware: X-User-ID / X-User-Role extraction and role checking."""

from flask import request

from errors import err_auth, err_perms

ROLES = {
    "GroupAdministrator",
    "PayerContractingOfficer",
    "CredentialingCoordinator",
    "PracticeExecutive",
    "DistributionAccountant",
    "GroupFinancialController",
    "MarketCommitteeChair",
    "PhysicianBoardMember",
    "ComplianceOfficer",
}


def get_context():
    """Return (user_id, role); raises ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER
    when either header is missing or the role is not one of the nine."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise err_auth()
    if not role or role not in ROLES:
        raise err_auth()
    return user_id, role


def require_roles(*allowed):
    """Return (user_id, role) after enforcing endpoint role set."""
    user_id, role = get_context()
    if role not in allowed:
        raise err_perms()
    return user_id, role

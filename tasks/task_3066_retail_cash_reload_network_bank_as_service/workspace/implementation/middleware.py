"""Auth header extraction and role checking.

PRD 2.1: every request carries two mandatory headers, `X-User-ID` and
`X-User-Role`.  A missing header, or a role string that is not one of the seven
declared roles, is `ERR_UNAUTHENTICATED` (401).  A declared role that is not
authorised for the operation is `ERR_UNAUTHORIZED` (403).
"""

from flask import request

import errors

ROLES = (
    "PlatformAdmin",
    "BankSponsor",
    "ProgramManager",
    "RetailerClerk",
    "ComplianceAnalyst",
    "ComplianceOfficer",
    "SettlementOperator",
)

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"


def authenticate(allowed_roles):
    """Validate the two headers and the role's authorisation for the call."""
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if not user_id or not role:
        raise errors.unauthenticated(
            "%s and %s headers are required." % (USER_ID_HEADER, USER_ROLE_HEADER)
        )
    if role not in ROLES:
        raise errors.unauthenticated(
            "%r is not a declared role." % (role,)
        )
    if role not in allowed_roles:
        raise errors.unauthorized(
            "Role %s is not authorised for this operation." % (role,)
        )
    return user_id, role
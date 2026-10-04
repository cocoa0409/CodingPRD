"""Authentication header extraction and role checking.

PRD 2.1 / SCAFFOLD validations priority 1: every request carries
`X-User-ID` and `X-User-Role`.  A missing header or an unrecognised role is
ERR_UNAUTHENTICATED (401).  A recognised role that may not perform the
operation is ERR_FORBIDDEN (403).
"""

from constants import ROLES
from errors import ApiError, ERR_FORBIDDEN, ERR_UNAUTHENTICATED

ROLE_HEADER = "X-User-Role"
IDENTITY_HEADER = "X-User-ID"

# PRD 2.1: the only role whose identity is entity-backed is LicensorApprover,
# whose X-User-ID is the id of the acting License.
ENTITY_BACKED_ROLE = "LicensorApprover"
ENTITY_BACKED_COLLECTION = "licenses"


class Principal(object):
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_entity_backed(self):
        return self.role == ENTITY_BACKED_ROLE


def authenticate(headers):
    role = headers.get(ROLE_HEADER)
    user_id = headers.get(IDENTITY_HEADER)
    if not role or not user_id:
        raise ApiError(
            ERR_UNAUTHENTICATED,
            "Both %s and %s headers are required" % (ROLE_HEADER, IDENTITY_HEADER),
        )
    if role not in ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, "Unknown %s value: %s" % (ROLE_HEADER, role))
    return Principal(user_id, role)


def require_role(principal, allowed):
    """Require the acting role to be one of `allowed`.

    PlatformAdmin holds no business exclusives but may read across every
    resource; read endpoints that enumerate PlatformAdmin explicitly pass it in
    `allowed`, so this is a plain membership test.
    """
    if principal.role not in allowed:
        raise ApiError(
            ERR_FORBIDDEN,
            "Role %s is not permitted to perform this operation" % principal.role,
        )


def require_licensor_ownership(principal, approver_id):
    """LicensorApprover acts for exactly one licensor instance at a time.

    PRD 2.1: an artwork approval's approver_id is compared against X-User-ID,
    and an operation attempted against another licensor's artwork is refused.
    """
    if principal.role != ENTITY_BACKED_ROLE:
        return
    if principal.user_id != approver_id:
        raise ApiError(
            ERR_FORBIDDEN,
            "LicensorApprover %s does not hold the approval right for %s"
            % (principal.user_id, approver_id),
        )
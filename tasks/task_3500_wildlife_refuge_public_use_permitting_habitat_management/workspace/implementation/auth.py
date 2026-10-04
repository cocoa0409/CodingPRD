"""Authentication (validation priority 1) and authorization/ownership
(priority 2). Header scheme from PRD 2.1: X-User-Role + X-User-ID; X-User-ID
is required for every role except Anonymous. Only the Volunteer role's
X-User-ID is entity-backed (it IS the Volunteer.id); all others are opaque."""
import functools
from flask import request
from envelope import fail

ROLES = (
    'RefugeManager', 'Biologist', 'PermitOfficer', 'VolunteerCoordinator',
    'LawEnforcementOfficer', 'StateAgencyPartner', 'PermitApplicant',
    'Cooperator', 'Volunteer', 'Anonymous',
)

# The six staff roles that share staff read endpoints (RefugeManager override
# is already spelled out in each endpoint's role list in PRD section 4).
STAFF_READERS = (
    'RefugeManager', 'Biologist', 'PermitOfficer', 'VolunteerCoordinator',
    'LawEnforcementOfficer', 'StateAgencyPartner',
)


def caller():
    role = request.headers.get('X-User-Role')
    uid = request.headers.get('X-User-ID')
    if role is None or role not in ROLES:
        fail('ERR_UNAUTHENTICATED', 'X-User-Role header missing or not a declared role')
    if role != 'Anonymous' and (uid is None or uid == ''):
        fail('ERR_UNAUTHENTICATED', 'X-User-ID header is required for this role')
    return role, uid


def endpoint(allowed_roles):
    """Decorator: runs priority-1 auth then priority-2 role-list check, then
    invokes the view as fn(role, uid, *path_params)."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            role, uid = caller()
            if role not in allowed_roles:
                fail('ERR_UNAUTHORIZED_ROLE', 'role is not authorized for this endpoint')
            return fn(role, uid, *args, **kwargs)
        return wrapper
    return deco


def forbidden(msg='ownership anchor violated'):
    fail('ERR_UNAUTHORIZED_ROLE', msg)


def not_found(msg='resource not found'):
    fail('ERR_NOT_FOUND', msg)


def invalid_state(msg='state precondition failed'):
    fail('ERR_INVALID_STATE', msg)

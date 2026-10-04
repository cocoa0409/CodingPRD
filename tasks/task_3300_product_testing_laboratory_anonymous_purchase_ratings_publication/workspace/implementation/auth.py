from flask import request
from resp import err

ROLES = {
    'LabManager', 'EditorialDirector', 'MethodologyOfficer', 'PurchasingAgent',
    'ComplianceOfficer', 'LabTechnician', 'SurveyDirector', 'ContentEditor',
    'SafetyOfficer', 'Member',
}


def auth_headers():
    """Return (user_id, role). Raises 401 on missing headers or unknown role."""
    uid = request.headers.get('X-User-ID')
    role = request.headers.get('X-User-Role')
    if not uid or not role:
        err('ERR_UNAUTHENTICATED', 'X-User-ID and X-User-Role headers are required', 401)
    if role not in ROLES:
        err('ERR_UNAUTHENTICATED', 'Unknown role', 401)
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        err('ERR_UNAUTHORIZED', f'Role {role} is not permitted for this endpoint', 403)

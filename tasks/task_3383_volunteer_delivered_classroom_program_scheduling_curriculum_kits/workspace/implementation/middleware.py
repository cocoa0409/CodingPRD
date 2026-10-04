"""Auth (PRD 2.1), role checks, body-shape validation, and pagination (2.3)."""
from flask import g, request

from errors import (ApiError, ERR_FORBIDDEN, ERR_UNAUTHENTICATED,
                    ERR_VALIDATION)

ROLES = (
    'PlatformAdmin',
    'AreaDirector',
    'PartnershipManager',
    'ProgramCoordinator',
    'LogisticsCoordinator',
    'Funder',
)


def authenticate():
    """before_request hook: X-User-ID and X-User-Role must be present and the
    role must be one of the six recognized roles, else ERR_UNAUTHENTICATED."""
    if not request.path.startswith('/ja-programs'):
        return None
    user_id = request.headers.get('X-User-ID')
    role = request.headers.get('X-User-Role')
    if not user_id or not role or role not in ROLES:
        raise ApiError(ERR_UNAUTHENTICATED,
                       'Missing or unrecognized X-User-ID / X-User-Role headers', 401)
    g.user_id = user_id
    g.role = role
    return None


def require_roles(*roles):
    if g.get('role') not in roles:
        raise ApiError(ERR_FORBIDDEN,
                       'Role %s is not permitted to invoke this operation' % g.get('role'),
                       403)


def bad(message):
    raise ApiError(ERR_VALIDATION, message, 400)


def get_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        bad('Request body must be a JSON object')
    return body


def _is_str(v):
    return isinstance(v, str)


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_bool(v):
    return isinstance(v, bool)


def _is_list(v):
    return isinstance(v, list)


def _opt_str(v):
    return v is None or isinstance(v, str)


def _opt_int(v):
    return v is None or (isinstance(v, int) and not isinstance(v, bool))


def validate_body(body, spec):
    """spec: {field: (required, checker)}. Rejects undeclared fields, missing
    required fields, and wrongly-typed values with ERR_VALIDATION (tier 3)."""
    for key in body:
        if key not in spec:
            bad('Undeclared field in request body: %s' % key)
    for key, (required, checker) in spec.items():
        if key not in body:
            if required:
                bad('Missing required field: %s' % key)
            continue
        if not checker(body[key]):
            bad('Invalid value for field: %s' % key)


def parse_pagination():
    limit_raw = request.args.get('limit')
    offset_raw = request.args.get('offset')
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except ValueError:
            bad('limit must be an integer')
        if limit < 1 or limit > 100:
            bad('limit must be between 1 and 100')
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except ValueError:
            bad('offset must be an integer')
        if offset < 0:
            bad('offset must be >= 0')
    return limit, offset


def paginate(records):
    """Sort by created_at ascending (insertion-order tiebreak) and slice."""
    limit, offset = parse_pagination()
    ordered = sorted(records, key=lambda r: (r['created_at'], r['_seq']))
    total = len(ordered)
    return ordered[offset:offset + limit], total, limit, offset


def apply_filters(records, mapping):
    """mapping: query param name -> record field name; exact-match filters."""
    for param, key in mapping.items():
        value = request.args.get(param)
        if value is not None:
            records = [r for r in records if str(r.get(key)) == value]
    return records

"""Request plumbing: auth context (cascade tier 1), role authorization (tier 2),
body well-formedness validators (tier 4), pagination, and path existence (tier 3).
"""
from flask import request

import errors
from timeutil import is_iso

ROLES = {
    "PlatformAdmin",
    "StaffAttorney",
    "Commissioner",
    "ComplianceMonitor",
    "FundAdministrator",
    "DisbursementOfficer",
    "CompanyRepresentative",
    "Claimant",
}
ALL_ROLES = sorted(ROLES)


def context():
    """Cascade tier 1: X-User-ID and X-User-Role present and non-empty."""
    user_id = (request.headers.get("X-User-ID") or "").strip()
    role = (request.headers.get("X-User-Role") or "").strip()
    if not user_id or not role:
        errors.fail(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-ID and X-User-Role headers must be present and non-empty",
        )
    return user_id, role


def require_role(role, allowed):
    """Cascade tier 2 (endpoint scope)."""
    if role not in ROLES or role not in allowed:
        errors.fail(
            "ERR_INSUFFICIENT_PERMISSIONS",
            "Role '{}' is not permitted for this endpoint".format(role),
        )


def require_target_role(role, target, target_roles):
    """Cascade tier 2 (target scope on transition endpoints)."""
    if target in target_roles and role not in target_roles[target]:
        errors.fail(
            "ERR_INSUFFICIENT_PERMISSIONS",
            "Role '{}' is not permitted for target_state '{}'".format(role, target),
        )


def json_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        errors.fail("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return body


def need_str(body, field):
    value = body.get(field)
    if not isinstance(value, str) or not value.strip():
        errors.fail(
            "ERR_INVALID_REQUEST",
            "Field '{}' is required and must be a non-empty string".format(field),
        )
    return value


def need_int(body, field, minimum=None, maximum=None, choices=None):
    value = body.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        errors.fail(
            "ERR_INVALID_REQUEST",
            "Field '{}' is required and must be an integer".format(field),
        )
    if choices is not None and value not in choices:
        errors.fail(
            "ERR_INVALID_REQUEST",
            "Field '{}' must be one of {}".format(field, sorted(choices)),
        )
    if minimum is not None and value < minimum:
        errors.fail(
            "ERR_INVALID_REQUEST",
            "Field '{}' must be >= {}".format(field, minimum),
        )
    if maximum is not None and value > maximum:
        errors.fail(
            "ERR_INVALID_REQUEST",
            "Field '{}' must be <= {}".format(field, maximum),
        )
    return value


def need_enum(body, field, allowed):
    value = body.get(field)
    if not isinstance(value, str) or value not in allowed:
        errors.fail(
            "ERR_INVALID_REQUEST",
            "Field '{}' must be one of {}".format(field, sorted(allowed)),
        )
    return value


def need_datetime(body, field):
    value = body.get(field)
    if not isinstance(value, str) or not is_iso(value):
        errors.fail(
            "ERR_INVALID_REQUEST",
            "Field '{}' is required and must be an ISO8601 timestamp".format(field),
        )
    return value


def need_str_list(body, field):
    value = body.get(field)
    if (
        not isinstance(value, list)
        or len(value) == 0
        or any(not isinstance(item, str) or not item.strip() for item in value)
    ):
        errors.fail(
            "ERR_INVALID_REQUEST",
            "Field '{}' must be a non-empty array of non-empty strings".format(field),
        )
    return value


def _parse_int_arg(raw, field):
    if raw is None:
        return None
    if isinstance(raw, str) and raw.strip().lstrip("-").isdigit():
        return int(raw.strip())
    errors.fail(
        "ERR_INVALID_REQUEST",
        "Query parameter '{}' must be an integer".format(field),
    )


def page_params():
    """Pagination: limit default 10, min 1, max 100; offset default 0, min 0."""
    limit = _parse_int_arg(request.args.get("limit"), "limit")
    offset = _parse_int_arg(request.args.get("offset"), "offset")
    limit = 10 if limit is None else limit
    offset = 0 if offset is None else offset
    if limit < 1 or limit > 100:
        errors.fail(
            "ERR_INVALID_REQUEST",
            "Query parameter 'limit' must be between 1 and 100",
        )
    if offset < 0:
        errors.fail(
            "ERR_INVALID_REQUEST",
            "Query parameter 'offset' must be >= 0",
        )
    return limit, offset


def get_or_404(mapping, key, error_id, label):
    """Cascade tier 3: path/body identifiers resolve, left to right."""
    entity = mapping.get(key)
    if entity is None:
        errors.fail(error_id, "{} '{}' does not exist".format(label, key))
    return entity

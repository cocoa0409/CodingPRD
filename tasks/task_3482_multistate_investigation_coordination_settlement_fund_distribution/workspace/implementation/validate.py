"""Body-schema validation (rung 3), pagination parsing, path-id resolution
(rung 4). First failure wins per PRD §2.8."""
import json

from flask import request

import db
import errors


# ---------------------------------------------------------------------------
# Body schema (rung 3)
# ---------------------------------------------------------------------------
def body_json():
    """Parse the request body. Empty body -> {}; non-JSON or non-object -> 400."""
    raw = request.get_data(cache=True)
    if raw is None or len(raw) == 0:
        return {}
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise errors.invalid_request("Request body is not valid JSON")
    if not isinstance(value, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    return value


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def req_str(body, field):
    if field not in body or not isinstance(body[field], str):
        raise errors.invalid_request(f"Field '{field}' is required and must be a string")
    return body[field]


def opt_str(body, field):
    if field not in body or body[field] is None:
        return None
    if not isinstance(body[field], str):
        raise errors.invalid_request(f"Field '{field}' must be a string")
    return body[field]


def req_int(body, field):
    if field not in body or not is_int(body[field]):
        raise errors.invalid_request(f"Field '{field}' is required and must be an integer")
    return body[field]


def opt_int(body, field):
    if field not in body or body[field] is None:
        return None
    if not is_int(body[field]):
        raise errors.invalid_request(f"Field '{field}' must be an integer")
    return body[field]


def req_enum(body, field, allowed):
    if field not in body or not isinstance(body[field], str) or body[field] not in allowed:
        raise errors.invalid_request(
            f"Field '{field}' is required and must be one of {sorted(allowed)}"
        )
    return body[field]


def req_str_list(body, field):
    if field not in body or not isinstance(body[field], list):
        raise errors.invalid_request(f"Field '{field}' is required and must be an array")
    for item in body[field]:
        if not isinstance(item, str):
            raise errors.invalid_request(f"Field '{field}' must contain only strings")
    return body[field]


def opt_bps_map(body, field):
    """Optional map state_code -> integer basis points (type-checked if present)."""
    if field not in body or body[field] is None:
        return None
    value = body[field]
    if not isinstance(value, dict):
        raise errors.invalid_request(f"Field '{field}' must be an object")
    for key, val in value.items():
        if not isinstance(key, str) or not is_int(val):
            raise errors.invalid_request(
                f"Field '{field}' must map state codes to integer basis points"
            )
    return value


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3): limit default 10, min 1, max 100; offset default 0.
# Out-of-range integers are clamped; non-integers are rejected.
# ---------------------------------------------------------------------------
def pagination_params():
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    try:
        limit = int(limit_raw) if limit_raw is not None else 10
    except ValueError:
        raise errors.invalid_request("Query parameter 'limit' must be an integer")
    try:
        offset = int(offset_raw) if offset_raw is not None else 0
    except ValueError:
        raise errors.invalid_request("Query parameter 'offset' must be an integer")
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def paginate(entities, limit, offset):
    """Sort by created_at ASC (ties: insertion order), then slice."""
    ordered = sorted(entities, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(ordered)
    return ordered[offset:offset + limit], total


# ---------------------------------------------------------------------------
# Path-id resolution (rung 4)
# ---------------------------------------------------------------------------
def get_office_or_404(office_id):
    ent = db.offices.get(office_id)
    if ent is None:
        raise errors.office_not_found()
    return ent


def get_investigation_or_404(investigation_id):
    ent = db.investigations.get(investigation_id)
    if ent is None:
        raise errors.investigation_not_found()
    return ent


def get_participation_or_404(participation_id):
    ent = db.participations.get(participation_id)
    if ent is None:
        raise errors.participation_not_found()
    return ent


def get_response_or_404(response_id):
    ent = db.responses.get(response_id)
    if ent is None:
        raise errors.response_not_found()
    return ent


def get_settlement_or_404(settlement_id):
    ent = db.settlements.get(settlement_id)
    if ent is None:
        raise errors.settlement_not_found()
    return ent


def get_line_or_404(line_id):
    ent = db.lines.get(line_id)
    if ent is None:
        raise errors.line_not_found()
    return ent


def get_disbursement_or_404(disbursement_id):
    ent = db.disbursements.get(disbursement_id)
    if ent is None:
        raise errors.disbursement_not_found()
    return ent


def get_claimant_or_404(claimant_id):
    ent = db.claimants.get(claimant_id)
    if ent is None:
        raise errors.claimant_not_found()
    return ent


def get_period_or_404(period_id):
    ent = db.periods.get(period_id)
    if ent is None:
        raise errors.period_not_found()
    return ent

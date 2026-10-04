"""Shared route plumbing: body parsing, lookups, existence ordering, OCC.

Existence checks are performed strictly left to right across the canonical
resource hierarchy — agency, then agent, then agreement, then policy, then
claim — and the failure names the *first* unresolved step (PRD §2.6).
"""

from flask import request

import db
from errors import (
    ApiError, ERR_AGENCY_NOT_FOUND, ERR_AGENT_NOT_FOUND, ERR_AGREEMENT_NOT_FOUND,
    ERR_CLAIM_NOT_FOUND, ERR_POLICY_NOT_FOUND, ERR_STAFF_NOT_FOUND, ERR_STALE_VERSION,
    ERR_UNAUTHORIZED,
)


def body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def want(data, key, default=None):
    value = data.get(key, default)
    return value


def agency_or_404(agency_id):
    record = db.agency_rows().get(agency_id)
    if record is None:
        raise ApiError(ERR_AGENCY_NOT_FOUND)
    return record


def agent_or_404(agent_id):
    record = db.agent_rows().get(agent_id)
    if record is None:
        raise ApiError(ERR_AGENT_NOT_FOUND)
    return record


def agreement_or_404(agreement_id):
    record = db.agreement_rows().get(agreement_id)
    if record is None:
        raise ApiError(ERR_AGREEMENT_NOT_FOUND)
    return record


def policy_or_404(policy_id):
    record = db.policy_rows().get(policy_id)
    if record is None:
        raise ApiError(ERR_POLICY_NOT_FOUND)
    return record


def claim_or_404(claim_id):
    record = db.claim_rows().get(claim_id)
    if record is None:
        raise ApiError(ERR_CLAIM_NOT_FOUND)
    return record


def staff_or_404(staff_id):
    record = db.staff_rows().get(staff_id)
    if record is None:
        raise ApiError(ERR_STAFF_NOT_FOUND)
    return record


def campaign_or_404(agency, campaign_id):
    record = db.campaign_rows().get(campaign_id)
    if record is None or record["agency_id"] != agency["id"]:
        raise ApiError("ERR_CAMPAIGN_NOT_FOUND", "No campaign matches the id under this agency.", 404)
    return record


def transfer_or_404(transfer_id):
    record = db.transfer_rows().get(transfer_id)
    if record is None:
        raise ApiError("ERR_BOOK_TRANSFER_NOT_FOUND",
                       "No book transfer matches the id in the path.", 404)
    return record


def application_or_404(application_id):
    record = db.application_rows().get(application_id)
    if record is None:
        raise ApiError("ERR_APPLICATION_NOT_FOUND",
                       "No appointment application matches the id in the path.", 404)
    return record


def principal_owns(role, user_id, agency_id):
    """An AgencyPrincipal's X-User-ID is an Agency id; it may only touch
    agency-scoped resources bearing that id (PRD §2.1)."""
    if role == "AgencyPrincipal" and str(user_id) != str(agency_id):
        raise ApiError(ERR_UNAUTHORIZED)


def paged(request, rows, view):
    """Slice a sorted list for a list endpoint and attach the pagination meta."""
    import middleware as _mw
    from response import array_response
    window, meta = _mw.paginate(request, len(rows))
    return array_response([view(r) for r in rows[window]], 200, meta)


def check_version(parent, supplied, field_name="expected_version"):
    """Optimistic concurrency (PRD §2.9) — see occ.check."""
    import occ
    occ.check(parent, supplied, field_name)


def terminal_guard(record, terminal_states):
    if record["status"] in terminal_states:
        raise ApiError("ERR_ALREADY_TERMINAL")


def require_state(record, expected):
    if record["status"] != expected:
        raise ApiError("ERR_INVALID_STATE")
"""Noncompliance records and the escalation ladder (PRD §3.3)."""
from flask import Blueprint, request

import store
from authz import require_ownership, require_roles
from cascades import maybe_auto_suspend_for_escalation
from envelope import get_body, pagination_params, sort_and_page, success_list, success_object
from errors import (
    raise_err,
    ERR_INVALID_STATE,
    ERR_NONCOMPLIANCE_RECORD_NOT_FOUND,
    ERR_SHIFT_WINDOW_MISMATCH,
    ERR_SHIFT_WINDOW_NOT_FOUND,
)
from guards import entity_or_404, establishment_or_404, require_not_withdrawn
from errors import ERR_INSPECTOR_NOT_FOUND
from store import insert, stamp_new, touch
from validate import (
    REGULATION_FAMILIES,
    not_future,
    optional_string,
    require_enum,
    require_string,
    require_timestamp,
)

bp = Blueprint("noncompliance_records", __name__)

READ_ROLES = ("EstablishmentManager", "Inspector", "SupervisoryReviewer", "DistrictManager", "ProgramAdministrator")


def _nr_or_404(nr_id):
    return entity_or_404("noncompliance_records", nr_id, ERR_NONCOMPLIANCE_RECORD_NOT_FOUND)


@bp.post("/inspection/noncompliance-records")
def create_nr():
    user_id, _ = require_roles("Inspector")
    body = get_body()
    establishment_id = require_string(body, "establishment_id")
    issued_by_inspector_id = require_string(body, "issued_by_inspector_id")
    shift_window_id = optional_string(body, "shift_window_id")
    regulation_family = require_enum(body, "regulation_family", REGULATION_FAMILIES)
    description = require_string(body, "description")
    observed_at = require_timestamp(body, "observed_at")

    # Ownership pinning (tier 2): the issuer is the caller.
    require_ownership(user_id, issued_by_inspector_id)
    # Tier 3: body-supplied FK references.
    establishment = establishment_or_404(establishment_id)
    entity_or_404("inspectors", issued_by_inspector_id, ERR_INSPECTOR_NOT_FOUND)
    window = None
    if shift_window_id is not None:
        window = entity_or_404("shift_windows", shift_window_id, ERR_SHIFT_WINDOW_NOT_FOUND)
    # Tier 5: establishment gates.
    require_not_withdrawn(establishment)
    # Tier 7: observation must not be after the logical clock.
    not_future(observed_at, "observed_at")
    # Tier 9: the optional shift link must belong to the same establishment.
    if window is not None and window["establishment_id"] != establishment_id:
        raise_err(ERR_SHIFT_WINDOW_MISMATCH, "shift window belongs to a different establishment")

    nr = {
        "establishment_id": establishment_id,
        "issued_by_inspector_id": issued_by_inspector_id,
        "shift_window_id": shift_window_id,
        "regulation_family": regulation_family,
        "description": description,
        "observed_at": observed_at,
        "issued_at": store.clock_now(),
        "status": "OPEN",
        "status_before_appeal": None,
        "response_text": None,
    }
    stamp_new(nr)
    insert("noncompliance_records", nr)
    return success_object(nr, status=201)


@bp.get("/inspection/noncompliance-records")
def list_nrs():
    require_roles(*READ_ROLES)
    rows = store.all_of("noncompliance_records")
    for param in ("establishment_id", "issued_by_inspector_id", "shift_window_id", "status", "regulation_family"):
        value = request.args.get(param)
        if value is not None:
            rows = [n for n in rows if n.get(param) == value]
    limit, offset = pagination_params()
    page, total = sort_and_page(rows, limit, offset)
    return success_list(page, limit, offset, total)


@bp.get("/inspection/noncompliance-records/<nr_id>")
def get_nr(nr_id):
    require_roles(*READ_ROLES)
    return success_object(_nr_or_404(nr_id))


@bp.post("/inspection/noncompliance-records/<nr_id>/respond")
def respond(nr_id):
    user_id, _ = require_roles("EstablishmentManager")
    nr = _nr_or_404(nr_id)
    require_ownership(user_id, nr["establishment_id"])
    require_not_withdrawn(establishment_or_404(nr["establishment_id"]))
    if nr["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE, "respond requires status OPEN")
    body = get_body()
    response_text = require_string(body, "response_text")
    nr["status"] = "RESPONSE_SUBMITTED"
    nr["response_text"] = response_text
    touch(nr)
    return success_object(nr)


@bp.post("/inspection/noncompliance-records/<nr_id>/verify-response")
def verify_response(nr_id):
    require_roles("Inspector")
    nr = _nr_or_404(nr_id)
    require_not_withdrawn(establishment_or_404(nr["establishment_id"]))
    if nr["status"] not in ("OPEN", "RESPONSE_SUBMITTED"):
        raise_err(ERR_INVALID_STATE, "verify-response requires status OPEN or RESPONSE_SUBMITTED")
    body = get_body()
    outcome = require_enum(body, "outcome", ("VERIFY", "ESCALATE"))

    if outcome == "VERIFY":
        nr["status"] = "VERIFIED"
        touch(nr)
    else:
        nr["status"] = "ESCALATED"
        touch(nr)
        # Escalation ladder: threshold re-evaluated at the moment of the
        # transition with this record counted in its ESCALATED state.
        maybe_auto_suspend_for_escalation(nr)
    return success_object(nr)

"""Enforcement actions: proposal, activation, abatement (PRD §3.4)."""
from flask import Blueprint, request

import calc
import store
from authz import require_roles
from cascades import apply_activation, apply_lift
from envelope import get_body, pagination_params, sort_and_page, success_list, success_object
from errors import (
    raise_err,
    ERR_ENFORCEMENT_ACTION_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_STALE_ESTABLISHMENT_VERSION,
)
from guards import establishment_or_404, entity_or_404, require_granted, require_not_withdrawn
from store import insert, stamp_new, touch
from validate import ACTION_TYPES, BASES, REGULATION_FAMILIES, optional_string, require_enum, require_int, require_string

bp = Blueprint("enforcement_actions", __name__)

READ_ROLES = ("EstablishmentManager", "Inspector", "SupervisoryReviewer", "DistrictManager", "ProgramAdministrator")


def _action_or_404(action_id):
    return entity_or_404("enforcement_actions", action_id, ERR_ENFORCEMENT_ACTION_NOT_FOUND)


@bp.post("/inspection/establishments/<est_id>/enforcement-actions")
def create_enforcement_action(est_id):
    require_roles("DistrictManager")
    establishment = establishment_or_404(est_id)
    body = get_body()
    action_type = require_enum(body, "action_type", ACTION_TYPES)
    basis = require_enum(body, "basis", BASES)
    regulation_family = optional_string(body, "regulation_family")
    if regulation_family is not None and regulation_family not in REGULATION_FAMILIES:
        raise_err(ERR_INVALID_REQUEST, "regulation_family is not a declared family")
    if basis == "NR_LINKAGE" and regulation_family is None:
        raise_err(ERR_INVALID_REQUEST, "regulation_family is required when basis is NR_LINKAGE")
    expected_version = require_int(body, "expected_establishment_version")

    # Tier 4: optimistic concurrency on the establishment (PRD §2.8).
    if expected_version != establishment["version"]:
        raise_err(ERR_STALE_ESTABLISHMENT_VERSION, "expected_establishment_version is stale")
    # Tier 5: withdrawal freeze.
    require_not_withdrawn(establishment)
    # Tier 8: basis eligibility, validated at creation (PRD §3.4).
    ok, err = calc.enforcement_eligible(action_type, basis, regulation_family, est_id, establishment)
    if not ok:
        raise_err(err, "enforcement basis eligibility is not met")

    action = {
        "establishment_id": est_id,
        "action_type": action_type,
        "basis": basis,
        "regulation_family": regulation_family,
        "status": "PROPOSED",
        "auto_created": False,
        "effective_at": None,
        "abatement_evidence": None,
    }
    stamp_new(action)
    insert("enforcement_actions", action)
    # Creation increments the establishment's version (PRD §3.4).
    touch(establishment)
    return success_object(action, status=201)


@bp.get("/inspection/establishments/<est_id>/enforcement-actions")
def list_enforcement_actions(est_id):
    require_roles(*READ_ROLES)
    establishment_or_404(est_id)
    rows = [a for a in store.all_of("enforcement_actions") if a["establishment_id"] == est_id]
    status_filter = request.args.get("status")
    if status_filter is not None:
        rows = [a for a in rows if a["status"] == status_filter]
    type_filter = request.args.get("action_type")
    if type_filter is not None:
        rows = [a for a in rows if a["action_type"] == type_filter]
    limit, offset = pagination_params()
    page, total = sort_and_page(rows, limit, offset)
    return success_list(page, limit, offset, total)


@bp.post("/inspection/enforcement-actions/<action_id>/activate")
def activate(action_id):
    require_roles("DistrictManager")
    action = _action_or_404(action_id)
    establishment = establishment_or_404(action["establishment_id"])
    if action["status"] != "PROPOSED":
        raise_err(ERR_INVALID_STATE, "activate requires status PROPOSED")
    # Tier 5 gates (PRD §2.5): withdrawal freeze; suspension requires a grant.
    require_not_withdrawn(establishment)
    if action["action_type"] == "SUSPENSION":
        require_granted(establishment)
    # Tier 8: basis eligibility is re-evaluated at activation time.
    ok, err = calc.enforcement_eligible(
        action["action_type"], action["basis"], action["regulation_family"], establishment["id"], establishment
    )
    if not ok:
        raise_err(err, "enforcement basis eligibility is no longer met")

    action["status"] = "IN_EFFECT"
    action["effective_at"] = store.clock_now()
    touch(action)
    apply_activation(action, establishment)
    return success_object(action)


@bp.post("/inspection/enforcement-actions/<action_id>/lift")
def lift(action_id):
    require_roles("DistrictManager")
    action = _action_or_404(action_id)
    establishment = establishment_or_404(action["establishment_id"])
    if action["status"] != "IN_EFFECT":
        raise_err(ERR_INVALID_STATE, "lift requires status IN_EFFECT")
    body = get_body()
    abatement_evidence = require_string(body, "abatement_evidence", min_len=20)

    action["abatement_evidence"] = abatement_evidence
    action["status"] = "LIFTED"
    touch(action)
    apply_lift(action, establishment)
    return success_object(action)

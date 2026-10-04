"""Substantive change requests: draft, list, submit, decide (PRD §3.9)."""
from flask import Blueprint, request

import constants as C
from auth import authenticate, check_liaison_chain, require_liaison_owns, require_role
from calculations import annual_dues_cents, outstanding_dues_cents
from db import STORE
from errors import (ERR_DUES_ARREARS, ERR_INSTITUTION_NOT_ACCREDITED,
                    ERR_INSTITUTION_NOT_FOUND, ERR_INVALID_STATE,
                    ERR_SANCTION_BLOCKS_CHANGE, ERR_SUBSTANTIVE_CHANGE_NOT_FOUND,
                    ERR_VALIDATION, raise_err)
from helpers import (fetch_or_404, get_body, new_entity, opt_string, paginate,
                     req_enum, req_string, serialize, touch)
from response import success_list, success_object

bp = Blueprint("changes", __name__)


@bp.post("/accreditation/institutions/<inst_id>/substantive-change-requests")
def create_change(inst_id):
    actor = authenticate()
    require_role(actor, ["InstitutionLiaison"])
    require_liaison_owns(actor, inst_id)
    inst = fetch_or_404(STORE.institutions, inst_id, ERR_INSTITUTION_NOT_FOUND)
    body = get_body()
    change_type = req_enum(body, "change_type", C.CHANGE_TYPES)
    # The type's detail field is required exactly when the type matches (§3.9).
    program_level = None
    location_state = None
    ownership = None
    if change_type == "PROGRAM_LEVEL":
        program_level = req_enum(body, "requested_program_level", C.DEGREE_LEVELS)
    elif change_type == "NEW_LOCATION":
        location_state = req_string(body, "new_location_state")
    elif change_type == "OWNERSHIP_CHANGE":
        ownership = req_string(body, "ownership_details")
    if inst["accreditation_status"] != "ACCREDITED":
        raise_err(ERR_INSTITUTION_NOT_ACCREDITED,
                  "Substantive-change drafting requires an ACCREDITED institution")
    req = new_entity({
        "institution_id": inst_id,
        "change_type": change_type,
        "requested_program_level": program_level,
        "new_location_state": location_state,
        "ownership_details": ownership,
        "status": "DRAFT",
        "decision_notes": None,
    })
    STORE.substantive_change_requests[req["id"]] = req
    return success_object(serialize(req), code=201)


@bp.get("/accreditation/institutions/<inst_id>/substantive-change-requests")
def list_changes(inst_id):
    actor = authenticate()
    if actor.role == "InstitutionLiaison":
        check_liaison_chain(actor, inst_id)
    fetch_or_404(STORE.institutions, inst_id, ERR_INSTITUTION_NOT_FOUND)
    items = [r for r in STORE.substantive_change_requests.values()
             if r["institution_id"] == inst_id]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, total, limit, offset = paginate(items)
    return success_list(page, total, limit, offset)


@bp.post("/accreditation/substantive-change-requests/<req_id>/submit")
def submit_change(req_id):
    actor = authenticate()
    require_role(actor, ["InstitutionLiaison"])
    req = fetch_or_404(STORE.substantive_change_requests, req_id, ERR_SUBSTANTIVE_CHANGE_NOT_FOUND)
    require_liaison_owns(actor, req["institution_id"])
    if req["status"] not in ("DRAFT", "DEFERRED"):
        raise_err(ERR_INVALID_STATE, "Only a DRAFT or DEFERRED request can be submitted")
    inst = STORE.institutions.get(req["institution_id"])
    # Pinned gate order (§3.9): sanction gate first, then the dues gate.
    if inst["sanction_status"] not in ("NONE", "NOTICE"):
        raise_err(ERR_SANCTION_BLOCKS_CHANGE,
                  "Institution sanction status blocks substantive-change submission")
    if outstanding_dues_cents(inst) > 0:
        raise_err(ERR_DUES_ARREARS, "Outstanding dues arrears block submission")
    req["status"] = "SUBMITTED"
    touch(req)
    return success_object(serialize(req))


@bp.post("/accreditation/substantive-change-requests/<req_id>/decide")
def decide_change(req_id):
    actor = authenticate()
    require_role(actor, ["CommissionStaff"])
    req = fetch_or_404(STORE.substantive_change_requests, req_id, ERR_SUBSTANTIVE_CHANGE_NOT_FOUND)
    body = get_body()
    decision = req_enum(body, "decision", C.CHANGE_DECISIONS)
    notes = opt_string(body, "decision_notes")
    if req["status"] != "SUBMITTED":
        raise_err(ERR_INVALID_STATE, "Only a SUBMITTED request can be decided")
    inst = STORE.institutions.get(req["institution_id"])
    if decision == "APPROVE":
        # The sanction gate is re-checked at decision time (§3.9).
        if inst["sanction_status"] not in ("NONE", "NOTICE"):
            raise_err(ERR_SANCTION_BLOCKS_CHANGE,
                      "Institution sanction status blocks approval")
        if req["change_type"] == "NEW_LOCATION":
            inst["locations_count"] += 1
        elif req["change_type"] == "PROGRAM_LEVEL":
            inst["degree_levels_offered"] = inst["degree_levels_offered"] + [req["requested_program_level"]]
            inst["current_annual_dues_cents"] = annual_dues_cents(
                inst["fte_enrollment"], inst["degree_levels_offered"])
        elif req["change_type"] == "DISTANCE_DELIVERY":
            inst["distance_delivery_approved"] = True
        # OWNERSHIP_CHANGE mutates no institutional field beyond status (§3.9).
        touch(inst)
        req["status"] = "APPROVED"
    elif decision == "DENY":
        req["status"] = "DENIED"
    else:  # DEFER
        req["status"] = "DEFERRED"
    if notes is not None:
        req["decision_notes"] = notes
    touch(req)
    return success_object(serialize(req))

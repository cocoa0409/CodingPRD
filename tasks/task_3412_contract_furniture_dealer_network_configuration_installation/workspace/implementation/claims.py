# Warranty claims routes (PRD 3.8; scaffold Tables 2/5).
from datetime import timedelta

from flask import Blueprint, request

import authz
import calc
import clock
import constants
import envelope
import errors
import serialize
import state
import validate
from dealers import _new_entity

bp = Blueprint("claims", __name__)


def _load_claim(claim_id):
    claim = state.claims.get(claim_id)
    if claim is None:
        errors.not_found("ERR_CLAIM_NOT_FOUND", "No warranty claim with the given id")
    return claim


def _claim_visible_to(claim, role, user_id):
    if role == "ManufacturerAdmin":
        return True
    order = state.orders.get(claim["project_order_id"])
    if order is None:
        return False
    return authz.order_visible_to(order, role, user_id)


@bp.post("/warranty-claims")
def create_claim():
    role, user_id = authz.authenticate()
    authz.require_roles(role, ("DealerRep",))
    body = validate.body_json(request)
    # Step 3: body FKs resolve in the PRD 2.9 listed order
    # (installation_phase_id before project_order_id).
    phase_id = body.get("installation_phase_id")
    if isinstance(phase_id, str) and phase_id not in state.phases:
        errors.not_found("ERR_PHASE_NOT_FOUND", "No installation phase with the given id")
    order_id = body.get("project_order_id")
    if isinstance(order_id, str) and order_id not in state.orders:
        errors.not_found("ERR_ORDER_NOT_FOUND", "No project order with the given id")
    order = state.orders.get(order_id) if isinstance(order_id, str) else None
    # Step 4: ownership of the named order.
    if order is not None:
        authz.check_order_ownership(order, role, user_id)
    # Step 5: body shape, including the conditional part_number requirement.
    order_id = validate.req_str(body, "project_order_id")
    phase_id = validate.req_str(body, "installation_phase_id")
    claim_type = validate.req_enum(body, "claim_type", constants.CLAIM_TYPES)
    description = validate.req_str(body, "description")
    part_number = None
    if claim_type == "PARTS":
        part_number = validate.req_str(body, "part_number")
        if part_number not in constants.CATALOG_PART_NUMBERS:
            errors.validation("part_number must be a catalog part number")
    order = state.orders[order_id]
    phase = state.phases[phase_id]
    # Step 8: the phase must belong to the order and be COMPLETE (PRD 3.8).
    if phase["project_order_id"] != order["id"] or phase["install_status"] != "COMPLETE":
        errors.invalid_state(
            "Claims require a phase of the order whose install_status is COMPLETE")
    filed = clock.today()
    complete_date = calc._parse_date(phase["actual_install_complete_date"])
    # Gate 26: warranty windows, inclusive on the last eligible day.
    horizon = (constants.PARTS_WARRANTY_DAYS if claim_type == "PARTS"
               else constants.LABOR_WARRANTY_DAYS)
    if filed > complete_date + timedelta(days=horizon):
        errors.err("ERR_WARRANTY_EXPIRED", 422,
                   "Claim filed after the warranty window")
    # Gate 27: parts-support horizon for DISCONTINUED families (PARTS only).
    if claim_type == "PARTS":
        category = constants.PART_CATEGORY[part_number]
        fam = calc.family_for_category(category)
        if fam is not None and fam["lifecycle_status"] == "DISCONTINUED":
            if filed > calc._parse_date(fam["parts_support_until"]):
                errors.err("ERR_PARTS_SUPPORT_EXPIRED", 422,
                           "Claim filed after the family's parts_support_until")
    claim = _new_entity({
        "project_order_id": order["id"],
        "installation_phase_id": phase["id"],
        "punch_ticket_id": None,
        "claim_type": claim_type,
        "part_number": part_number,
        "description": description,
        "status": "SUBMITTED",
        "filed_date": filed.isoformat(),
        "review_note": None,
        "reviewed_at": None,
    })
    state.claims[claim["id"]] = claim
    return envelope.success_object(serialize.claim(claim), status=201)


@bp.get("/warranty-claims/<claimId>")
def get_claim(claimId):
    role, user_id = authz.authenticate()
    authz.require_roles(role, ("DealerRep", "ManufacturerAdmin", "EndUserRep"))
    claim = _load_claim(claimId)
    if not _claim_visible_to(claim, role, user_id):
        errors.forbidden_ownership()
    return envelope.success_object(serialize.claim(claim))


@bp.get("/warranty-claims")
def list_claims():
    role, user_id = authz.authenticate()
    authz.require_roles(role, ("DealerRep", "ManufacturerAdmin", "EndUserRep"))
    items = [c for c in state.claims.values()
             if _claim_visible_to(c, role, user_id)]
    for param in ("project_order_id", "installation_phase_id", "punch_ticket_id"):
        value = request.args.get(param)
        if value is not None:
            items = [c for c in items if c[param] == value]
    page, total, limit, offset = envelope.paginate(items, request.args)
    return envelope.success_list(
        [serialize.claim(c) for c in page], total, limit, offset)


@bp.post("/warranty-claims/<claimId>/review")
def review_claim(claimId):
    role, _uid = authz.authenticate()
    authz.require_roles(role, ("ManufacturerAdmin",))
    claim = _load_claim(claimId)
    body = validate.body_json(request)
    decision = validate.req_enum(body, "decision", constants.REVIEW_DECISIONS)
    review_note = validate.opt_str(body, "review_note")
    if claim["status"] != "SUBMITTED":
        errors.invalid_state("Only a SUBMITTED claim can be reviewed")
    claim["status"] = "APPROVED" if decision == "APPROVE" else "DENIED"
    claim["review_note"] = review_note
    claim["reviewed_at"] = clock.now_iso()
    state.touch(claim)
    return envelope.success_object(serialize.claim(claim))

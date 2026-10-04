# Volume agreements routes (PRD 3.2; scaffold Tables 2/5).
from flask import Blueprint, request

import authz
import calc
import clock
import envelope
import errors
import serialize
import state
import validate
from dealers import _new_entity

bp = Blueprint("agreements", __name__)


def _load_agreement(agreement_id):
    agreement = state.agreements.get(agreement_id)
    if agreement is None:
        errors.not_found("ERR_AGREEMENT_NOT_FOUND", "No volume agreement with the given id")
    calc.maybe_expire_agreement(agreement)
    return agreement


@bp.post("/volume-agreements")
def create_agreement():
    role, _uid = authz.authenticate()
    authz.require_roles(role, ("ManufacturerAdmin",))
    body = validate.body_json(request)
    # Step 3: body foreign keys resolve (a missing FK is caught by shape at step 5).
    end_user_id = body.get("end_user_id")
    if isinstance(end_user_id, str) and end_user_id not in state.end_users:
        errors.not_found("ERR_END_USER_NOT_FOUND", "No end user with the given id")
    # Step 5: body shape.
    end_user_id = validate.req_str(body, "end_user_id")
    effective_start = validate.req_date(body, "effective_start")
    effective_end = validate.req_date(body, "effective_end")
    tier1 = validate.fraction_0_to_1(body, "tier1_discount_pct")
    tier2 = validate.fraction_0_to_1(body, "tier2_discount_pct")
    tier3 = validate.fraction_0_to_1(body, "tier3_discount_pct")
    # Step 6: effective_end strictly after effective_start.
    if effective_end <= effective_start:
        errors.date_window("effective_end must be strictly after effective_start")
    agreement = _new_entity({
        "end_user_id": end_user_id,
        "effective_start": effective_start.isoformat(),
        "effective_end": effective_end.isoformat(),
        "tier1_discount_pct": tier1,
        "tier2_discount_pct": tier2,
        "tier3_discount_pct": tier3,
        "status": "DRAFT",
        "activated_at": None,
    })
    state.agreements[agreement["id"]] = agreement
    return envelope.success_object(serialize.agreement(agreement), status=201)


@bp.get("/volume-agreements/<agreementId>")
def get_agreement(agreementId):
    role, user_id = authz.authenticate()
    authz.require_roles(role, ("ManufacturerAdmin", "EndUserRep"))
    agreement = _load_agreement(agreementId)
    if role == "EndUserRep" and agreement["end_user_id"] != user_id:
        errors.forbidden_ownership()
    return envelope.success_object(serialize.agreement(agreement))


@bp.get("/volume-agreements")
def list_agreements():
    role, user_id = authz.authenticate()
    authz.require_roles(role, ("ManufacturerAdmin", "EndUserRep"))
    items = []
    for agreement in state.agreements.values():
        calc.maybe_expire_agreement(agreement)
        if role == "EndUserRep" and agreement["end_user_id"] != user_id:
            continue
        items.append(agreement)
    end_user_filter = request.args.get("end_user_id")
    if end_user_filter is not None:
        items = [a for a in items if a["end_user_id"] == end_user_filter]
    status_filter = request.args.get("status")
    if status_filter is not None:
        items = [a for a in items if a["status"] == status_filter]
    page, total, limit, offset = envelope.paginate(items, request.args)
    return envelope.success_list(
        [serialize.agreement(a) for a in page], total, limit, offset)


@bp.post("/volume-agreements/<agreementId>/activate")
def activate_agreement(agreementId):
    role, _uid = authz.authenticate()
    authz.require_roles(role, ("ManufacturerAdmin",))
    agreement = _load_agreement(agreementId)
    if agreement["status"] != "DRAFT":
        errors.invalid_state("Only a DRAFT agreement can be activated")
    if clock.today() > calc._parse_date(agreement["effective_end"]):
        errors.invalid_state(
            "Cannot activate an agreement whose effective_end has passed")
    agreement["status"] = "ACTIVE"
    agreement["activated_at"] = clock.now_iso()
    state.touch(agreement)
    return envelope.success_object(serialize.agreement(agreement))

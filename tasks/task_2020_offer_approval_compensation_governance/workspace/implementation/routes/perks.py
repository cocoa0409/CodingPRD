"""PerkPackage endpoints."""

from flask import Blueprint, request

import db
from errors import (
    raise_err, ERR_OFFER_NOT_FOUND, ERR_PERK_NOT_FOUND, ERR_PERK_STATE_LOCKED,
    ERR_SIGNON_EXCEEDS_HARD_CAP, ERR_INVALID_REQUEST, ERR_NOT_RESOURCE_OWNER,
)
from middleware import (
    get_actor, require_role, get_json_body, validate_fields, req_enum, req_int,
)
from response import success
from services import calc
from services import offer_ops

bp = Blueprint("perks", __name__)

READ_ROLES = ["Recruiter", "HiringManager", "CompAnalyst", "DepartmentDirector",
              "VPPeople", "HRAdmin", "Candidate"]
QUOTE_ROLES = ["Recruiter", "HiringManager", "HRAdmin", "VPPeople"]


@bp.route("/api/offers/<offer_id>/perks", methods=["POST"])
def create(offer_id):
    uid, role = get_actor()
    body = get_json_body()
    validate_fields(body, ["kind", "amount_cents", "clawback_months", "clawback_variant"], [])
    kind = req_enum(body, "kind", ["SIGN_ON", "RELOCATION"])
    amount = req_int(body, "amount_cents", min_value=1)
    months = req_int(body, "clawback_months", min_value=1)
    variant = req_enum(body, "clawback_variant", ["FULL_CLIFF", "PRORATED_MONTHLY"])
    require_role(role, ["Recruiter", "HiringManager"])
    offer = db.offers.get(offer_id)
    if offer is None:
        raise_err(ERR_OFFER_NOT_FOUND, "Offer not found")
    if offer["status"] not in ("DRAFT", "RETURNED"):
        raise_err(ERR_PERK_STATE_LOCKED, "Perks may only be added while offer is DRAFT or RETURNED")
    if kind == "SIGN_ON" and amount > calc.SIGNON_HARD_CAP_CENTS:
        raise_err(ERR_SIGNON_EXCEEDS_HARD_CAP, "Single SIGN_ON perk exceeds 2500000 cents")
    ts = db.now_ms()
    perk = {
        "id": db.new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "offer_id": offer_id,
        "kind": kind,
        "amount_cents": amount,
        "clawback_months": months,
        "clawback_variant": variant,
        "status": "DRAFT",
    }
    db.perks[perk["id"]] = perk
    req = db.requisitions[offer["requisition_id"]]
    calc.compute_costs(offer)
    calc.compute_equity_metrics(offer, req)
    calc.touch_no_version(offer)
    offer_ops.append_event(offer_id, "PERK_ADDED", uid, f"kind={kind}")
    return success(perk, status=201)


@bp.route("/api/offers/<offer_id>/perks", methods=["GET"])
def list_perks(offer_id):
    uid, role = get_actor()
    require_role(role, READ_ROLES)
    offer = db.offers.get(offer_id)
    if offer is None:
        raise_err(ERR_OFFER_NOT_FOUND, "Offer not found")
    if role == "Candidate" and offer["candidate_id"] != uid:
        raise_err(ERR_NOT_RESOURCE_OWNER, "Candidates may only view their own offers' perks")
    items = sorted(
        [p for p in db.perks.values() if p["offer_id"] == offer_id],
        key=lambda p: p["created_at"],
    )
    return success(items, response_type="array")


@bp.route("/api/perks/<perk_id>/clawback-quote", methods=["GET"])
def clawback_quote(perk_id):
    uid, role = get_actor()
    require_role(role, QUOTE_ROLES)
    perk = db.perks.get(perk_id)
    if perk is None:
        raise_err(ERR_PERK_NOT_FOUND, "Perk not found")
    mw_s = request.args.get("months_worked")
    if mw_s is None:
        raise_err(ERR_INVALID_REQUEST, "months_worked query parameter is required")
    try:
        months_worked = int(mw_s)
    except (TypeError, ValueError):
        raise_err(ERR_INVALID_REQUEST, "months_worked must be an integer")
    if months_worked < 0:
        raise_err(ERR_INVALID_REQUEST, "months_worked must be >= 0")
    repayment, remaining = calc.clawback_quote(perk, months_worked)
    return success({
        "repayment_cents": repayment,
        "remaining_months": remaining,
        "clawback_variant": perk["clawback_variant"],
    })

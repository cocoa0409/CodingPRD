"""Health treatments and death-loss reports."""
from flask import Blueprint, request

from common import (authenticate, body_of, opt_bool, opt_int, opt_str,
                    req_dt_str, req_enum, req_int, req_str)
from derive import (contract_of_lot, death_loss_sweep, deaths_of_lot,
                    pasture_of_contract, recompute_pasture,
                    settlements_of_lot, treatment_allocation,
                    treatments_of_lot)
from envelope import created, listing, ok, pagination, public, public_list
from errors import ApiError
from routes.lots import get_lot
from store import db, new_record, touch

bp = Blueprint("health", __name__)

ALL_ROLES = ("Grazier", "CattleOwner", "RangeConsultant", "PlatformAdmin")
CLASSIFICATIONS = ("ROUTINE_PROTOCOL", "THERAPEUTIC", "PREVENTIVE_EMERGENCY")
TREATMENT_DECISIONS = ("APPROVE", "DISPUTE", "VOID")
DEATH_CAUSES = ("DISEASE", "PREDATOR", "WEATHER", "INFRASTRUCTURE_FAILURE", "UNKNOWN")
DEATH_DECISIONS = ("CONFIRM", "REJECT", "VOID")


# ---------------------------------------------------------------- treatments --
@bp.post("/grazing/lots/<lot_id>/treatments")
def record_treatment(lot_id):
    actor = authenticate(("Grazier",))
    lot = get_lot(lot_id)
    body = body_of()
    protocol_code = req_str(body, "protocol_code")
    classification = req_enum(body, "classification", CLASSIFICATIONS)
    treatment_date = req_dt_str(body, "treatment_date")
    withdrawal_days = opt_int(body, "withdrawal_days", 0, minv=0)
    head_treated = req_int(body, "head_treated", gt=0)
    drug_cost_cents = req_int(body, "drug_cost_cents", minv=0)
    labor_cost_cents = req_int(body, "labor_cost_cents", minv=0)

    contract = contract_of_lot(lot)
    if contract["grazier_id"] != actor.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Only the contract's grazier may record treatments.")

    total = drug_cost_cents + labor_cost_cents
    owner_share, grazier_share = treatment_allocation(
        classification, total, contract["treatment_cost_split_pct"])

    rec = new_record()
    rec.update({
        "lot_id": lot["id"],
        "protocol_code": protocol_code,
        "classification": classification,
        "treatment_date": treatment_date,
        "withdrawal_days": withdrawal_days,
        "head_treated": head_treated,
        "drug_cost_cents": drug_cost_cents,
        "labor_cost_cents": labor_cost_cents,
        "total_cost_cents": total,
        "owner_share_cents": owner_share,
        "grazier_share_cents": grazier_share,
        "review_note": None,
        "status": "RECORDED",
    })
    db.treatments[rec["id"]] = rec
    return created(public(rec))


@bp.get("/grazing/lots/<lot_id>/treatments")
def list_treatments(lot_id):
    authenticate(ALL_ROLES)
    lot = get_lot(lot_id)
    limit, offset = pagination()
    rows = treatments_of_lot(lot["id"])
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return listing(public_list(rows), limit, offset)


@bp.post("/grazing/treatments/<treatment_id>/review")
def review_treatment(treatment_id):
    actor = authenticate(("CattleOwner", "Grazier"))
    treatment = db.treatments.get(treatment_id)
    if treatment is None:
        raise ApiError("ERR_TREATMENT_NOT_FOUND", "Treatment does not exist.")
    body = body_of()
    decision = req_enum(body, "decision", TREATMENT_DECISIONS)
    note = opt_str(body, "note")

    lot = db.lots[treatment["lot_id"]]
    contract = contract_of_lot(lot)
    if actor.is_grazier and contract["grazier_id"] != actor.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Only the contract's grazier may act here.")
    if actor.is_owner and contract["cattle_owner_id"] != actor.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Only the contract's cattle owner may act here.")

    current = treatment["status"]
    target = None
    if actor.is_owner and decision == "APPROVE" and current in ("RECORDED", "DISPUTED"):
        target = "APPROVED"
    elif actor.is_owner and decision == "DISPUTE" and current == "RECORDED":
        target = "DISPUTED"
    elif actor.is_grazier and decision == "VOID" and current in ("RECORDED", "DISPUTED"):
        target = "VOIDED"
    if target is None:
        raise ApiError("ERR_TREATMENT_INVALID_STATE",
                       "Decision %s is not permitted from %s." % (decision, current))

    treatment["status"] = target
    if note is not None:
        treatment["review_note"] = note
    touch(treatment)
    return ok(public(treatment))


# -------------------------------------------------------------- death losses --
@bp.post("/grazing/lots/<lot_id>/death-losses")
def report_death_loss(lot_id):
    actor = authenticate(("Grazier",))
    lot = get_lot(lot_id)
    body = body_of()
    death_date = req_dt_str(body, "death_date")
    head_lost = req_int(body, "head_lost", gt=0)
    cause = req_enum(body, "cause", DEATH_CAUSES)
    necropsy_performed = opt_bool(body, "necropsy_performed", False)

    contract = contract_of_lot(lot)
    if contract["grazier_id"] != actor.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Only the contract's grazier may report a death loss.")

    alive = (lot["head_count_received"] or 0) - (lot["confirmed_death_head"] or 0)
    if head_lost > alive:
        raise ApiError("ERR_HEAD_COUNT_INCONSISTENT",
                       "The report claims more head than are still alive on the lot.")

    rec = new_record()
    rec.update({
        "lot_id": lot["id"],
        "death_date": death_date,
        "head_lost": head_lost,
        "cause": cause,
        "necropsy_performed": necropsy_performed,
        "owner_liable_head": 0,
        "grazier_liable_head": 0,
        "credit_cents": 0,
        "review_note": None,
        "status": "REPORTED",
    })
    db.death_losses[rec["id"]] = rec
    return created(public(rec))


@bp.get("/grazing/lots/<lot_id>/death-losses")
def list_death_losses(lot_id):
    authenticate(ALL_ROLES)
    lot = get_lot(lot_id)
    limit, offset = pagination()
    rows = deaths_of_lot(lot["id"])
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return listing(public_list(rows), limit, offset)


@bp.post("/grazing/death-losses/<report_id>/review")
def review_death_loss(report_id):
    actor = authenticate(("RangeConsultant", "Grazier"))
    report = db.death_losses.get(report_id)
    if report is None:
        raise ApiError("ERR_DEATH_LOSS_NOT_FOUND", "Death-loss report does not exist.")
    body = body_of()
    decision = req_enum(body, "decision", DEATH_DECISIONS)
    note = opt_str(body, "note")

    lot = db.lots[report["lot_id"]]
    contract = contract_of_lot(lot)
    if actor.is_grazier and contract["grazier_id"] != actor.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Only the contract's grazier may act here.")

    current = report["status"]
    target = None
    if actor.is_consultant and decision == "CONFIRM" and current == "REPORTED":
        target = "CONFIRMED"
    elif actor.is_consultant and decision == "REJECT" and current == "REPORTED":
        target = "REJECTED"
    elif actor.is_grazier and decision == "VOID" and current == "CONFIRMED":
        target = "VOIDED"
    if target is None:
        raise ApiError("ERR_DEATH_LOSS_INVALID_STATE",
                       "Decision %s is not permitted from %s." % (decision, current))

    if target == "VOIDED":
        for settlement in settlements_of_lot(lot["id"]):
            if settlement["status"] not in ("DRAFT", "VOID"):
                raise ApiError("ERR_SETTLEMENT_INVALID_STATE",
                               "A settled lot cannot have its death record rewritten.")

    report["status"] = target
    if note is not None:
        report["review_note"] = note
    touch(report)

    death_loss_sweep(lot)
    recompute_pasture(pasture_of_contract(contract))
    return ok(public(report))

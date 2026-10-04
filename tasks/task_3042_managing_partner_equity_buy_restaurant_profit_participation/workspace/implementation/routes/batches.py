"""Meat cut batch routes (PRD §3.7)."""

from flask import Blueprint, request

import db
from errors import conflict, invalid_request, unprocessable
from errors import (
    ERR_BATCH_PERIOD_RESTAURANT_MISMATCH,
    ERR_INVALID_STATE,
    ERR_PERIOD_NOT_OPEN,
    ERR_UNKNOWN_CUT_CODE,
)
from middleware import require_roles
from response import success_list, success_object
from services import calculations, domain
from util import base_entity, get_json_body, paginate, req_field, req_number, req_string, touch

bp = Blueprint("batches", __name__)

BATCH_READ_ROLES = ("PlatformAdmin", "CorporateController", "OperationsAuditor", "ManagingPartner")


def _active_standard_for(cut_code):
    for y in db.yield_standards.values():
        if y["active"] and y["cut_code"] == cut_code:
            return y
    return None


def _check_period_open(period):
    if period["status"] not in domain.PERIOD_BATCH_OPEN_STATUSES:
        raise conflict(
            ERR_PERIOD_NOT_OPEN,
            "Parent period must be OPEN, COMPUTED, or REOPENED",
        )


@bp.route("/meat-cut-batches", methods=["POST"])
def create_batch():
    require_roles("OperationsAuditor")
    body = get_json_body()
    restaurant_id = req_field(body, "restaurant_id")
    profit_period_id = req_field(body, "profit_period_id")
    cut_code = req_string(body, "cut_code")
    # Body FK existence (tier 4).
    domain.ref_restaurant(restaurant_id)
    period = domain.ref_period(profit_period_id)
    # State gate (tier 5) — period must accept batch activity.
    _check_period_open(period)
    # Referential (tier 7): period must belong to the same restaurant; cut code known.
    if period["restaurant_id"] != restaurant_id:
        raise unprocessable(
            ERR_BATCH_PERIOD_RESTAURANT_MISMATCH,
            "profit_period_id belongs to a different restaurant",
        )
    if _active_standard_for(cut_code) is None:
        raise unprocessable(ERR_UNKNOWN_CUT_CODE, "No active yield standard matches the cut_code")
    weight = req_number(body, "sub_primal_weight_lbs")
    if not (weight > 0):
        raise invalid_request("sub_primal_weight_lbs must be > 0")
    b = base_entity()
    b.update({
        "restaurant_id": restaurant_id,
        "profit_period_id": profit_period_id,
        "cut_code": cut_code,
        "sub_primal_weight_lbs": weight,
        "actual_yield_lbs": None,
        "actual_waste_lbs": None,
        "excess_waste_lbs": None,
        "waste_charge_cents": None,
        "status": "RECORDED",
    })
    db.batches[b["id"]] = b
    return success_object(domain.ser_batch(b), 201)


@bp.route("/meat-cut-batches", methods=["GET"])
def list_batches():
    require_roles(*BATCH_READ_ROLES)
    items = list(db.batches.values())
    restaurant_id = request.args.get("restaurant_id")
    if restaurant_id is not None:
        items = [b for b in items if b["restaurant_id"] == restaurant_id]
    period_id = request.args.get("profit_period_id")
    if period_id is not None:
        items = [b for b in items if b["profit_period_id"] == period_id]
    status = request.args.get("status")
    if status is not None:
        items = [b for b in items if b["status"] == status]
    page, limit, offset, total = paginate(items)
    return success_list([domain.ser_batch(b) for b in page], limit, offset, total)


@bp.route("/meat-cut-batches/<bid>", methods=["GET"])
def get_batch(bid):
    require_roles(*BATCH_READ_ROLES)
    return success_object(domain.ser_batch(domain.get_batch(bid)))


@bp.route("/meat-cut-batches/<bid>/audit", methods=["POST"])
def audit_batch(bid):
    require_roles("OperationsAuditor")
    b = domain.get_batch(bid)
    if b["status"] != "RECORDED":
        raise conflict(ERR_INVALID_STATE, "Batch must be RECORDED to audit")
    period = db.periods.get(b["profit_period_id"])
    if period is not None:
        _check_period_open(period)
    body = get_json_body()
    actual_yield = req_number(body, "actual_yield_lbs")
    if actual_yield < 0:
        raise invalid_request("actual_yield_lbs must be >= 0")
    standard = _active_standard_for(b["cut_code"])
    if standard is None:
        raise unprocessable(ERR_UNKNOWN_CUT_CODE, "No active yield standard matches the cut_code")
    actual_waste, excess, charge, conforming = calculations.meat_waste_charge(b, standard, actual_yield)
    b["actual_yield_lbs"] = actual_yield
    b["actual_waste_lbs"] = actual_waste
    b["excess_waste_lbs"] = excess
    b["waste_charge_cents"] = charge
    b["status"] = "AUDITED_CONFORMING" if conforming else "VARIANCE_CONFIRMED"
    touch(b)
    return success_object(domain.ser_batch(b))


@bp.route("/meat-cut-batches/<bid>/waive", methods=["POST"])
def waive_batch(bid):
    require_roles("CorporateController")
    b = domain.get_batch(bid)
    if b["status"] != "VARIANCE_CONFIRMED":
        raise conflict(ERR_INVALID_STATE, "Batch must be VARIANCE_CONFIRMED to waive")
    period = db.periods.get(b["profit_period_id"])
    if period is not None:
        _check_period_open(period)
    b["status"] = "VARIANCE_WAIVED"
    b["waste_charge_cents"] = 0
    touch(b)
    return success_object(domain.ser_batch(b))

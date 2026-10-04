"""PerformanceMeasurement, PayerSettlement, MedicalCost, and clock endpoints."""
from flask import Blueprint, request

from db import db
from errors import (err_not_found, err_state, err_input,
                    ERR_MEASUREMENT_NOT_FOUND, ERR_SETTLEMENT_NOT_FOUND,
                    ERR_CONTRACT_NOT_FOUND, ERR_MEMBER_NOT_FOUND,
                    ERR_SETTLEMENT_NOT_PROVISIONAL,
                    ERR_SETTLEMENT_NOT_FINALIZED, ERR_CONTRACT_EXPIRED,
                    ERR_INVALID_REQUEST)
from middleware import require_roles
from response import success_object, success_list, parse_pagination, paginate
from services import serializers
from services.clock import (now_clock, set_clock, advance_clock_hours,
                            parse_ts, sweep_episode_lapses)
from services.measurements import serialize as serialize_measurement
from services.resources import base_fields, touch
from services.settlements import (compute_settlement_amounts,
                                  finalize_settlement)
from services.validation import (get_json_body, require_string, require_int)

bp = Blueprint("ops", __name__)

MEASUREMENT_ROLES = ["PlatformAdmin", "ContractAdministrator",
                     "PerformanceAnalyst"]
SETTLEMENT_READ_ROLES = ["PlatformAdmin", "ContractAdministrator",
                         "PerformanceAnalyst"]
COST_READ_ROLES = ["PlatformAdmin", "ContractAdministrator",
                   "PerformanceAnalyst"]
ADMIN = ["ContractAdministrator"]
PLATFORM = ["PlatformAdmin"]


# ---------------- Performance Measurements ----------------

@bp.route("/performance-measurements", methods=["GET"])
def list_measurements():
    require_roles(MEASUREMENT_ROLES)
    limit, offset = parse_pagination(request.args)
    items = list(db.measurements.values())
    pc = request.args.get("payer_contract_id")
    if pc:
        items = [m for m in items if m.get("payer_contract_id") == pc]
    mid = request.args.get("member_id")
    if mid:
        items = [m for m in items if m.get("member_id") == mid]
    pi = request.args.get("period_index")
    if pi is not None and pi != "":
        try:
            pi_val = int(pi)
        except ValueError:
            raise err_input(ERR_INVALID_REQUEST, "period_index must be an integer")
        items = [m for m in items if m.get("period_index") == pi_val]
    items.sort(key=lambda m: (m["created_at"], m["id"]))
    page, total = paginate(items, limit, offset)
    return success_list([serialize_measurement(m) for m in page],
                        limit, offset, total)


@bp.route("/performance-measurements/<measurementId>", methods=["GET"])
def get_measurement(measurementId):
    require_roles(MEASUREMENT_ROLES)
    m = db.measurements.get(measurementId)
    if m is None:
        raise err_not_found(ERR_MEASUREMENT_NOT_FOUND, "PerformanceMeasurement")
    return success_object(serialize_measurement(m))


# ---------------- Settlements ----------------

def _get_contract_or_404(contract_id):
    c = db.payer_contracts.get(contract_id)
    if c is None:
        raise err_not_found(ERR_CONTRACT_NOT_FOUND, "PayerContract")
    return c


def _settlements_for_contract(contract_id):
    return [s for s in db.settlements.values()
            if s.get("payer_contract_id") == contract_id]


@bp.route("/payer-contracts/<contractId>/settlements", methods=["POST"])
def create_settlement(contractId):
    require_roles(ADMIN)
    contract = _get_contract_or_404(contractId)
    program = db.care_programs.get(contract.get("care_program_id"))
    period = int(program.get("current_period_index") or 0) if program else 0

    existing = _settlements_for_contract(contractId)
    amounts = compute_settlement_amounts(contract, period, existing)

    s = base_fields()
    s.update({
        "payer_contract_id": contractId,
        "period_index": period,
        "enrolled_member_count": amounts["enrolled_member_count"],
        "gross_capitation_cents": amounts["gross_capitation_cents"],
        "gross_savings_share_cents": amounts["gross_savings_share_cents"],
        "quality_withhold_cents": amounts["quality_withhold_cents"],
        "withhold_released_cents": None,
        "net_payment_cents": None,
        "status": "PROVISIONAL",
    })
    db.settlements[s["id"]] = s
    return success_object(serializers.settlement(s), status=201)


@bp.route("/payer-contracts/<contractId>/settlements", methods=["GET"])
def list_settlements(contractId):
    require_roles(SETTLEMENT_READ_ROLES)
    _get_contract_or_404(contractId)
    limit, offset = parse_pagination(request.args)
    items = _settlements_for_contract(contractId)
    st = request.args.get("status")
    if st:
        items = [s for s in items if s.get("status") == st]
    items.sort(key=lambda s: (s["created_at"], s["id"]))
    page, total = paginate(items, limit, offset)
    return success_list([serializers.settlement(s) for s in page],
                        limit, offset, total)


@bp.route("/settlements/<settlementId>", methods=["GET"])
def get_settlement(settlementId):
    require_roles(SETTLEMENT_READ_ROLES)
    s = db.settlements.get(settlementId)
    if s is None:
        raise err_not_found(ERR_SETTLEMENT_NOT_FOUND, "PayerSettlement")
    return success_object(serializers.settlement(s))


@bp.route("/payer-contracts/<contractId>/settlements/<settlementId>/finalize",
          methods=["POST"])
def finalize(contractId, settlementId):
    require_roles(ADMIN)
    contract = _get_contract_or_404(contractId)
    s = db.settlements.get(settlementId)
    if s is None or s.get("payer_contract_id") != contractId:
        raise err_not_found(ERR_SETTLEMENT_NOT_FOUND, "PayerSettlement")
    if s.get("status") != "PROVISIONAL":
        raise err_state(ERR_SETTLEMENT_NOT_PROVISIONAL,
                        "Settlement must be PROVISIONAL to finalize")
    expiration = parse_ts(contract.get("contract_expiration_date"))
    if expiration is not None and now_clock() > expiration:
        raise err_state(ERR_CONTRACT_EXPIRED,
                        "Contract has passed its expiration date")

    finalize_settlement(contract, s)
    s["status"] = "FINALIZED"
    touch(s)
    return success_object(serializers.settlement(s))


@bp.route("/payer-contracts/<contractId>/settlements/<settlementId>/mark-paid",
          methods=["POST"])
def mark_paid(contractId, settlementId):
    require_roles(ADMIN)
    _get_contract_or_404(contractId)
    s = db.settlements.get(settlementId)
    if s is None or s.get("payer_contract_id") != contractId:
        raise err_not_found(ERR_SETTLEMENT_NOT_FOUND, "PayerSettlement")
    if s.get("status") != "FINALIZED":
        raise err_state(ERR_SETTLEMENT_NOT_FINALIZED,
                        "Settlement must be FINALIZED to mark paid")
    s["status"] = "PAID"
    touch(s)
    return success_object(serializers.settlement(s))


@bp.route("/payer-contracts/<contractId>/settlements/<settlementId>/void",
          methods=["POST"])
def void_settlement(contractId, settlementId):
    require_roles(ADMIN)
    _get_contract_or_404(contractId)
    s = db.settlements.get(settlementId)
    if s is None or s.get("payer_contract_id") != contractId:
        raise err_not_found(ERR_SETTLEMENT_NOT_FOUND, "PayerSettlement")
    if s.get("status") != "PROVISIONAL":
        raise err_state(ERR_SETTLEMENT_NOT_PROVISIONAL,
                        "Settlement must be PROVISIONAL to void")
    s["status"] = "VOIDED"
    touch(s)
    return success_object(serializers.settlement(s))


# ---------------- Medical Costs ----------------

@bp.route("/medical-costs", methods=["POST"])
def create_medical_cost():
    require_roles(ADMIN)
    body = get_json_body()
    payer_contract_id = require_string(body, "payer_contract_id")
    member_id = require_string(body, "member_id")
    period_index = require_int(body, "period_index", min_value=0)
    amount_cents = require_int(body, "amount_cents", min_value=0)
    incurred_date = require_string(body, "incurred_date")

    if db.payer_contracts.get(payer_contract_id) is None:
        raise err_not_found(ERR_CONTRACT_NOT_FOUND, "PayerContract")
    if db.members.get(member_id) is None:
        raise err_not_found(ERR_MEMBER_NOT_FOUND, "Member")

    c = base_fields()
    c.update({
        "payer_contract_id": payer_contract_id,
        "member_id": member_id,
        "period_index": period_index,
        "amount_cents": amount_cents,
        "incurred_date": incurred_date,
    })
    db.medical_costs[c["id"]] = c
    return success_object(serializers.medical_cost(c), status=201)


@bp.route("/medical-costs", methods=["GET"])
def list_medical_costs():
    require_roles(COST_READ_ROLES)
    limit, offset = parse_pagination(request.args)
    items = list(db.medical_costs.values())
    pc = request.args.get("payer_contract_id")
    if pc:
        items = [c for c in items if c.get("payer_contract_id") == pc]
    mid = request.args.get("member_id")
    if mid:
        items = [c for c in items if c.get("member_id") == mid]
    pi = request.args.get("period_index")
    if pi is not None and pi != "":
        try:
            pi_val = int(pi)
        except ValueError:
            raise err_input(ERR_INVALID_REQUEST, "period_index must be an integer")
        items = [c for c in items if c.get("period_index") == pi_val]
    items.sort(key=lambda c: (c["created_at"], c["id"]))
    page, total = paginate(items, limit, offset)
    return success_list([serializers.medical_cost(c) for c in page],
                        limit, offset, total)


# ---------------- Logical clock ----------------

@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_roles(PLATFORM)
    body = get_json_body()
    current_utc = require_string(body, "current_utc")
    dt = parse_ts(current_utc, "current_utc")
    # PRD §3.6: only the period-advance capability and advance_hours trigger
    # the LAPSED sweep; setting the clock to an arbitrary timestamp does not.
    set_clock(dt)
    return success_object({})


@bp.route("/_clock/advance_hours", methods=["POST"])
def advance_hours():
    require_roles(PLATFORM)
    body = get_json_body()
    by_hours = require_int(body, "by_hours")
    advance_clock_hours(by_hours)
    sweep_episode_lapses()
    return success_object({})

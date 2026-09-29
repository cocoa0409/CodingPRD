"""Award, contract, approval, signature and deposit endpoints (3.7 - 3.9)."""
from flask import Blueprint, g

import clock
import db as store
import enums
import lookup
import middleware
import response
import serializers
import validate
from db import db, touch
from errors import ApiError
from money import D, q2
from services import calc, flows, rollups

bp = Blueprint("contracts", __name__)

AWARD_EVENT_STATUSES = ("BID_REVIEW", "AWARDED", "CONTRACTED")


@bp.route("/sourcing/events/<event_id>/award", methods=["POST"])
@middleware.roles(middleware.ROLE_SOURCING_MANAGER)
def award(event_id):
    event = lookup.event(event_id)
    data = validate.body()

    proposal = None
    raw_proposal_id = data.get("proposal_id")
    if raw_proposal_id is not None:
        if not isinstance(raw_proposal_id, str):
            validate.bad("Field proposal_id must be a string")
        proposal = lookup.proposal(raw_proposal_id)
        if lookup.event_of_proposal(proposal) is not event:
            raise ApiError("ERR_PROPOSAL_NOT_FOUND",
                           "That bid does not belong to this event")

    validate.req_str(data, "proposal_id")
    expected_event_version = validate.req_int(data, "expected_event_version")
    validate.opt_str(data, "award_note")

    if event["status"] not in AWARD_EVENT_STATUSES:
        raise ApiError("ERR_EVENT_STATE_INVALID",
                       "The event cannot be awarded in its current status")
    if proposal["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_PROPOSAL_STATE_INVALID",
                       "Only a bid UNDER_REVIEW may be awarded")

    existing = lookup.live_contract_of_event(event["id"])
    if existing is not None and existing["signature_state"] == "EXECUTED":
        raise ApiError("ERR_CONTRACT_ALREADY_EXECUTED",
                       "This event already has an executed contract")
    if event["status"] == "CONTRACTED":
        raise ApiError("ERR_CONTRACT_ALREADY_EXECUTED",
                       "This event already has an executed contract")

    if expected_event_version != event["version"]:
        raise ApiError("ERR_STALE_EVENT_VERSION",
                       "expected_event_version does not match the event")

    venue = db.venues[proposal["venue_id"]]
    entry = lookup.entry_for(event["id"], proposal["venue_id"])
    flows.supplier_program_guards(event, venue, proposal, entry)

    has_contracted_eval = any(
        row["basis"] == "CONTRACTED_BASIS"
        for row in lookup.evaluations_of_proposal(proposal["id"])
    )
    if not has_contracted_eval:
        raise ApiError("ERR_BID_EVALUATION_REQUIRED",
                       "The bid needs a CONTRACTED_BASIS evaluation first")

    pre_rebate = q2(proposal["total_cost_contracted_usd"])
    if pre_rebate > event["budget_ceiling_usd"]:
        raise ApiError("ERR_BUDGET_CEILING_EXCEEDED",
                       "The bid exceeds the event budget ceiling")

    if existing is not None:
        flows.unwind_contract(existing)

    model = calc.cost_model(proposal, "CONTRACTED_BASIS")
    rebate_pct, rebate_usd, contracted_total = calc.volume_rebate(pre_rebate)
    paid_nights = model["paid_room_nights"]
    rate = model["net_adr_usd"]

    contract = store.base_row()
    contract.update({
        "event_id": event["id"],
        "proposal_id": proposal["id"],
        "venue_id": venue["id"],
        "approval_state": "PENDING_ROUTING",
        "signature_state": "UNSIGNED",
        "awarded_by_user_id": g.user_id,
        "contracted_room_rate_usd": rate,
        "contracted_paid_room_nights": paid_nights,
        "contracted_room_revenue_usd": q2(D(rate) * D(paid_nights)),
        "pre_rebate_total_usd": pre_rebate,
        "volume_rebate_pct": rebate_pct,
        "volume_rebate_usd": rebate_usd,
        "contracted_total_usd": contracted_total,
        "peak_rooms_per_night": calc.peak_rooms_per_night(paid_nights,
                                                          event["nights_span"]),
        "attrition_allowance_pct": proposal["attrition_allowance_pct"],
        "cancellation_schedule": proposal["cancellation_schedule"],
        "force_majeure_scope": proposal["force_majeure_scope"],
        "rebooking_credit_pct": proposal["rebooking_credit_pct"],
        "service_charge_pct": proposal["service_charge_pct"],
        "tax_pct": proposal["tax_pct"],
        "resort_fee_usd_per_night": proposal["resort_fee_usd_per_night"],
        "fnb_minimum_usd": proposal["fnb_minimum_usd"],
        "concession_applied_usd": model["concession_applied_usd"],
        "deposit_total_usd": None,
        "deposit_paid_usd": q2(0),
        "deposit_outstanding_usd": None,
        "approval_step_count": 0,
        "planner_signatory_name": None,
        "venue_signatory_name": None,
        "executed_at": None,
        "terminated_at": None,
        "cancellation_fee_usd": None,
        "rebooking_credit_usd": None,
        "termination_reason": None,
    })
    db.contracts[contract["id"]] = contract

    proposal["status"] = "AWARDED"
    touch(proposal)
    flows.award_cascade(event, proposal)

    rfp = db.rfps[proposal["rfp_id"]]
    before = rfp["submitted_count"]
    rollups.refresh_submitted_count(rfp)
    if rfp["submitted_count"] != before:
        touch(rfp)

    event["status"] = "AWARDED"
    event["awarded_proposal_id"] = proposal["id"]
    event["committed_spend_usd"] = contracted_total
    rollups.refresh_event_rollup(event)
    rollups.refresh_budget_envelope(event)
    touch(event)
    return response.obj(serializers.contract(contract), 201)


@bp.route("/sourcing/contracts/<contract_id>", methods=["GET"])
@middleware.roles(*middleware.ALL_ROLES)
def get_contract(contract_id):
    return response.obj(serializers.contract(lookup.contract(contract_id)))


@bp.route("/sourcing/contracts", methods=["GET"])
@middleware.roles(*middleware.ALL_ROLES)
def list_contracts():
    limit, offset = validate.pagination()
    event_id = validate.str_filter("event_id")
    proposal_id = validate.str_filter("proposal_id")
    venue_id = validate.str_filter("venue_id")
    approval_state = validate.enum_filter("approval_state", enums.APPROVAL_STATES)
    signature_state = validate.enum_filter("signature_state", enums.SIGNATURE_STATES)
    rows = store.ordered(db.contracts.values())
    if event_id is not None:
        rows = [r for r in rows if r["event_id"] == event_id]
    if proposal_id is not None:
        rows = [r for r in rows if r["proposal_id"] == proposal_id]
    if venue_id is not None:
        rows = [r for r in rows if r["venue_id"] == venue_id]
    if approval_state is not None:
        rows = [r for r in rows if r["approval_state"] == approval_state]
    if signature_state is not None:
        rows = [r for r in rows if r["signature_state"] == signature_state]
    return validate.page(rows, limit, offset, serializers.contract)


@bp.route("/sourcing/contracts/<contract_id>/route-approvals", methods=["POST"])
@middleware.roles(middleware.ROLE_SOURCING_MANAGER)
def route_approvals(contract_id):
    contract = lookup.contract(contract_id)
    validate.body()
    if (contract["approval_state"] != "PENDING_ROUTING"
            or contract["signature_state"] in ("TERMINATED", "VOIDED")):
        raise ApiError("ERR_CONTRACT_STATE_INVALID",
                       "This contract cannot be routed for approval")
    venue = db.venues[contract["venue_id"]]
    levels = calc.approval_route(
        venue["preferred_supplier_status"],
        contract["contracted_total_usd"],
        contract["force_majeure_scope"],
    )
    for index, (level, required_role) in enumerate(levels):
        step = store.base_row()
        step.update({
            "contract_id": contract["id"],
            "step_seq": index + 1,
            "approval_level": level,
            "required_role": required_role,
            "decision": "PENDING",
            "approver_user_id": None,
            "decision_note": None,
            "decided_at": None,
        })
        db.steps[step["id"]] = step
    rollups.refresh_approval_step_count(contract)
    contract["approval_state"] = "IN_APPROVAL"
    touch(contract)
    return response.obj(serializers.contract(contract))


@bp.route("/sourcing/contracts/<contract_id>/approval-steps", methods=["GET"])
@middleware.roles(*middleware.PLANNER_SIDE)
def list_steps(contract_id):
    contract = lookup.contract(contract_id)
    limit, offset = validate.pagination()
    decision = validate.enum_filter("decision", enums.APPROVAL_DECISIONS)
    rows = lookup.steps_of_contract(contract["id"])
    if decision is not None:
        rows = [r for r in rows if r["decision"] == decision]
    return validate.page(rows, limit, offset, serializers.step)


@bp.route("/sourcing/approval-steps/<step_id>", methods=["GET"])
@middleware.roles(*middleware.PLANNER_SIDE)
def get_step(step_id):
    return response.obj(serializers.step(lookup.step(step_id)))


@bp.route("/sourcing/approval-steps/<step_id>/decide", methods=["POST"])
@middleware.roles(middleware.ROLE_CONTRACT_APPROVER, middleware.ROLE_PROGRAM_ADMIN)
def decide_step(step_id):
    step = lookup.step(step_id)
    data = validate.body()
    decision = validate.req_enum(data, "decision", ("APPROVED", "REJECTED"))
    note = validate.opt_str(data, "decision_note")
    contract = db.contracts[step["contract_id"]]

    if step["decision"] != "PENDING" or contract["approval_state"] != "IN_APPROVAL":
        raise ApiError("ERR_CONTRACT_STATE_INVALID",
                       "This approval step cannot be decided")

    siblings = lookup.steps_of_contract(contract["id"])
    for other in siblings:
        if other["step_seq"] < step["step_seq"] and other["decision"] != "APPROVED":
            raise ApiError("ERR_APPROVAL_STEP_OUT_OF_ORDER",
                           "An earlier approval step is still open")
    if g.role != step["required_role"]:
        raise ApiError("ERR_APPROVAL_LEVEL_ROLE_MISMATCH",
                       "This step must be decided by " + step["required_role"])
    if g.user_id == contract["awarded_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The awarding planner may not decide this contract")
    if decision == "APPROVED":
        for other in siblings:
            if other["id"] == step["id"]:
                continue
            if other["approver_user_id"] == g.user_id:
                raise ApiError("ERR_DUPLICATE_APPROVER",
                               "This approver already cleared another step")

    step["decision"] = decision
    step["approver_user_id"] = g.user_id
    step["decision_note"] = note
    step["decided_at"] = clock.now()
    touch(step)

    event = db.events[contract["event_id"]]
    if decision == "REJECTED":
        flows.reject_contract_cascade(contract, event)
        touch(contract)
        return response.obj(serializers.step(step))

    highest = max(row["step_seq"] for row in siblings)
    if step["step_seq"] == highest:
        contract["approval_state"] = "APPROVED"
        if contract["signature_state"] == "COUNTERSIGNED":
            flows.execute_contract(contract, event, db.venues[contract["venue_id"]])
    touch(contract)
    return response.obj(serializers.step(step))


@bp.route("/sourcing/contracts/<contract_id>/sign", methods=["POST"])
@middleware.roles(middleware.ROLE_SOURCING_MANAGER)
def sign(contract_id):
    contract = lookup.contract(contract_id)
    data = validate.body()
    name = validate.req_str(data, "planner_signatory_name", max_len=160)
    if (contract["signature_state"] != "UNSIGNED"
            or contract["approval_state"] in ("REJECTED", "CANCELLED")):
        raise ApiError("ERR_CONTRACT_STATE_INVALID",
                       "This contract cannot be planner-signed")
    contract["signature_state"] = "PLANNER_SIGNED"
    contract["planner_signatory_name"] = name
    touch(contract)
    return response.obj(serializers.contract(contract))


@bp.route("/sourcing/contracts/<contract_id>/countersign", methods=["POST"])
@middleware.roles(middleware.ROLE_VENUE_REP)
def countersign(contract_id):
    contract = lookup.contract(contract_id)
    middleware.own_venue(contract["venue_id"])
    data = validate.body()
    name = validate.req_str(data, "venue_signatory_name", max_len=160)
    if (contract["signature_state"] != "PLANNER_SIGNED"
            or contract["approval_state"] in ("REJECTED", "CANCELLED")):
        raise ApiError("ERR_CONTRACT_STATE_INVALID",
                       "This contract cannot be countersigned")
    event = db.events[contract["event_id"]]
    venue = db.venues[contract["venue_id"]]
    flows.room_block_capacity_guard(contract, event, venue)
    contract["signature_state"] = "COUNTERSIGNED"
    contract["venue_signatory_name"] = name
    if contract["approval_state"] == "APPROVED":
        flows.execute_contract(contract, event, venue)
    touch(contract)
    return response.obj(serializers.contract(contract))


@bp.route("/sourcing/contracts/<contract_id>/deposit-schedule", methods=["POST"])
@middleware.roles(middleware.ROLE_FINANCE_CONTROLLER)
def deposit_schedule(contract_id):
    contract = lookup.contract(contract_id)
    validate.body()
    if contract["signature_state"] != "EXECUTED":
        raise ApiError("ERR_CONTRACT_STATE_INVALID",
                       "Only an executed contract may carry a deposit schedule")
    if contract["deposit_total_usd"] is not None:
        raise ApiError("ERR_DEPOSIT_ALREADY_SCHEDULED",
                       "This contract already has a deposit schedule")
    event = db.events[contract["event_id"]]
    deposit_total, rows = calc.deposit_allocation(
        contract["contracted_total_usd"], event["start_date"]
    )
    for spec in rows:
        installment = store.base_row()
        installment.update({
            "contract_id": contract["id"],
            "installment_seq": spec["installment_seq"],
            "weight_pct": spec["weight_pct"],
            "amount_usd": spec["amount_usd"],
            "due_date": spec["due_date"],
            "status": "SCHEDULED",
            "paid_amount_usd": None,
            "paid_at": None,
            "payment_reference": None,
        })
        db.installments[installment["id"]] = installment
    contract["deposit_total_usd"] = deposit_total
    contract["deposit_paid_usd"] = q2(0)
    rollups.refresh_deposit_rollup(contract)
    touch(contract)
    return response.obj(serializers.contract(contract))


@bp.route("/sourcing/contracts/<contract_id>/deposit-installments", methods=["GET"])
@middleware.roles(middleware.ROLE_SOURCING_MANAGER, middleware.ROLE_VENUE_REP,
                  middleware.ROLE_FINANCE_CONTROLLER, middleware.ROLE_PROGRAM_ADMIN)
def list_installments(contract_id):
    contract = lookup.contract(contract_id)
    limit, offset = validate.pagination()
    status = validate.enum_filter("status", enums.INSTALLMENT_STATUSES)
    rows = lookup.installments_of_contract(contract["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return validate.page(rows, limit, offset, serializers.installment)


@bp.route("/sourcing/deposit-installments/<installment_id>", methods=["GET"])
@middleware.roles(middleware.ROLE_SOURCING_MANAGER, middleware.ROLE_VENUE_REP,
                  middleware.ROLE_FINANCE_CONTROLLER, middleware.ROLE_PROGRAM_ADMIN)
def get_installment(installment_id):
    return response.obj(serializers.installment(lookup.installment(installment_id)))


@bp.route("/sourcing/deposit-installments/<installment_id>/pay", methods=["POST"])
@middleware.roles(middleware.ROLE_FINANCE_CONTROLLER)
def pay_installment(installment_id):
    installment = lookup.installment(installment_id)
    data = validate.body()
    amount = validate.req_money(data, "paid_amount_usd")
    reference = validate.opt_str(data, "payment_reference", max_len=120)
    contract = db.contracts[installment["contract_id"]]

    if installment["status"] != "SCHEDULED":
        raise ApiError("ERR_CONTRACT_STATE_INVALID",
                       "Only a scheduled installment may be paid")
    for other in lookup.installments_of_contract(contract["id"]):
        if (other["installment_seq"] < installment["installment_seq"]
                and other["status"] != "PAID"):
            raise ApiError("ERR_DEPOSIT_SEQUENCE_VIOLATION",
                           "An earlier deposit installment is still unpaid")
    if q2(amount) != q2(installment["amount_usd"]):
        raise ApiError("ERR_DEPOSIT_AMOUNT_MISMATCH",
                       "paid_amount_usd must equal the installment amount")

    installment["status"] = "PAID"
    installment["paid_amount_usd"] = q2(amount)
    installment["payment_reference"] = reference
    installment["paid_at"] = clock.now()
    touch(installment)
    rollups.refresh_deposit_rollup(contract)
    touch(contract)
    return response.obj(serializers.installment(installment))


@bp.route("/sourcing/contracts/<contract_id>/terminate", methods=["POST"])
@middleware.roles(middleware.ROLE_SOURCING_MANAGER)
def terminate(contract_id):
    contract = lookup.contract(contract_id)
    data = validate.body()
    reason = validate.req_str(data, "termination_reason", max_len=500)
    if contract["signature_state"] != "EXECUTED":
        raise ApiError("ERR_CONTRACT_STATE_INVALID",
                       "Only an executed contract may be terminated")
    event = db.events[contract["event_id"]]
    arrival = clock.day_start(event["start_date"])
    moment = clock.now()
    if moment >= arrival:
        raise ApiError("ERR_TERMINATION_WINDOW_CLOSED",
                       "The termination window closed when the group arrived")

    days_out = calc.days_to_arrival(arrival, moment)
    fee, credit = calc.cancellation_fee(
        contract["cancellation_schedule"],
        contract["contracted_room_revenue_usd"],
        contract["rebooking_credit_pct"],
        days_out,
    )
    contract["signature_state"] = "TERMINATED"
    contract["terminated_at"] = moment
    contract["cancellation_fee_usd"] = fee
    contract["rebooking_credit_usd"] = credit
    contract["termination_reason"] = reason
    for row in lookup.installments_of_contract(contract["id"]):
        if row["status"] == "SCHEDULED":
            row["status"] = "CANCELLED"
            touch(row)
    rollups.refresh_deposit_rollup(contract)
    if contract["deposit_total_usd"] is not None:
        contract["deposit_outstanding_usd"] = q2(0)
    touch(contract)

    venue = db.venues[contract["venue_id"]]
    venue["blocked_room_nights"] = (
        venue["blocked_room_nights"] - contract["contracted_paid_room_nights"]
    )
    touch(venue)

    event["committed_spend_usd"] = q2(0)
    event["cancellation_liability_usd"] = q2(
        D(event["cancellation_liability_usd"]) + D(fee)
    )
    if event["status"] == "CONTRACTED":
        event["status"] = "CANCELLED"
    rollups.refresh_budget_envelope(event)
    touch(event)
    return response.obj(serializers.contract(contract))

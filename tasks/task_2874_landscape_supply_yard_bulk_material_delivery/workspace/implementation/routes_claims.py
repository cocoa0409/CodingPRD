"""Claim cases and the reusable-container deposit ledger."""
from flask import Blueprint

import calc
import serial
from core import (
    arg, auth, body, contractor_filter, db, fail, new_record, opt_id,
    pre_scope_order, present, render_list, req_enum, req_id, req_int, req_str,
    require, respond, scope_via_order, touch,
)

bp = Blueprint("claims", __name__)

CLAIM_TYPES = ("DRIVEWAY_DAMAGE", "SPILLAGE", "SHORT_LOAD")
DECISIONS = ("APPROVE", "DENY")
CLAIM_READ_ROLES = ("ClaimsAdjuster", "YardAdmin", "Contractor")
CONTAINER_READ_ROLES = ("YardLoader", "YardAdmin", "CreditManager", "Contractor")


def _order_of_claim(claim):
    return db.get("material_orders", claim["material_order_id"])


# --------------------------------------------------------------------------
# Filing and reading claims
# --------------------------------------------------------------------------
@bp.post("/claim-cases")
def create_claim():
    ctx = auth("Contractor")
    data = body()
    pre_scope_order(ctx, data)
    order_id = req_id(data, "material_order_id")
    claim_type = req_enum(data, "claim_type", CLAIM_TYPES)
    claimed = req_int(data, "claimed_amount_cents", minimum=0, exclusive_min=True)
    description = req_str(data, "description")
    load_id = opt_id(data, "delivery_load_id")
    ticket_id = opt_id(data, "will_call_ticket_id")

    order = require(db.get("material_orders", order_id), "material_orders")
    load = None
    ticket = None
    if load_id is not None:
        load = require(db.get("delivery_loads", load_id), "delivery_loads")
    if ticket_id is not None:
        ticket = require(db.get("will_call_tickets", ticket_id), "will_call_tickets")

    if load is not None and load["material_order_id"] != order_id:
        fail("ERR_CLAIM_TARGET_MISMATCH",
             "The named load belongs to a different order.")
    if ticket is not None and ticket["material_order_id"] != order_id:
        fail("ERR_CLAIM_TARGET_MISMATCH",
             "The named ticket belongs to a different order.")

    record = new_record(
        material_order_id=order_id,
        delivery_load_id=load_id,
        will_call_ticket_id=ticket_id,
        claim_type=claim_type,
        claimed_amount_cents=claimed,
        description=description,
        review_round=0,
        approved_amount_cents=None,
        payable_cents=None,
        invoice_offset_cents=0,
        deposit_offset_cents=0,
        goodwill_credit_cents=0,
        decided_by_user_id=None,
        denial_reason=None,
        info_request_note=None,
        status="SUBMITTED",
    )
    db.insert("claim_cases", record)
    return respond(serial.claim_case(record), 201)


@bp.get("/claim-cases")
def list_claims():
    ctx = auth(*CLAIM_READ_ROLES)
    order_id = arg("material_order_id")
    load_id = arg("delivery_load_id")
    ticket_id = arg("will_call_ticket_id")
    claim_type = arg("claim_type")
    status = arg("status")
    rows = []
    for record in db.claim_cases.values():
        if order_id is not None and record["material_order_id"] != order_id:
            continue
        if load_id is not None and record["delivery_load_id"] != load_id:
            continue
        if ticket_id is not None and record["will_call_ticket_id"] != ticket_id:
            continue
        if claim_type is not None and record["claim_type"] != claim_type:
            continue
        if status is not None and record["status"] != status:
            continue
        rows.append(record)
    rows = contractor_filter(
        ctx, rows,
        lambda r: (db.get("material_orders", r["material_order_id"]) or {}).get(
            "contractor_account_id"))
    return render_list(rows, serial.claim_case)


@bp.get("/claim-cases/<claim_case_id>")
def read_claim(claim_case_id):
    ctx = auth(*CLAIM_READ_ROLES)
    record = db.get("claim_cases", claim_case_id)
    if record is not None:
        scope_via_order(ctx, _order_of_claim(record))
    require(record, "claim_cases")
    return respond(serial.claim_case(record))


# --------------------------------------------------------------------------
# The cyclic review (PRD 3.7)
# --------------------------------------------------------------------------
@bp.post("/claim-cases/<claim_case_id>/start-review")
def start_review(claim_case_id):
    auth("ClaimsAdjuster")
    claim = require(db.get("claim_cases", claim_case_id), "claim_cases")
    if claim["status"] != "SUBMITTED":
        fail("ERR_CLAIM_NOT_REVIEWABLE", "Claim is %s." % claim["status"])
    claim["status"] = "UNDER_REVIEW"
    claim["review_round"] = int(claim["review_round"]) + 1
    touch(claim)
    return respond(serial.claim_case(claim))


@bp.post("/claim-cases/<claim_case_id>/request-info")
def request_info(claim_case_id):
    auth("ClaimsAdjuster")
    data = body()
    note = req_str(data, "info_request_note")
    claim = require(db.get("claim_cases", claim_case_id), "claim_cases")
    if claim["status"] != "UNDER_REVIEW":
        fail("ERR_CLAIM_NOT_REVIEWABLE", "Claim is %s." % claim["status"])
    claim["status"] = "INFO_REQUESTED"
    claim["info_request_note"] = note
    touch(claim)
    return respond(serial.claim_case(claim))


@bp.post("/claim-cases/<claim_case_id>/provide-info")
def provide_info(claim_case_id):
    ctx = auth("Contractor")
    data = body()
    claim = db.get("claim_cases", claim_case_id)
    if claim is not None:
        scope_via_order(ctx, _order_of_claim(claim))
    description = req_str(data, "description")
    require(claim, "claim_cases")
    if claim["status"] != "INFO_REQUESTED":
        fail("ERR_CLAIM_NOT_REVIEWABLE", "Claim is %s." % claim["status"])
    claim["description"] = description
    claim["status"] = "UNDER_REVIEW"
    claim["review_round"] = int(claim["review_round"]) + 1
    touch(claim)
    return respond(serial.claim_case(claim))


@bp.post("/claim-cases/<claim_case_id>/decide")
def decide_claim(claim_case_id):
    ctx = auth("ClaimsAdjuster")
    claim = db.get("claim_cases", claim_case_id)

    # Rung 4 outranks the request shape and even path existence.
    if claim is not None and claim["delivery_load_id"]:
        load = db.get("delivery_loads", claim["delivery_load_id"])
        if load is not None and load["dispatched_by_user_id"] == ctx.user_id:
            fail("ERR_SEGREGATION_OF_DUTIES",
                 "The dispatching planner may not adjudicate this claim.")

    data = body()
    decision = req_enum(data, "decision", DECISIONS)
    approved = None
    reason = None
    if decision == "APPROVE":
        approved = req_int(data, "approved_amount_cents", minimum=0)
    else:
        reason = req_str(data, "denial_reason")

    require(claim, "claim_cases")
    if claim["status"] != "UNDER_REVIEW":
        fail("ERR_CLAIM_NOT_REVIEWABLE", "Claim is %s." % claim["status"])

    claim["decided_by_user_id"] = ctx.user_id
    if decision == "DENY":
        claim["status"] = "DENIED"
        claim["denial_reason"] = reason
        touch(claim)
        return respond(serial.claim_case(claim))

    if approved > int(claim["claimed_amount_cents"]):
        fail("ERR_APPROVED_EXCEEDS_CLAIM",
             "The approved amount exceeds the amount claimed.")
    order = _order_of_claim(claim)
    figures = calc.claim_waterfall(claim, order, approved)
    claim["status"] = "APPROVED"
    claim["approved_amount_cents"] = approved
    for key in ("payable_cents", "invoice_offset_cents", "deposit_offset_cents",
                "goodwill_credit_cents"):
        claim[key] = figures[key]
    touch(claim)
    return respond(serial.claim_case(claim))


@bp.post("/claim-cases/<claim_case_id>/settle")
def settle_claim(claim_case_id):
    auth("CreditManager")
    claim = require(db.get("claim_cases", claim_case_id), "claim_cases")
    if claim["status"] != "APPROVED":
        fail("ERR_CLAIM_NOT_APPROVED", "Claim is %s." % claim["status"])
    payable = int(claim["payable_cents"] or 0)
    if payable <= 0:
        fail("ERR_CLAIM_NOT_PAYABLE", "The claim has nothing payable.")

    # ---- hop one -----------------------------------------------------------
    claim["status"] = "SETTLED"
    touch(claim)

    # ---- hop two: the credit memo on the order -----------------------------
    order = _order_of_claim(claim)
    if order is not None:
        memo = 0
        for other in calc.claims_of(order["id"]):
            if other["status"] == "SETTLED":
                memo += int(other["payable_cents"] or 0)
        order["credit_memo_cents"] = memo
        order["settlement_status"] = "CREDIT_MEMO_ISSUED"
        touch(order)

        offset = int(claim["deposit_offset_cents"] or 0)
        for record in calc.containers_of(order["id"]):
            if offset <= 0:
                break
            forfeited = int(record["forfeited_cents"])
            if forfeited <= 0:
                continue
            taken = forfeited if forfeited < offset else offset
            record["forfeited_cents"] = forfeited - taken
            touch(record)
            offset -= taken

        # ---- hops three and four -------------------------------------------
        account = calc.account_of_order(order)
        if account is not None:
            calc.recompute_account(account)
            calc.evaluate_credit_posture(account)
        if order["job_purchase_order_id"]:
            po = db.get("job_purchase_orders", order["job_purchase_order_id"])
            if po is not None:
                calc.recompute_po(po)
    return respond(serial.claim_case(claim))


# --------------------------------------------------------------------------
# Container returns (PRD 3.8)
# --------------------------------------------------------------------------
@bp.get("/container-returns")
def list_containers():
    ctx = auth(*CONTAINER_READ_ROLES)
    order_id = arg("material_order_id")
    container_type = arg("container_type")
    status = arg("status")
    rows = []
    for record in db.container_returns.values():
        if order_id is not None and record["material_order_id"] != order_id:
            continue
        if container_type is not None and record["container_type"] != container_type:
            continue
        if status is not None and record["status"] != status:
            continue
        rows.append(record)
    rows = contractor_filter(
        ctx, rows,
        lambda r: (db.get("material_orders", r["material_order_id"]) or {}).get(
            "contractor_account_id"))
    return render_list(rows, serial.container_return)


@bp.get("/container-returns/<container_return_id>")
def read_container(container_return_id):
    ctx = auth(*CONTAINER_READ_ROLES)
    record = db.get("container_returns", container_return_id)
    if record is not None:
        scope_via_order(ctx, db.get("material_orders", record["material_order_id"]))
    require(record, "container_returns")
    return respond(serial.container_return(record))


@bp.post("/container-returns/<container_return_id>/receive")
def receive_containers(container_return_id):
    auth("YardLoader")
    data = body()
    count = req_int(data, "returned_count")
    record = require(db.get("container_returns", container_return_id),
                     "container_returns")
    if record["status"] in ("CLOSED", "FORFEITED"):
        fail("ERR_CONTAINER_RETURN_CLOSED", "Record is %s." % record["status"])

    cumulative = int(record["returned_count"]) + count
    if count < 1 or cumulative > int(record["issued_count"]):
        fail("ERR_RETURN_COUNT_EXCEEDS_ISSUED",
             "The returned count does not fit the issued count.")

    received_at = db.clock
    record["returned_count"] = cumulative
    record["last_received_at"] = received_at
    record["refund_cents"] = int(record["refund_cents"]) + calc.refund_delta_cents(
        record, count, received_at)
    if cumulative >= int(record["issued_count"]):
        record["status"] = "CLOSED"
        record["forfeited_cents"] = (calc.full_deposit_cents(record)
                                    - int(record["refund_cents"]))
    else:
        record["status"] = "PARTIALLY_RETURNED"
    touch(record)

    order = db.get("material_orders", record["material_order_id"])
    account = calc.account_of_order(order) if order is not None else None
    if account is not None:
        calc.recompute_account(account)
    return respond(serial.container_return(record))


@bp.post("/container-returns/<container_return_id>/forfeit")
def forfeit_containers(container_return_id):
    auth("YardAdmin")
    record = require(db.get("container_returns", container_return_id),
                     "container_returns")
    if record["status"] in ("CLOSED", "FORFEITED"):
        fail("ERR_CONTAINER_RETURN_CLOSED", "Record is %s." % record["status"])
    record["forfeited_cents"] = (calc.full_deposit_cents(record)
                                - int(record["refund_cents"]))
    record["status"] = "FORFEITED"
    touch(record)

    order = db.get("material_orders", record["material_order_id"])
    account = calc.account_of_order(order) if order is not None else None
    if account is not None:
        calc.recompute_account(account)
    return respond(serial.container_return(record))

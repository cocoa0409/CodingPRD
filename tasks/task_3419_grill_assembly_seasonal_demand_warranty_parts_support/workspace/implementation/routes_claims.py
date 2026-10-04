"""WarrantyClaim intake, adjudication and settlement (PRD §3.7)."""

from datetime import timedelta

from flask import Blueprint, request

import clock
import derive
from auth import authenticate, check_ownership, require_role
from constants import (
    CLAIM_COMPONENTS,
    GOODWILL_CAP_CENTS,
    LABOR_ALLOWANCE_BY_COMPONENT,
    PART_COST_BY_COMPONENT,
    REOPEN_WINDOW_DAYS,
)
from errors import api_error, not_found, validation
from serialize import claim_out
from store import db, new_entity, next_seq, touch
from util import as_int, get_body, ok, ok_list, paginate, req_str, require

bp = Blueprint("warranty_claims", __name__, url_prefix="/grillops")

VALID_FROM = {
    "REVIEW": ("SUBMITTED", "REOPENED"),
    "REQUEST_INFO": ("UNDER_REVIEW",),
    "SUBMIT_INFO": ("INFO_REQUESTED",),
    "ESCALATE": ("UNDER_REVIEW",),
    "APPROVE": ("UNDER_REVIEW", "ESCALATED"),
    "DENY": ("UNDER_REVIEW", "ESCALATED"),
    "REOPEN": ("DENIED",),
    "SETTLE": ("APPROVED",),
}


@bp.post("/warranty-claims")
def create_claim():
    _, role = authenticate()
    require_role(role, ("ServiceAgent",))
    data = get_body()
    # rung 3: body-carried sale reference
    sale_id = require(data, "sale_id")
    sale = db.sales.get(sale_id)
    if sale is None:
        raise not_found("SALE")
    # rung 5: registration is the gate
    if sale["status"] == "SOLD":
        raise api_error("ERR_SALE_NOT_REGISTERED", "proof of purchase has not been provided for this sale")
    if sale["status"] == "RETURNED":
        raise api_error("ERR_SALE_RETURNED", "claims cannot be filed against a RETURNED sale")
    # rung 6: body
    component = req_str(data, "component")
    if component not in CLAIM_COMPONENTS:
        raise validation("component must be one of BURNER, GRATE, ELECTRONICS, OTHER")
    failure_description = req_str(data, "failure_description")
    serial_number = data.get("serial_number")
    if serial_number is not None:
        if not isinstance(serial_number, str):
            raise validation("serial_number must be a string")
        if sale["serials"] and serial_number not in sale["serials"]:
            raise validation("serial_number must be a member of the sale's serials")
    model = db.models.get(sale["model_id"])
    now = clock.now()
    determination = derive.calc_coverage_determination(
        model, component, clock.parse_iso(sale["sold_at"]), now
    )
    claim = new_entity({
        "sale_id": sale["id"],
        "component": component,
        "failure_description": failure_description,
        "serial_number": serial_number,
        "claim_date": clock.iso_z(now),
        "coverage_determination": determination,  # stored at creation; never changes
        "goodwill": False,
        "provisional_settlement_cents": None,
        "final_settlement_cents": None,
        "settlement_delta_cents": None,
        "settlement_parts_order_id": None,
        "denied_at": None,
        "status": "SUBMITTED",
    })
    db.claims[claim["id"]] = claim
    return ok(claim_out(claim), status=201)


@bp.get("/sales/<sale_id>/warranty-claims")
def list_sale_claims(sale_id):
    user_id, role = authenticate()
    require_role(role, ("ServiceAgent", "PlannerAdmin", "ChannelRep"))
    sale = db.sales.get(sale_id)
    if sale is None:
        raise not_found("SALE")
    if role == "ChannelRep":
        check_ownership(user_id, sale["channel_account_id"])
    items = [c for c in db.claims.values() if c["sale_id"] == sale["id"]]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, total, limit, offset = paginate(items)
    return ok_list([claim_out(c) for c in page], total, limit, offset)


def _select_settlement_part(claim, sale):
    """The pinned selector: eligible -> ranked by unit_cost ASC, created_at ASC
    (never id). Returns the chosen PartSku or None when the pool is empty."""
    model = db.models.get(sale["model_id"])
    model_code = model["model_code"] if model is not None else None
    eligible = [
        p for p in db.parts.values()
        if p["component"] == claim["component"]
        and model_code in p["compatible_model_codes"]
        and p["status"] in ("AVAILABLE", "LOW_STOCK")
        and p["stock_quantity"] >= 1
    ]
    if not eligible:
        return None
    eligible.sort(key=lambda p: (p["unit_cost_cents"], p["created_at"], p["_seq"]))
    return eligible[0]


def _settle(claim, sale, actual_labor_cents):
    """SETTLE side effects: auto-create the settlement PartsOrder (when the
    selector finds a candidate), then compute final + delta."""
    part = _select_settlement_part(claim, sale)
    part_actual = None
    if part is None:
        claim["settlement_parts_order_id"] = None
        part_actual = PART_COST_BY_COMPONENT[claim["component"]]  # schedule stands in
    else:
        fulfillment = "WARRANTY" if claim["coverage_determination"] == "IN_COVERAGE" else "GOODWILL"
        order = new_entity({
            "part_id": part["id"],
            "sale_id": sale["id"],
            "warranty_claim_id": claim["id"],
            "fulfillment_type": fulfillment,
            "quantity": 1,
            "resolved_part_id": part["id"],
            "free_of_charge": True,
            "total_cost_cents": part["unit_cost_cents"],
            "status": "REQUESTED",
            "seq_no": next_seq(),
        })
        db.parts_orders[order["id"]] = order
        # synchronous resolution within the settle: stock decrements now
        part["stock_quantity"] -= 1
        derive.derive_part_status(part)
        touch(part)
        order["status"] = "ALLOCATED"
        touch(order)
        claim["settlement_parts_order_id"] = order["id"]
        part_actual = order["total_cost_cents"]
    claim["final_settlement_cents"] = part_actual + actual_labor_cents
    claim["settlement_delta_cents"] = claim["final_settlement_cents"] - claim["provisional_settlement_cents"]
    claim["status"] = "SETTLED"


@bp.post("/warranty-claims/<claim_id>/adjudicate")
def adjudicate_claim(claim_id):
    _, role = authenticate()
    require_role(role, ("ServiceAgent",))
    claim = db.claims.get(claim_id)
    if claim is None:
        raise not_found("CLAIM")
    data = get_body()
    action = require(data, "action")
    if action not in VALID_FROM:
        raise validation("action must be one of REVIEW, REQUEST_INFO, SUBMIT_INFO, ESCALATE, APPROVE, DENY, REOPEN, SETTLE")
    # rung 5: valid-from state
    if claim["status"] not in VALID_FROM[action]:
        raise api_error(
            "ERR_CLAIM_NOT_ADJUDICATABLE",
            "action %s is not available from status %s" % (action, claim["status"]),
        )
    # rung 6: per-action body requirements
    goodwill_justification = data.get("goodwill_justification")
    if action == "APPROVE" and claim["coverage_determination"] == "OUT_OF_COVERAGE":
        if not goodwill_justification or not isinstance(goodwill_justification, str):
            raise validation("approving an OUT_OF_COVERAGE claim requires a non-empty goodwill_justification")
    actual_labor_cents = None
    if action == "SETTLE":
        actual_labor_cents = as_int(require(data, "actual_labor_cents"), "actual_labor_cents")
        if actual_labor_cents < 0:
            raise validation("actual_labor_cents must be >= 0")
    # rung 8: reopen window
    if action == "REOPEN":
        deadline = clock.parse_iso(claim["denied_at"]) + timedelta(days=REOPEN_WINDOW_DAYS)
        if clock.now() > deadline:
            raise api_error("ERR_REOPEN_WINDOW_EXPIRED", "the 30-day reopen window has elapsed")
    # rung 10: goodwill cap applies only to approval straight from UNDER_REVIEW
    if action == "APPROVE":
        provisional = (
            PART_COST_BY_COMPONENT[claim["component"]]
            + LABOR_ALLOWANCE_BY_COMPONENT[claim["component"]]
        )
        if claim["status"] == "UNDER_REVIEW" and provisional > GOODWILL_CAP_CENTS:
            raise api_error("ERR_GOODWILL_CAP_EXCEEDED", "provisional settlement exceeds the goodwill cap; escalate first")

    if action == "REVIEW":
        claim["status"] = "UNDER_REVIEW"
    elif action == "REQUEST_INFO":
        claim["status"] = "INFO_REQUESTED"
    elif action == "SUBMIT_INFO":
        claim["status"] = "UNDER_REVIEW"
    elif action == "ESCALATE":
        claim["status"] = "ESCALATED"
    elif action == "DENY":
        claim["status"] = "DENIED"
        claim["denied_at"] = clock.iso_z(clock.now())
    elif action == "REOPEN":
        claim["status"] = "REOPENED"
    elif action == "APPROVE":
        claim["provisional_settlement_cents"] = provisional
        if claim["coverage_determination"] in ("OUT_OF_COVERAGE", "GOODWILL_ELIGIBLE"):
            claim["goodwill"] = True
        claim["status"] = "APPROVED"
    elif action == "SETTLE":
        sale = db.sales.get(claim["sale_id"])
        _settle(claim, sale, actual_labor_cents)
    touch(claim)
    return ok(claim_out(claim))

"""Warranty claims: intake (window + fraud flag at creation), review, and
decisions including the SAME_COLORWAY / NEAREST_AVAILABLE / CREDIT_EQUIVALENT
replacement resolution."""
from datetime import timedelta
from flask import Blueprint, request

from auth import context, forbidden, require_roles
from calc import add_months, drop_unallocated_units, refresh_drop
from constants import FRAUD_PRIOR_THRESHOLD, FRAUD_WINDOW_DAYS
from envelope import (
    get_body, new_entity, opt_dt, opt_str, req_enum, req_str, sort_created,
    success, success_list, touch,
)
from errors import fail
from serialize import ser_claim
from store import DB, get_clock

bp = Blueprint("claims", __name__)

COMPONENTS = ("LID", "INSULATION", "HARDWARE")
OUTCOMES = ("APPROVE_REPAIR", "APPROVE_REPLACEMENT", "DENY")

WARRANTY_MONTHS_FIELD = {
    "LID": "warranty_months_lid",
    "INSULATION": "warranty_months_insulation",
    "HARDWARE": "warranty_months_hardware",
}


def load_claim(claim_id):
    c = DB.claims.get(claim_id)
    if c is None:
        fail("ERR_CLAIM_NOT_FOUND", "no warranty claim with id %s" % claim_id)
    return c


def _claimant_key(source, dealer_id, buyer_ref):
    return ("DEALER", dealer_id) if source == "DEALER" else ("DTC", buyer_ref)


@bp.post("/drinkware/warranty-claims")
def create_claim():
    uid, role = context()
    require_roles(role, ["Buyer", "Dealer", "WarrantyAgent"])
    body = get_body()
    claim_source = req_enum(body, "claim_source", ("DTC", "DEALER"))
    # Ownership (priority 2): Buyer files DTC claims under its own buyer_ref;
    # Dealer files DEALER claims under its own dealer id.
    if role == "Buyer" and claim_source != "DTC":
        forbidden("Buyer role may file only DTC claims")
    if role == "Dealer" and claim_source != "DEALER":
        forbidden("Dealer role may file only DEALER claims")
    serial_number = req_str(body, "serial_number")
    component = req_enum(body, "component", COMPONENTS)
    failure_description = req_str(body, "failure_description")
    dealer_id = opt_str(body, "dealer_id")
    buyer_ref = opt_str(body, "buyer_ref")
    order_id = opt_str(body, "order_id")
    product_line_id = opt_str(body, "product_line_id")
    purchase_date = opt_dt(body, "purchase_date")
    # Conditionally-required fields.
    if claim_source == "DEALER" and dealer_id is None:
        fail("ERR_INVALID_REQUEST", "dealer_id is required when claim_source is DEALER")
    if claim_source == "DTC" and buyer_ref is None:
        fail("ERR_INVALID_REQUEST", "buyer_ref is required when claim_source is DTC")
    if order_id is None and (product_line_id is None or purchase_date is None):
        fail("ERR_INVALID_REQUEST",
             "product_line_id and purchase_date are required when order_id is absent")
    if role == "Buyer" and buyer_ref != uid:
        forbidden("Buyer role may file claims only for its own buyer_ref")
    if role == "Dealer" and dealer_id != uid:
        forbidden("Dealer role may file claims only for its own dealer id")
    # Body foreign keys resolve in declared input order.
    if claim_source == "DEALER" and dealer_id not in DB.dealers:
        fail("ERR_DEALER_NOT_FOUND", "no dealer with id %s" % dealer_id)
    order = None
    if order_id is not None:
        order = DB.orders.get(order_id)
        if order is None:
            fail("ERR_ORDER_NOT_FOUND", "no customization order with id %s" % order_id)
    line = None
    if order is not None:
        line = DB.product_lines.get(order["product_line_id"])
    elif product_line_id is not None:
        line = DB.product_lines.get(product_line_id)
        if line is None:
            fail("ERR_PRODUCT_LINE_NOT_FOUND",
                 "no product line with id %s" % product_line_id)
    if order is not None and order["schedule_status"] != "COMPLETE":
        fail("ERR_INVALID_STATE_TRANSITION",
             "claims on a customized order require schedule_status COMPLETE")
    if order is not None and claim_source == "DTC" and order["buyer_ref"] != buyer_ref:
        fail("ERR_COLORWAY_NOT_AVAILABLE",
             "the claim's buyer must match the order's buyer")
    # Warranty anchor and expiry (calendar months from the product line).
    anchor = order["completed_at"] if order is not None else purchase_date
    months = line[WARRANTY_MONTHS_FIELD[component]]
    expires = add_months(anchor, months)
    filed_at = get_clock()
    if not (filed_at < expires):
        fail("ERR_WARRANTY_EXPIRED",
             "the claim was filed at or after the component's warranty expiry")
    # Fraud flag: >= 3 other non-DENIED claims from this claimant within the
    # trailing 365 days. The window is inclusive of the filing instant —
    # claims already on file at the same logical-clock tick count as priors.
    key = _claimant_key(claim_source, dealer_id, buyer_ref)
    window_start = filed_at - timedelta(days=FRAUD_WINDOW_DAYS)
    prior = 0
    for c in DB.claims.values():
        if c["status"] == "DENIED":
            continue
        if _claimant_key(c["claim_source"], c["dealer_id"], c["buyer_ref"]) != key:
            continue
        if window_start <= c["filed_at"] <= filed_at:
            prior += 1
    claim = new_entity({
        "claim_source": claim_source,
        "dealer_id": dealer_id,
        "buyer_ref": buyer_ref,
        "order_id": order_id,
        "product_line_id": product_line_id,
        "serial_number": serial_number,
        "component": component,
        "failure_description": failure_description,
        "purchase_date": purchase_date,
        "filed_at": filed_at,
        "warranty_anchor_at": anchor,
        "warranty_expires_at": expires,
        "fraud_flag": prior >= FRAUD_PRIOR_THRESHOLD,
        "replacement_colorway_resolution": None,
        "credit_equivalent_cents": None,
        "status": "FILED",
        "decision_reason": None,
    })
    DB.claims[claim["id"]] = claim
    return success(ser_claim(claim), 201)


@bp.get("/drinkware/warranty-claims/<claim_id>")
def get_claim(claim_id):
    uid, role = context()
    require_roles(role, ["WarrantyAgent", "PlatformAdmin", "Dealer", "Buyer"])
    claim = load_claim(claim_id)
    if role == "Dealer" and claim["dealer_id"] != uid:
        forbidden("Dealer role may read only its own claims")
    if role == "Buyer" and claim["buyer_ref"] != uid:
        forbidden("Buyer role may read only its own claims")
    return success(ser_claim(claim))


@bp.get("/drinkware/warranty-claims")
def list_claims():
    _, role = context()
    require_roles(role, ["WarrantyAgent", "PlatformAdmin"])
    dealer_id = request.args.get("dealer_id")
    buyer_ref = request.args.get("buyer_ref")
    order_id = request.args.get("order_id")
    product_line_id = request.args.get("product_line_id")
    status = request.args.get("status")
    items = sort_created(list(DB.claims.values()))
    if dealer_id is not None:
        items = [c for c in items if c["dealer_id"] == dealer_id]
    if buyer_ref is not None:
        items = [c for c in items if c["buyer_ref"] == buyer_ref]
    if order_id is not None:
        items = [c for c in items if c["order_id"] == order_id]
    if product_line_id is not None:
        items = [c for c in items if c["product_line_id"] == product_line_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return success_list([ser_claim(c) for c in items])


@bp.post("/drinkware/warranty-claims/<claim_id>/start-review")
def start_review(claim_id):
    _, role = context()
    require_roles(role, ["WarrantyAgent"])
    claim = load_claim(claim_id)
    get_body()
    if claim["status"] != "FILED":
        fail("ERR_INVALID_STATE_TRANSITION", "only a FILED claim can enter review")
    claim["status"] = "UNDER_REVIEW"
    touch(claim)
    return success(ser_claim(claim))


@bp.post("/drinkware/warranty-claims/<claim_id>/decide")
def decide_claim(claim_id):
    _, role = context()
    require_roles(role, ["WarrantyAgent"])
    claim = load_claim(claim_id)
    body = get_body()
    outcome = req_enum(body, "outcome", OUTCOMES)
    decision_reason = req_str(body, "decision_reason")
    if claim["status"] not in ("FILED", "UNDER_REVIEW"):
        fail("ERR_INVALID_STATE_TRANSITION", "the claim is already decided")
    if claim["fraud_flag"] and claim["status"] == "FILED":
        fail("ERR_FRAUD_REVIEW_REQUIRED",
             "fraud-flagged claims must pass through review before a decision")
    claim["decision_reason"] = decision_reason
    if outcome == "DENY":
        claim["status"] = "DENIED"
    elif outcome == "APPROVE_REPAIR":
        claim["status"] = "APPROVED_REPAIR"
    else:
        claim["status"] = "APPROVED_REPLACEMENT"
        # Resolve where the replacement unit comes from.
        line = None
        same_colorway = False
        if claim["order_id"] is not None:
            order = DB.orders.get(claim["order_id"])
            if order is not None:
                line = DB.product_lines.get(order["product_line_id"])
                drop = DB.drops.get(order["colorway_drop_id"])
                if drop is not None:
                    refresh_drop(drop)
                    if (drop["status"] in ("ALLOCATION_LOCKED", "LIVE")
                            and drop_unallocated_units(drop) >= 1):
                        same_colorway = True
        elif claim["product_line_id"] is not None:
            line = DB.product_lines.get(claim["product_line_id"])
        if same_colorway:
            claim["replacement_colorway_resolution"] = "SAME_COLORWAY"
            # The drop's warranty_reserved_units rises by one via the ledger.
        elif line is not None and line["status"] == "ACTIVE":
            claim["replacement_colorway_resolution"] = "NEAREST_AVAILABLE"
        else:
            claim["replacement_colorway_resolution"] = "CREDIT_EQUIVALENT"
            claim["credit_equivalent_cents"] = line["map_price_cents"] if line is not None else 0
    touch(claim)
    return success(ser_claim(claim))

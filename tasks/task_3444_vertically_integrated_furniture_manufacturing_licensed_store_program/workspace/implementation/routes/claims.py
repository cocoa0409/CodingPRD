"""Warranty claims (PRD §3.7): bounded review loop, adjudication, chargebacks."""
from datetime import timedelta

from flask import Blueprint, request

from constants import CLAIM_STATUSES, CLAIM_TYPES, INFO_REQUEST_MAX, WARRANTY_WINDOW_DAYS
from db import store
from errors import err
from middleware import auth, require_licensee_owner, require_role
from routes.orders import get_order
from services import calc
from util import (
    get_body, new_record, now_dt, ok_list, ok_object, opt_str, paginate,
    req_enum, req_str, serialize, touch,
)

bp = Blueprint("claims", __name__)


def get_claim(cid):
    c = store.claims.get(cid)
    if c is None:
        err("ERR_CLAIM_NOT_FOUND", "unknown warranty claim id")
    return c


@bp.route("/api/warranty-claims", methods=["POST"])
def create_claim():
    uid, role = auth()
    data = get_body()
    order_id = req_str(data, "supply_order_id")
    claim_type = req_enum(data, "claim_type", CLAIM_TYPES)
    description = req_str(data, "description")
    require_role(role, ["LicenseeManager"])
    order = get_order(order_id)
    require_licensee_owner(uid, role, order.get("licensee_id"))
    # State guard: claims file against DELIVERED licensee orders only.
    if order["fulfillment_state"] != "DELIVERED" or order["buyer_type"] != "LICENSEE":
        err("ERR_INVALID_TRANSITION", "claims require a DELIVERED licensee order")
    # Temporal guard: filing window measured from delivered_at; boundary day passes.
    window_days = WARRANTY_WINDOW_DAYS[claim_type]
    if now_dt() > order["delivered_at"] + timedelta(days=window_days):
        err("ERR_WARRANTY_WINDOW_EXPIRED", "claim filed after its %d-day window" % window_days)
    rec = new_record()
    rec.update({
        "supply_order_id": order_id,
        "licensee_id": order["licensee_id"],
        "claim_type": claim_type,
        "description": description,
        "status": "UNDER_REVIEW",
        "info_request_count": 0,
        "decision": None,
        "decision_note": None,
        "chargeback_cents": None,
        "resolved_at": None,
    })
    store.claims[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.route("/api/warranty-claims/<cid>", methods=["GET"])
def fetch_claim(cid):
    auth()
    return ok_object(serialize(get_claim(cid)), 200)


@bp.route("/api/warranty-claims", methods=["GET"])
def list_claims():
    auth()
    items = list(store.claims.values())
    for field in ("licensee_id", "supply_order_id", "status", "claim_type"):
        value = request.args.get(field)
        if value is not None:
            items = [c for c in items if c[field] == value]
    page, pagination = paginate(items)
    return ok_list([serialize(c) for c in page], pagination)


def _apply_chargeback(claim, bumped):
    """APPROVED DAMAGE_IN_TRANSIT -> chargeback on the licensee ledger."""
    if claim["claim_type"] != "DAMAGE_IN_TRANSIT":
        return
    order = store.orders.get(claim["supply_order_id"])
    if order is None or order["final_total_cents"] is None:
        return
    claim["chargeback_cents"] = calc.chargeback_for(order["final_total_cents"])
    lic = store.licensees.get(claim["licensee_id"])
    if lic is not None and calc.recompute_ledger(lic):
        touch(lic, bumped)


@bp.route("/api/warranty-claims/<cid>/transition", methods=["POST"])
def transition_claim(cid):
    uid, role = auth()
    data = get_body()
    to_state = req_enum(data, "to_state", CLAIM_STATUSES)
    decision_note = opt_str(data, "decision_note", None)
    opt_str(data, "info_note", None)  # accepted; no field stores it
    approved_parts = data.get("approved_parts")
    if to_state == "PARTS_ORDERED":
        if (not isinstance(approved_parts, list) or not approved_parts
                or any(not isinstance(p, dict) or not isinstance(p.get("sku"), str)
                       or type(p.get("quantity")) is not int or p["quantity"] <= 0
                       for p in approved_parts)):
            err("ERR_VALIDATION", "approved_parts must be a non-empty array of {sku, quantity>0}")
    require_role(role, ["WarrantyAdmin", "LicenseeManager"])
    if to_state == "UNDER_REVIEW":
        if role != "LicenseeManager":
            err("ERR_FORBIDDEN_ROLE", "only the owning LicenseeManager answers info requests")
    elif role != "WarrantyAdmin":
        err("ERR_FORBIDDEN_ROLE", "only WarrantyAdmin adjudicates claims")
    claim = get_claim(cid)
    if to_state == "UNDER_REVIEW":
        require_licensee_owner(uid, role, claim["licensee_id"])

    bumped = set()
    if to_state == "INFO_REQUESTED":
        if claim["status"] != "UNDER_REVIEW":
            err("ERR_INVALID_TRANSITION", "INFO_REQUESTED requires status UNDER_REVIEW")
        if claim["info_request_count"] >= INFO_REQUEST_MAX:
            err("ERR_INFO_REQUEST_LIMIT_REACHED", "information budget exhausted (max 2)")
        claim["status"] = "INFO_REQUESTED"
        claim["info_request_count"] += 1
        if decision_note is not None:
            claim["decision_note"] = decision_note
        touch(claim, bumped)
    elif to_state == "UNDER_REVIEW":
        if claim["status"] != "INFO_REQUESTED":
            err("ERR_INVALID_TRANSITION", "UNDER_REVIEW requires status INFO_REQUESTED")
        claim["status"] = "UNDER_REVIEW"
        touch(claim, bumped)
    elif to_state == "RESOLVED":
        if claim["status"] != "UNDER_REVIEW":
            err("ERR_INVALID_TRANSITION", "RESOLVED requires status UNDER_REVIEW")
        claim["status"] = "RESOLVED"
        claim["decision"] = "APPROVED"
        if decision_note is not None:
            claim["decision_note"] = decision_note
        claim["resolved_at"] = now_dt()
        touch(claim, bumped)
        _apply_chargeback(claim, bumped)
    elif to_state == "PARTS_ORDERED":
        if claim["status"] != "UNDER_REVIEW":
            err("ERR_INVALID_TRANSITION", "PARTS_ORDERED requires status UNDER_REVIEW")
        claim["status"] = "PARTS_ORDERED"
        claim["decision"] = "APPROVED"
        if decision_note is not None:
            claim["decision_note"] = decision_note
        touch(claim, bumped)
        _apply_chargeback(claim, bumped)
        for p in approved_parts:
            part = new_record()
            part.update({
                "claim_id": claim["id"],
                "sku": p["sku"],
                "quantity": p["quantity"],
                "status": "QUEUED",
            })
            store.parts_orders[part["id"]] = part
    else:  # DENIED
        if claim["status"] != "UNDER_REVIEW":
            err("ERR_INVALID_TRANSITION", "DENIED requires status UNDER_REVIEW")
        claim["status"] = "DENIED"
        claim["decision"] = "DENIED"
        if decision_note is not None:
            claim["decision_note"] = decision_note
        touch(claim, bumped)
    return ok_object(serialize(claim), 200)

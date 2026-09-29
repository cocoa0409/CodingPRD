"""Customs audits, shrinkage write-offs and unaccounted-goods duty (PRD section 3.9)."""
from flask import Blueprint

import clock
import db
import response
from errors import ApiError
from middleware import actor, body, endpoint
from services import ledger, rent
from services.lookup import fetch, fetch_body, listing
from services.money import apply_bps, floor_bps
from services.scope import AUDIT_ROLES
from services.validate import PERIOD_CODE, req_int, req_string

bp = Blueprint("audits", __name__)

TOLERANCE_BPS = 200
REPEAT_FINDING_ROUNDS = 3
REPEAT_FINDING_MULTIPLIER = 2


@bp.post("/customs-audits")
@endpoint("StockController")
def create_audit():
    payload = body()
    terminal = fetch_body("terminals", "terminal_id", payload)
    item = fetch_body("stock_items", "stock_item_id", payload)
    period_code = req_string(payload, "period_code", pattern=PERIOD_CODE)
    audit = db.base()
    audit.update({
        "terminal_id": terminal["id"],
        "stock_item_id": item["id"],
        "period_code": period_code,
        "preparer_user_id": actor(),
        "auditor_user_id": None,
        "counted_qty": None,
        "expected_qty_snapshot": None,
        "shrinkage_qty": 0,
        "assessable_qty": 0,
        "assessed_duty_cents": 0,
        "round_count": 1,
        "info_request_note": None,
        "status": "DRAFT",
        "closed_at": None,
    })
    db.audits[audit["id"]] = audit
    return response.created(db.public(audit))


@bp.get("/customs-audits/<audit_id>")
@endpoint(*AUDIT_ROLES)
def get_audit(audit_id):
    return response.single(db.public(fetch("audits", audit_id)))


@bp.get("/customs-audits")
@endpoint(*AUDIT_ROLES)
def list_audits():
    rows, limit, offset, total = listing(
        db.audits, ("terminal_id", "stock_item_id", "period_code", "status")
    )
    return response.collection(rows, limit, offset, total)


@bp.post("/customs-audits/<audit_id>/submit")
@endpoint("StockController")
def submit_audit(audit_id):
    audit = fetch("audits", audit_id)
    counted_qty = req_int(body(), "counted_qty", minimum=0)
    if audit["status"] not in ("DRAFT", "INFO_REQUESTED"):
        raise ApiError("ERR_AUDIT_NOT_SUBMITTED")
    item = db.stock_items[audit["stock_item_id"]]
    if counted_qty > item["on_hand_qty"]:
        raise ApiError("ERR_COUNTED_QTY_EXCEEDS_EXPECTED")
    if audit["status"] == "INFO_REQUESTED":
        audit["round_count"] += 1
    audit["counted_qty"] = counted_qty
    audit["expected_qty_snapshot"] = item["on_hand_qty"]
    audit["status"] = "SUBMITTED"
    db.touch(audit)
    return response.single(db.public(audit))


@bp.post("/customs-audits/<audit_id>/request-info")
@endpoint("CustomsAuditor")
def request_info(audit_id):
    audit = fetch("audits", audit_id)
    note = req_string(body(), "info_request_note")
    if audit["status"] != "SUBMITTED":
        raise ApiError("ERR_AUDIT_NOT_SUBMITTED")
    if actor() == audit["preparer_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    audit["info_request_note"] = note
    audit["status"] = "INFO_REQUESTED"
    db.touch(audit)
    return response.single(db.public(audit))


@bp.post("/customs-audits/<audit_id>/close")
@endpoint("CustomsAuditor")
def close_audit(audit_id):
    audit = fetch("audits", audit_id)
    if audit["status"] != "SUBMITTED":
        raise ApiError("ERR_AUDIT_NOT_SUBMITTED")
    if actor() == audit["preparer_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    agreement = rent.agreement_for_period(audit["terminal_id"], audit["period_code"])
    if agreement is None or agreement["status"] != "CLOSED":
        raise ApiError("ERR_AUDIT_PERIOD_NOT_CLOSED")
    item = db.stock_items[audit["stock_item_id"]]
    product = db.products[item["product_id"]]
    snapshot = audit["expected_qty_snapshot"] or 0
    counted = audit["counted_qty"] or 0
    shrinkage = max(0, snapshot - counted)
    tolerance = floor_bps(snapshot, TOLERANCE_BPS)
    assessable = max(0, shrinkage - tolerance)
    per_unit = apply_bps(product["unit_price_cents"],
                        product["duty_rate_bps"] + product["vat_rate_bps"])
    multiplier = (REPEAT_FINDING_MULTIPLIER
                  if audit["round_count"] >= REPEAT_FINDING_ROUNDS else 1)
    assessed = assessable * per_unit * multiplier
    audit["shrinkage_qty"] = shrinkage
    audit["assessable_qty"] = assessable
    audit["assessed_duty_cents"] = assessed
    audit["auditor_user_id"] = actor()
    audit["closed_at"] = clock.now_iso()
    if assessable == 0:
        audit["status"] = "CLOSED_CLEAN"
        audit["assessed_duty_cents"] = 0
        item["last_reconciled_at"] = clock.now_iso()
        db.touch(item)
        db.touch(audit)
        return response.single(db.public(audit))
    audit["status"] = "CLOSED_ASSESSED"
    terminal = db.terminals[audit["terminal_id"]]
    terminal["unaccounted_duty_liability_cents"] += assessed
    db.touch(terminal)
    ledger.append(item, "SHRINKAGE_WRITE_OFF", -shrinkage, "CUSTOMS_AUDIT",
                  audit["id"], actor())
    item["last_reconciled_at"] = clock.now_iso()
    while item["reserved_qty"] > item["on_hand_qty"]:
        candidates = db.ordered(
            db.pre_orders,
            lambda p: p["stock_item_id"] == item["id"] and p["status"] == "RESERVED",
        )
        if not candidates:
            break
        pre_order = candidates[0]
        pre_order["status"] = "RELEASED"
        pre_order["closed_at"] = clock.now_iso()
        db.touch(pre_order)
        ledger.append(item, "RESERVATION_RELEASE", -pre_order["qty"], "PRE_ORDER",
                      pre_order["id"], actor())
    db.touch(audit)
    return response.single(db.public(audit))

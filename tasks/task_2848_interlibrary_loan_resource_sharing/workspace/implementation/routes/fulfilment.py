"""Parcels, the hold shelf and loan lifecycle (PRD 3.6, 3.7)."""
from flask import Blueprint

from db import add_days, base_row, db, now, touch
from errors import ApiError
from middleware import (ACCOUNTANT, ADMIN, ILL_STAFF, PARTNER_AGENT, PATRON, auth,
                        get_loan, get_shipment, own_loan, own_shipment)
from response import ok_row
from services import calc, derive
from validate import bad, body, opt_int, req_enum, req_int

bp = Blueprint("fulfilment", __name__)

CONDITIONS = ("OK", "DAMAGED", "LOST")
SETTLEMENT_ACTIONS = ("PAY", "WAIVE")
BILLABLE_STATES = ("FINE_ACCRUED", "DAMAGE_BILLED", "LOST_BILLED")


def loan_for_request(request_id):
    rows = [l for l in db.loans.values() if l["request_id"] == request_id]
    rows.sort(key=lambda l: (l["created_at"], l["_seq"]))
    return rows[-1] if rows else None


def create_return_parcel(req):
    row = base_row()
    row.update({
        "request_id": req["id"],
        "direction": "RETURN",
        "carrier": None,
        "tracking_code": None,
        "insured_value_cents": 0,
        "shipped_at": now(),
        "received_at": None,
        "confirmed_at": None,
        "status": "IN_TRANSIT",
    })
    db.shipments[row["id"]] = row
    return row


@bp.route("/ill/shipments/<shipment_id>/receive", methods=["POST"])
def receive_shipment(shipment_id):
    auth(ILL_STAFF)
    shipment = get_shipment(shipment_id)
    # rung 42
    if shipment["direction"] != "INBOUND" or shipment["status"] != "IN_TRANSIT":
        raise ApiError("ERR_SHIPMENT_INVALID_STATE")
    req = db.requests[shipment["request_id"]]
    patron = db.patrons[req["patron_id"]]
    bib = db.bib_items.get(req["bib_item_id"]) or {}
    partner = db.partners.get(req.get("committed_partner_id")) or {}
    period_days = req["committed_loan_period_days"]
    # rung 64: aggregate loan-window capacity, tested before anything is written
    window_start = now()
    window_end = add_days(now(), period_days)
    counted = [l for l in derive.patron_loans(patron["id"])
               if l["custody_status"] in ("AWAITING_PICKUP", "WITH_PATRON")]
    overlaps = sum(1 for l in counted
                   if l["received_at"] <= window_end and window_start <= l["due_at"])
    if overlaps + 1 > patron["max_concurrent_loans"]:
        raise ApiError("ERR_PATRON_LOAN_WINDOW_CAPACITY")

    shipment["status"] = "RECEIVED"
    shipment["received_at"] = now()
    touch(shipment)
    list_price = bib.get("list_price_cents") or 0
    row = base_row()
    row.update({
        "request_id": req["id"],
        "inbound_tracking_code": shipment.get("tracking_code"),
        "received_at": now(),
        "due_at": window_end,
        "original_due_at": window_end,
        "renewal_count": 0,
        "max_renewals": partner.get("max_renewals", 0),
        "renewals_allowed": bool(partner.get("allows_renewals", False)),
        "pickup_expires_at": add_days(now(), calc.HOLD_SHELF_DAYS),
        "picked_up_at": None,
        "return_prepared_at": None,
        "custody_status": "AWAITING_PICKUP",
        "billing_status": "NO_CHARGE",
        "recall_status": "NONE",
        "recall_due_at": None,
        "replacement_cost_cents": (list_price if list_price
                                   else calc.DEFAULT_REPLACEMENT_COST_CENTS),
        "overdue_fine_cents": 0,
        "damage_fee_cents": 0,
        "lost_replacement_cents": 0,
        "lender_processing_fee_cents": 0,
        "total_charge_cents": 0,
        "paid_overdue_cents": 0,
        "paid_damage_cents": 0,
        "paid_lost_cents": 0,
        "paid_processing_cents": 0,
        "total_paid_cents": 0,
        "outstanding_cents": 0,
    })
    db.loans[row["id"]] = row
    req["status"] = "ON_HOLD_SHELF"
    req["fulfilled_at"] = now()
    touch(req)
    derive.notify(req, "READY_FOR_PICKUP",
                  "Ready for pickup: %s" % bib.get("title", ""))
    return ok_row(row, 201)


@bp.route("/ill/shipments/<shipment_id>/lender-confirm", methods=["POST"])
def lender_confirm(shipment_id):
    user_id, role = auth(PARTNER_AGENT, ILL_STAFF)
    shipment = get_shipment(shipment_id)
    own_shipment(shipment, user_id, role)
    data = body()
    condition = req_enum(data, "condition", CONDITIONS)
    damage_fee = opt_int(data, "damage_fee_cents", 0, 0)
    # rung 42
    if shipment["direction"] != "RETURN" or shipment["status"] != "IN_TRANSIT":
        raise ApiError("ERR_SHIPMENT_INVALID_STATE")
    req = db.requests[shipment["request_id"]]
    loan = loan_for_request(req["id"])
    # rung 82
    if condition == "DAMAGED" and loan is not None \
            and damage_fee > loan["replacement_cost_cents"]:
        raise ApiError("ERR_DAMAGE_FEE_EXCEEDS_REPLACEMENT")
    bib = db.bib_items.get(req["bib_item_id"]) or {}
    advance = req["status"] == "RETURN_IN_TRANSIT"
    shipment["confirmed_at"] = now()
    if condition == "OK":
        shipment["status"] = "CONFIRMED_OK"
        touch(shipment)
        if loan is not None:
            loan["custody_status"] = "RETURNED_TO_LENDER"
            touch(loan)
        if advance:
            req["status"] = "CLOSED"
            req["closed_at"] = now()
            touch(req)
        derive.recompute_patron_for_request(req, ("open_request_count",))
    elif condition == "DAMAGED":
        shipment["status"] = "CONFIRMED_DAMAGED"
        touch(shipment)
        if loan is not None:
            loan["custody_status"] = "RETURNED_TO_LENDER"
            loan["billing_status"] = "DAMAGE_BILLED"
            loan["damage_fee_cents"] = damage_fee
            loan["lender_processing_fee_cents"] = calc.LENDER_PROCESSING_FEE_CENTS
            derive.recompute_loan_money(loan)
            touch(loan)
        if advance:
            req["status"] = "CLOSED_WITH_DAMAGE"
            req["closed_at"] = now()
            touch(req)
        derive.notify(req, "DAMAGE_BILLED",
                      "Damage charge recorded: %s" % bib.get("title", ""))
        derive.recompute_patron_for_request(
            req, ("damaged_count", "lost_count", "unpaid_balance_cents",
                  "open_request_count", "final_risk_score"), block=True)
    else:
        shipment["status"] = "CONFIRMED_LOST"
        touch(shipment)
        if loan is not None:
            loan["custody_status"] = "DECLARED_LOST"
            loan["billing_status"] = "LOST_BILLED"
            loan["lost_replacement_cents"] = loan["replacement_cost_cents"]
            loan["lender_processing_fee_cents"] = calc.LENDER_PROCESSING_FEE_CENTS
            derive.recompute_loan_money(loan)
            touch(loan)
        if advance:
            req["status"] = "CLOSED_LOST"
            req["closed_at"] = now()
            touch(req)
        derive.notify(req, "LOST_BILLED",
                      "Replacement charge recorded: %s" % bib.get("title", ""))
        derive.recompute_patron_for_request(
            req, ("damaged_count", "lost_count", "unpaid_balance_cents",
                  "open_request_count", "final_risk_score"), block=True)
    return ok_row(shipment)


@bp.route("/ill/shipments/<shipment_id>", methods=["GET"])
def get_one_shipment(shipment_id):
    user_id, role = auth(PARTNER_AGENT, ILL_STAFF, ADMIN)
    shipment = get_shipment(shipment_id)
    own_shipment(shipment, user_id, role)
    return ok_row(shipment)


@bp.route("/ill/loans/<loan_id>/pickup", methods=["POST"])
def pickup_loan(loan_id):
    auth(ILL_STAFF)
    loan = get_loan(loan_id)
    # rung 43
    if loan["custody_status"] != "AWAITING_PICKUP":
        raise ApiError("ERR_LOAN_INVALID_CUSTODY_STATE")
    # rung 68
    if now() >= loan["pickup_expires_at"]:
        raise ApiError("ERR_PICKUP_WINDOW_EXPIRED")
    loan["custody_status"] = "WITH_PATRON"
    loan["picked_up_at"] = now()
    touch(loan)
    req = db.requests[loan["request_id"]]
    if req["status"] == "ON_HOLD_SHELF":
        req["status"] = "WITH_PATRON"
        touch(req)
    return ok_row(loan)


@bp.route("/ill/loans/<loan_id>/renewals", methods=["POST"])
def renew_loan(loan_id):
    user_id, role = auth(PATRON, ILL_STAFF)
    loan = get_loan(loan_id)
    own_loan(loan, user_id, role)
    # rung 43
    if loan["custody_status"] != "WITH_PATRON":
        raise ApiError("ERR_LOAN_INVALID_CUSTODY_STATE")
    # rung 65
    if loan["recall_status"] == "RECALL_BREACHED":
        raise ApiError("ERR_RECALL_OVERDUE")
    if loan["recall_status"] == "RECALL_ISSUED" and loan["recall_due_at"] is not None \
            and now() > loan["recall_due_at"]:
        raise ApiError("ERR_RECALL_OVERDUE")
    # rung 70
    if loan["recall_status"] != "NONE":
        raise ApiError("ERR_RENEWAL_BLOCKED_BY_RECALL")
    # rung 71
    if not loan["renewals_allowed"]:
        raise ApiError("ERR_RENEWALS_NOT_ALLOWED_BY_LENDER")
    # rung 72
    projected = min(add_days(loan["due_at"], calc.RENEWAL_DAYS),
                    add_days(loan["received_at"], calc.MAX_TOTAL_LOAN_DAYS))
    if loan["renewal_count"] >= loan["max_renewals"] or projected <= loan["due_at"]:
        raise ApiError("ERR_RENEWAL_CAP_REACHED")
    loan["due_at"] = projected
    loan["renewal_count"] += 1
    touch(loan)
    return ok_row(loan)


@bp.route("/ill/loans/<loan_id>/recalls", methods=["POST"])
def recall_loan(loan_id):
    user_id, role = auth(PARTNER_AGENT, ILL_STAFF)
    loan = get_loan(loan_id)
    own_loan(loan, user_id, role)
    data = body()
    grace_days = opt_int(data, "grace_days", calc.DEFAULT_RECALL_GRACE_DAYS, 0)
    if loan["custody_status"] not in ("AWAITING_PICKUP", "WITH_PATRON"):
        raise ApiError("ERR_LOAN_INVALID_CUSTODY_STATE")
    recall_due_at = add_days(now(), grace_days)
    loan["recall_status"] = "RECALL_ISSUED"
    loan["recall_due_at"] = recall_due_at
    if recall_due_at < loan["due_at"]:
        loan["due_at"] = recall_due_at
    touch(loan)
    req = db.requests[loan["request_id"]]
    bib = db.bib_items.get(req["bib_item_id"]) or {}
    derive.notify(req, "RECALL_ISSUED", "Recalled by lender: %s" % bib.get("title", ""))
    return ok_row(loan)


@bp.route("/ill/loans/<loan_id>/return", methods=["POST"])
def return_loan(loan_id):
    auth(ILL_STAFF)
    loan = get_loan(loan_id)
    # rung 43
    if loan["custody_status"] != "WITH_PATRON":
        raise ApiError("ERR_LOAN_INVALID_CUSTODY_STATE")
    req = db.requests[loan["request_id"]]
    loan["return_prepared_at"] = now()
    loan["custody_status"] = "RETURN_PREPARED"
    # the recall dimension resolves first
    if loan["recall_status"] == "RECALL_ISSUED":
        if loan["recall_due_at"] is not None and now() <= loan["recall_due_at"]:
            loan["recall_status"] = "RECALL_HONORED"
        else:
            loan["recall_status"] = "RECALL_BREACHED"
    breached = loan["recall_status"] == "RECALL_BREACHED"
    fine = calc.overdue_fine_cents(loan["due_at"], loan["return_prepared_at"], breached)
    loan["overdue_fine_cents"] = fine
    if fine > 0 and loan["billing_status"] == "NO_CHARGE":
        loan["billing_status"] = "FINE_ACCRUED"
    derive.recompute_loan_money(loan)
    touch(loan)
    create_return_parcel(req)
    req["status"] = "RETURN_IN_TRANSIT"
    touch(req)
    derive.recompute_patron_for_request(
        req, ("late_return_count", "unpaid_balance_cents", "final_risk_score"))
    return ok_row(loan)


@bp.route("/ill/loans/<loan_id>/declare-lost", methods=["POST"])
def declare_loan_lost(loan_id):
    auth(ILL_STAFF)
    loan = get_loan(loan_id)
    # rung 43
    if loan["custody_status"] != "WITH_PATRON":
        raise ApiError("ERR_LOAN_INVALID_CUSTODY_STATE")
    req = db.requests[loan["request_id"]]
    bib = db.bib_items.get(req["bib_item_id"]) or {}
    breached = loan["recall_status"] == "RECALL_BREACHED"
    loan["custody_status"] = "DECLARED_LOST"
    loan["billing_status"] = "LOST_BILLED"
    loan["lost_replacement_cents"] = loan["replacement_cost_cents"]
    loan["lender_processing_fee_cents"] = calc.LENDER_PROCESSING_FEE_CENTS
    loan["overdue_fine_cents"] = calc.overdue_fine_cents(loan["due_at"], now(),
                                                         breached)
    derive.recompute_loan_money(loan)
    touch(loan)
    req["status"] = "CLOSED_LOST"
    req["closed_at"] = now()
    touch(req)
    derive.notify(req, "LOST_BILLED",
                  "Item declared lost: %s" % bib.get("title", ""))
    derive.recompute_patron_for_request(
        req, ("lost_count", "unpaid_balance_cents", "open_request_count",
              "final_risk_score"), block=True)
    return ok_row(loan)


@bp.route("/ill/loans/<loan_id>/charge-settlements", methods=["POST"])
def settle_charges(loan_id):
    auth(ACCOUNTANT, ADMIN)
    loan = get_loan(loan_id)
    data = body()
    action = req_enum(data, "action", SETTLEMENT_ACTIONS)
    if action == "PAY":
        payment = req_int(data, "payment_cents", 0)
        buckets = (
            ("overdue_fine_cents", "paid_overdue_cents"),
            ("damage_fee_cents", "paid_damage_cents"),
            ("lost_replacement_cents", "paid_lost_cents"),
            ("lender_processing_fee_cents", "paid_processing_cents"),
        )
        remaining_total = sum(max(0, loan[charge] - loan[paid])
                              for charge, paid in buckets)
        # rung 81: nothing at all is written on an overpayment
        if payment > remaining_total:
            raise ApiError("ERR_OVERPAYMENT")
        left = payment
        for charge, paid in buckets:
            if left <= 0:
                break
            room = max(0, loan[charge] - loan[paid])
            applied = min(room, left)
            loan[paid] += applied
            left -= applied
        derive.recompute_loan_money(loan)
        if loan["outstanding_cents"] == 0 and loan["billing_status"] in BILLABLE_STATES:
            loan["billing_status"] = "CHARGE_SETTLED"
    else:
        if loan["billing_status"] not in BILLABLE_STATES:
            bad("A waiver requires an outstanding charge on the loan.")
        loan["billing_status"] = "CHARGE_WAIVED"
        derive.recompute_loan_money(loan)
    touch(loan)
    req = db.requests[loan["request_id"]]
    derive.recompute_patron_for_request(
        req, ("unpaid_balance_cents", "final_risk_score"))
    return ok_row(loan)


@bp.route("/ill/loans/<loan_id>", methods=["GET"])
def get_one_loan(loan_id):
    user_id, role = auth(PATRON, PARTNER_AGENT, ILL_STAFF, ACCOUNTANT, ADMIN)
    loan = get_loan(loan_id)
    own_loan(loan, user_id, role)
    return ok_row(loan)

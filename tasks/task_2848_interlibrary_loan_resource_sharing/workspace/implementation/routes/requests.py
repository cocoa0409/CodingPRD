"""Interlibrary loan request endpoints (PRD 3.3, 3.4, 3.8)."""
from flask import Blueprint

from db import base_row, db, now, touch
from errors import ApiError
from middleware import (ACCOUNTANT, ACQUISITIONS, ADMIN, ILL_STAFF, PARTNER_AGENT,
                        PATRON, auth, deny_owner, get_request, own_request)
from response import ok_row
from routes.common import filter_eq, list_response
from services import calc, derive
from validate import (bad, body, opt_int, q_enum, q_str, raw_id, req_enum,
                      req_instant, req_int, req_str)

bp = Blueprint("requests", __name__)

SERVICE_TYPES = ("LOAN", "COPY")
DELIVERY_MODES = ("PICKUP", "ELECTRONIC", "MAIL")
REQUEST_STATUSES = (
    "SUBMITTED", "COPYRIGHT_HOLD", "SOURCING", "OFFER_PENDING", "SUPPLY_COMMITTED",
    "IN_TRANSIT", "ON_HOLD_SHELF", "WITH_PATRON", "RETURN_IN_TRANSIT",
    "DELIVERED_ELECTRONIC", "ESCALATED_POD", "CLOSED", "CLOSED_WITH_DAMAGE",
    "CLOSED_LOST", "UNCLAIMED", "CANCELLED", "UNFILLED", "FILLED_BY_PURCHASE",
)
CANCELLABLE = ("COPYRIGHT_HOLD", "SOURCING", "OFFER_PENDING", "SUPPLY_COMMITTED",
               "ESCALATED_POD")
NOTIFICATION_KINDS = (
    "REQUEST_SUBMITTED", "COPYRIGHT_HOLD", "READY_FOR_PICKUP",
    "ELECTRONIC_DELIVERY_READY", "RECALL_ISSUED", "UNCLAIMED", "DAMAGE_BILLED",
    "LOST_BILLED", "REQUEST_UNFILLED", "POD_APPROVED", "PURCHASE_RECEIVED",
    "DELIVERY_EXPIRED", "REQUEST_CANCELLED",
)
CLEARANCE_STATUSES = ("ACTIVE", "VOIDED")
POD_STATUSES = ("PROPOSED", "APPROVED", "REJECTED", "RECEIVED", "CANCELLED")
DELIVERY_STATUSES = ("AVAILABLE", "EXPIRED", "EXHAUSTED")
SHIPMENT_STATUSES = ("IN_TRANSIT", "RECEIVED", "CONFIRMED_OK", "CONFIRMED_DAMAGED",
                     "CONFIRMED_LOST", "LOST_IN_TRANSIT")
CUSTODY_STATUSES = ("AWAITING_PICKUP", "WITH_PATRON", "RETURN_PREPARED",
                    "UNCLAIMED_RETURN_PREPARED", "RETURNED_TO_LENDER",
                    "DECLARED_LOST")


def new_clearance(req, issn, method, sequence_in_year, royalty_cents,
                  approved_by_user_id=None):
    row = base_row()
    row.update({
        "request_id": req["id"],
        "issn": issn,
        "calendar_year": now().year,
        "method": method,
        "sequence_in_year": sequence_in_year,
        "royalty_cents": royalty_cents,
        "pages_covered": req.get("pages_requested"),
        "approved_by_user_id": approved_by_user_id,
        "status": "ACTIVE",
    })
    db.clearances[row["id"]] = row
    return row


@bp.route("/ill/requests", methods=["POST"])
def create_request():
    user_id, role = auth(PATRON, ILL_STAFF)
    data = body()
    # rung 25: a patron may only file requests for their own account
    if role == PATRON:
        claimed = data.get("patron_id")
        if isinstance(claimed, str) and claimed.strip() and claimed != user_id:
            deny_owner()
    # rung 32: body foreign keys in declared field order
    for field, collection, error_id in (
            ("patron_id", db.patrons, "ERR_PATRON_NOT_FOUND"),
            ("bib_item_id", db.bib_items, "ERR_BIB_ITEM_NOT_FOUND"),
            ("rota_id", db.rotas, "ERR_ROTA_NOT_FOUND")):
        ref = raw_id(data, field)
        if ref is not None and ref not in collection:
            raise ApiError(error_id)
    # rung 35: shape
    patron_id = req_str(data, "patron_id")
    bib_item_id = req_str(data, "bib_item_id")
    rota_id = req_str(data, "rota_id")
    service_type = req_enum(data, "service_type", SERVICE_TYPES)
    delivery_mode = req_enum(data, "delivery_mode", DELIVERY_MODES)
    needed_by = req_instant(data, "needed_by")
    max_supply_fee = req_int(data, "max_supply_fee_cents", 0)
    pages_requested = opt_int(data, "pages_requested", None, 1, 200)
    patron = db.patrons[patron_id]
    bib = db.bib_items[bib_item_id]
    rota = db.rotas[rota_id]
    if service_type == "COPY" and delivery_mode != "ELECTRONIC":
        bad("Field 'delivery_mode' must be ELECTRONIC when service_type is COPY.")
    if service_type == "COPY" and bib["item_type"] == "ARTICLE" \
            and pages_requested is None:
        bad("Field 'pages_requested' is required for a COPY of an ARTICLE.")
    # rung 38: the rota must handle this material
    if rota["material_type"] != service_type:
        raise ApiError("ERR_ROTA_MATERIAL_MISMATCH")
    # rung 55 / 56: local and licensed availability
    if bib["local_holding_status"] == "HELD_AVAILABLE":
        raise ApiError("ERR_HELD_LOCALLY")
    if calc.licensed_access_available(bib, now().year):
        raise ApiError("ERR_LICENSED_ACCESS_AVAILABLE")
    # rung 58 / 59 / 60: patron gates
    if patron["status"] != "ACTIVE":
        raise ApiError("ERR_PATRON_BLOCKED")
    open_count = len([r for r in derive.patron_requests(patron_id)
                      if r["status"] not in calc.REQUEST_TERMINAL])
    if open_count >= patron["max_open_requests"]:
        raise ApiError("ERR_PATRON_REQUEST_CAP_REACHED")
    # gates read freshly derived figures without writing anything yet
    probe = dict(patron)
    derive.recompute_patron(probe, derive.PATRON_COUNTER_KEYS, defer_touch=True)
    if derive.provisional_standing(probe) >= calc.STANDING_BLOCK_THRESHOLD:
        raise ApiError("ERR_PATRON_STANDING_BLOCKED")
    # rung 62: the deadline must still be ahead of the clock
    if needed_by <= now():
        raise ApiError("ERR_NEEDED_BY_IN_PAST")
    # rung 80: unpaid balance ceiling
    if probe["unpaid_balance_cents"] > patron["unpaid_balance_cap_cents"]:
        raise ApiError("ERR_PATRON_BALANCE_EXCEEDED")

    row = base_row()
    row.update({
        "patron_id": patron_id,
        "bib_item_id": bib_item_id,
        "rota_id": rota_id,
        "committed_partner_id": None,
        "service_type": service_type,
        "delivery_mode": delivery_mode,
        "needed_by": needed_by,
        "max_supply_fee_cents": max_supply_fee,
        "pages_requested": pages_requested,
        "intake_user_id": user_id,
        "status": "SUBMITTED",
        "unfilled_reason": "NONE",
        "attempt_count": 0,
        "copyright_required": False,
        "days_available_at_source": 0,
        "committed_fee_cents": 0,
        "committed_loan_period_days": 0,
        "rush_surcharge_cents": 0,
        "royalty_cents": 0,
        "gross_charge_cents": 0,
        "subsidy_cents": 0,
        "net_patron_charge_cents": 0,
        "fulfilled_at": None,
        "closed_at": None,
    })
    row["copyright_required"] = bool(
        service_type == "COPY" and bib["item_type"] == "ARTICLE" and bib.get("issn"))
    db.requests[row["id"]] = row

    on_hold = False
    if row["copyright_required"]:
        issn = bib["issn"]
        year = now().year
        if not calc.counts_toward_limit(bib, year):
            new_clearance(row, issn, "PRE_WINDOW_EXEMPT", 0, 0)
        else:
            counted = calc.counted_fill_count(issn, year)
            if counted < calc.COPYRIGHT_LIMIT_FREE_FILLS:
                new_clearance(row, issn, "CONTU_FREE", counted + 1, 0)
            else:
                on_hold = True
    if on_hold:
        row["status"] = "COPYRIGHT_HOLD"
        derive.notify(row, "COPYRIGHT_HOLD",
                      "Copyright clearance required: %s" % bib["title"])
    else:
        row["status"] = "SOURCING"
        derive.notify(row, "REQUEST_SUBMITTED",
                      "Interlibrary loan request received: %s" % bib["title"])
    derive.recompute_patron(
        patron, ("open_request_count", "pending_charge_cents",
                 "provisional_risk_score"))
    return ok_row(row, 201)


@bp.route("/ill/requests/<request_id>", methods=["GET"])
def get_one_request(request_id):
    user_id, role = auth(PATRON, PARTNER_AGENT, ILL_STAFF, ACQUISITIONS, ACCOUNTANT,
                         ADMIN)
    req = get_request(request_id)
    own_request(req, user_id, role)
    return ok_row(req)


@bp.route("/ill/requests", methods=["GET"])
def list_requests():
    user_id, role = auth(PATRON, ILL_STAFF, ACQUISITIONS, ACCOUNTANT, ADMIN)
    rows = list(db.requests.values())
    if role == PATRON:
        rows = [r for r in rows if r["patron_id"] == user_id]
    rows = filter_eq(rows, "patron_id", q_str("patron_id"))
    rows = filter_eq(rows, "bib_item_id", q_str("bib_item_id"))
    rows = filter_eq(rows, "rota_id", q_str("rota_id"))
    rows = filter_eq(rows, "committed_partner_id", q_str("committed_partner_id"))
    rows = filter_eq(rows, "status", q_enum("status", REQUEST_STATUSES))
    rows = filter_eq(rows, "service_type", q_enum("service_type", SERVICE_TYPES))
    return list_response(rows)


@bp.route("/ill/requests/<request_id>/cancel", methods=["POST"])
def cancel_request(request_id):
    user_id, role = auth(PATRON, ILL_STAFF)
    req = get_request(request_id)
    own_request(req, user_id, role)
    if req["status"] not in CANCELLABLE:
        raise ApiError("ERR_REQUEST_INVALID_STATE")
    for clearance in db.clearances.values():
        if clearance["request_id"] == req["id"] and clearance["status"] == "ACTIVE":
            clearance["status"] = "VOIDED"
            touch(clearance)
    for offer in db.offers.values():
        if offer["request_id"] == req["id"] and offer["status"] == "OFFERED":
            offer["status"] = "CANCELLED"
            touch(offer)
    for order in db.pod_orders.values():
        if order["request_id"] == req["id"] and order["status"] == "PROPOSED":
            order["status"] = "CANCELLED"
            touch(order)
    previous_partner_id = req.get("committed_partner_id")
    req["committed_partner_id"] = None
    req["committed_fee_cents"] = 0
    req["rush_surcharge_cents"] = 0
    req["royalty_cents"] = 0
    req["gross_charge_cents"] = 0
    req["subsidy_cents"] = 0
    req["net_patron_charge_cents"] = 0
    req["status"] = "CANCELLED"
    req["closed_at"] = now()
    touch(req)
    bib = db.bib_items.get(req["bib_item_id"]) or {}
    derive.notify(req, "REQUEST_CANCELLED",
                  "Request cancelled: %s" % bib.get("title", ""))
    derive.recompute_partner_by_id(previous_partner_id)
    derive.recompute_patron_for_request(
        req, ("open_request_count", "pending_charge_cents"))
    return ok_row(req)


@bp.route("/ill/requests/<request_id>/copyright-clearances", methods=["GET"])
def list_request_clearances(request_id):
    auth(ILL_STAFF, ADMIN)
    get_request(request_id)
    rows = [c for c in db.clearances.values() if c["request_id"] == request_id]
    rows = filter_eq(rows, "status", q_enum("status", CLEARANCE_STATUSES))
    return list_response(rows)


@bp.route("/ill/requests/<request_id>/pod-orders", methods=["GET"])
def list_request_pod_orders(request_id):
    auth(ILL_STAFF, ACQUISITIONS, ADMIN)
    get_request(request_id)
    rows = [o for o in db.pod_orders.values() if o["request_id"] == request_id]
    rows = filter_eq(rows, "status", q_enum("status", POD_STATUSES))
    return list_response(rows)


@bp.route("/ill/requests/<request_id>/notifications", methods=["GET"])
def list_request_notifications(request_id):
    user_id, role = auth(PATRON, ILL_STAFF, ADMIN)
    req = get_request(request_id)
    own_request(req, user_id, role)
    rows = [n for n in db.notifications.values() if n["request_id"] == request_id]
    rows = filter_eq(rows, "kind", q_enum("kind", NOTIFICATION_KINDS))
    return list_response(rows)


@bp.route("/ill/requests/<request_id>/shipments", methods=["GET"])
def list_request_shipments(request_id):
    user_id, role = auth(PATRON, PARTNER_AGENT, ILL_STAFF, ADMIN)
    req = get_request(request_id)
    own_request(req, user_id, role, partner_side=True)
    rows = [s for s in db.shipments.values() if s["request_id"] == request_id]
    rows = filter_eq(rows, "direction", q_enum("direction", ("INBOUND", "RETURN")))
    rows = filter_eq(rows, "status", q_enum("status", SHIPMENT_STATUSES))
    return list_response(rows)


@bp.route("/ill/requests/<request_id>/loans", methods=["GET"])
def list_request_loans(request_id):
    user_id, role = auth(PATRON, PARTNER_AGENT, ILL_STAFF, ACCOUNTANT, ADMIN)
    req = get_request(request_id)
    own_request(req, user_id, role, partner_side=True)
    rows = [l for l in db.loans.values() if l["request_id"] == request_id]
    rows = filter_eq(rows, "custody_status",
                     q_enum("custody_status", CUSTODY_STATUSES))
    return list_response(rows)


@bp.route("/ill/requests/<request_id>/electronic-deliveries", methods=["GET"])
def list_request_deliveries(request_id):
    user_id, role = auth(PATRON, PARTNER_AGENT, ILL_STAFF, ADMIN)
    req = get_request(request_id)
    own_request(req, user_id, role, partner_side=True)
    rows = [d for d in db.deliveries.values() if d["request_id"] == request_id]
    rows = filter_eq(rows, "status", q_enum("status", DELIVERY_STATUSES))
    return list_response(rows)

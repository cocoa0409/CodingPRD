"""Routes: special items, mishandled reports and claims."""

from flask import Blueprint, request

from common import (
    authenticate, body, boolean, datetime_value, enum_value, integer, paginate,
    query_str, require, text, version_token,
)
from db import DB, new_row, iso, parse_iso, touch
from errors import fail
import calc
import recompute
import serializers as ser

bp = Blueprint("reports", __name__)

ITEM_TYPES = ("OVERSIZE", "FRAGILE", "SPORTS_EQUIPMENT", "MOBILITY_DEVICE")
REPORT_TYPES = ("DELAYED", "DAMAGED", "LOST", "PILFERED")
REPORT_STATUS = ("REPORTED", "INVESTIGATING", "DELIVERY_ARRANGED", "DELIVERED",
                 "COMPENSATED", "REOPENED", "CLOSED")
DELIVERY_METHODS = ("COURIER", "PASSENGER_PICKUP", "FORWARD_ON_NEXT_FLIGHT")
DECISIONS = ("APPROVED", "DENIED")


def _bag(ident):
    row = DB.bags.get(ident)
    if row is None:
        fail("ERR_BAG_NOT_FOUND")
    return row


def _report(ident):
    row = DB.reports.get(ident)
    if row is None:
        fail("ERR_REPORT_NOT_FOUND")
    return row


def _guard_passenger(role, user_id, bag):
    if role == "Passenger" and bag.get("passenger_ref") != user_id:
        fail("ERR_FORBIDDEN_ROLE")


def _listed(rows, query, serializer=lambda r: r):
    rows = ser.sort_rows(rows)
    window, page = paginate(rows, query)
    return [serializer(r) for r in window], page


def _sync_report(store, report):
    recompute.recompute_report_money(store, report)
    touch(store, report)
    recompute.recompute_station(store, report["station_id"])


# ---------------------------------------------------------- special items ---
@bp.post("/baggage/bags/<ident>/special-items")
def create_special_item(ident):
    authenticate()
    role = request.headers.get("X-User-Role")
    if role not in ("AcceptanceAgent", "BaggageServiceAgent"):
        fail("ERR_FORBIDDEN_ROLE")
    bag = _bag(ident)
    payload = body()
    require(payload, "item_type", "declared_value_cents")
    item_type = enum_value(payload, "item_type", ITEM_TYPES)
    value = integer(payload, "declared_value_cents")
    row = new_row(DB, {
        "bag_id": bag["id"],
        "item_type": item_type,
        "declared_value_cents": value,
        "requires_manual_screening": calc.requires_manual_screening(bag["linear_in"], item_type),
        "handling_fee_cents": calc.single_item_fee(bag["linear_in"], item_type),
        "liability_cap_cents": calc.liability_cap(item_type, value),
        "waived_fee_cents": 0,
    })
    DB.add("special_items", row)
    variant = "PROVISIONAL" if bag["custody_status"] in calc.PROVISIONAL_CUSTODY else "FINAL"
    bag["handling_charge_cents"] = calc.handling_charge(DB, bag, variant)
    recompute.recompute_bag_derived(DB, bag)
    return ser.special_item(row), 201


@bp.get("/baggage/bags/<ident>/special-items")
def list_bag_special_items(ident):
    bag = _bag(ident)
    authenticate()
    rows = calc.special_items_of(DB, bag["id"])
    window, page = _listed(rows, request.args, ser.special_item)
    return window, page


@bp.get("/baggage/special-items")
def list_special_items():
    authenticate()
    rows = DB.all_of("special_items")
    bag_id = query_str("bag_id")
    item_type = query_str("item_type")
    if bag_id:
        if DB.bags.get(bag_id) is None:
            fail("ERR_BAG_NOT_FOUND")
        rows = [r for r in rows if r["bag_id"] == bag_id]
    if item_type:
        rows = [r for r in rows if r["item_type"] == item_type]
    window, page = _listed(rows, request.args, ser.special_item)
    return window, page


@bp.post("/baggage/bags/<ident>/special-items/<item_id>/waive-handling-fee")
def waive_handling_fee(ident, item_id):
    authenticate()
    role = request.headers.get("X-User-Role")
    if role not in ("BaggageServiceAgent", "PlatformAdmin"):
        fail("ERR_FORBIDDEN_ROLE")
    bag = _bag(ident)
    payload = body()
    expected = version_token(payload, "expected_bag_version")
    item = DB.special_items.get(item_id)
    if item is None or item["bag_id"] != bag["id"]:
        fail("ERR_INVALID_REQUEST")
    if expected != bag["version"]:
        fail("ERR_STALE_VERSION")
    item["waived_fee_cents"] = calc.single_item_fee(bag["linear_in"], item["item_type"])
    touch(DB, item)
    touch(DB, bag)
    return ser.bag(DB, bag), 200


# --------------------------------------------------------------- reports ----
@bp.post("/baggage/reports")
def file_report():
    authenticate()
    role = request.headers.get("X-User-Role")
    if role != "BaggageServiceAgent":
        fail("ERR_FORBIDDEN_ROLE")
    payload = body()
    require(payload, "bag_id", "station_id", "report_type")
    bag = _bag(text(payload, "bag_id"))
    station = DB.stations.get(text(payload, "station_id"))
    if station is None:
        fail("ERR_INVALID_REQUEST")
    report_type = enum_value(payload, "report_type", REPORT_TYPES)
    payload.get("anomaly_note")
    row = new_row(DB, {
        "bag_id": bag["id"],
        "station_id": station["id"],
        "report_type": report_type,
        "status": "REPORTED",
        "delivery_method": None,
        "compensation_offer_cents": 0,
        "claim_status": "NONE",
        "claim_amount_cents": 0,
        "approved_cents": 0,
        "compensation_settled_cents": 0,
        "final_liability_cents": 0,
        "outage_context": False,
        "_paid_compensation": False,
    })
    DB.add("reports", row)
    _sync_report(DB, row)
    return ser.report(row), 201


@bp.get("/baggage/reports/<ident>")
def get_report(ident):
    user_id, role = authenticate()
    report = _report(ident)
    bag = DB.bags.get(report["bag_id"])
    if bag is not None:
        _guard_passenger(role, user_id, bag)
    return ser.report(report), 200


@bp.get("/baggage/reports")
def list_reports():
    authenticate()
    rows = DB.all_of("reports")
    for key in ("station_id", "bag_id", "report_type", "status"):
        value = query_str(key)
        if value is not None:
            rows = [r for r in rows if r.get(key) == value]
    if query_str("bag_id") and DB.bags.get(query_str("bag_id")) is None:
        fail("ERR_BAG_NOT_FOUND")
    window, page = _listed(rows, request.args, ser.report)
    return window, page


@bp.get("/baggage/stations/<ident>/reports")
def list_station_reports(ident):
    authenticate()
    station = DB.stations.get(ident)
    if station is None:
        fail("ERR_INVALID_REQUEST")
    rows = [r for r in DB.reports.values() if r["station_id"] == station["id"]]
    window, page = _listed(rows, request.args, ser.report)
    return window, page


@bp.get("/baggage/bags/<ident>/reports")
def list_bag_reports(ident):
    user_id, role = authenticate()
    bag = _bag(ident)
    _guard_passenger(role, user_id, bag)
    rows = calc.reports_of(DB, bag["id"])
    window, page = _listed(rows, request.args, ser.report)
    return window, page


@bp.post("/baggage/reports/<ident>/investigate")
def investigate_report(ident):
    authenticate()
    role = request.headers.get("X-User-Role")
    if role != "BaggageServiceAgent":
        fail("ERR_FORBIDDEN_ROLE")
    report = _report(ident)
    if report["status"] not in ("REPORTED", "REOPENED"):
        fail("ERR_INVALID_STATE")
    report["status"] = "INVESTIGATING"
    _sync_report(DB, report)
    return ser.report(report), 200


@bp.post("/baggage/reports/<ident>/arrange-delivery")
def arrange_delivery(ident):
    authenticate()
    role = request.headers.get("X-User-Role")
    if role != "BaggageServiceAgent":
        fail("ERR_FORBIDDEN_ROLE")
    report = _report(ident)
    payload = body()
    if report["status"] != "INVESTIGATING":
        fail("ERR_INVALID_STATE")
    require(payload, "delivery_method")
    method = enum_value(payload, "delivery_method", DELIVERY_METHODS)
    scheduled = datetime_value(payload, "scheduled_utc", required=False)
    if scheduled is not None and scheduled < DB.now():
        fail("ERR_DELIVERY_IN_PAST")
    proof_required = boolean(payload, "proof_required", False)
    report["status"] = "DELIVERY_ARRANGED"
    report["delivery_method"] = method
    bag = DB.bags.get(report["bag_id"])
    delivery = recompute.ensure_delivery(DB, bag)
    delivery["mishandled_report_id"] = report["id"]
    delivery["method"] = method
    delivery["scheduled_utc"] = iso(scheduled) if scheduled else delivery.get("scheduled_utc")
    delivery["proof_required"] = proof_required
    delivery["status"] = "IN_TRANSIT"
    touch(DB, delivery)
    _sync_report(DB, report)
    return ser.report(report), 200


@bp.post("/baggage/reports/<ident>/mark-delivered")
def mark_report_delivered(ident):
    authenticate()
    role = request.headers.get("X-User-Role")
    if role != "BaggageServiceAgent":
        fail("ERR_FORBIDDEN_ROLE")
    report = _report(ident)
    if report["status"] != "DELIVERY_ARRANGED":
        fail("ERR_INVALID_STATE")
    report["status"] = "DELIVERED"
    bag = DB.bags.get(report["bag_id"])
    delivery = recompute.ensure_delivery(DB, bag)
    delivery["mishandled_report_id"] = report["id"]
    delivery["status"] = "DELIVERED"
    delivery["delivered_utc"] = iso(DB.now())
    touch(DB, delivery)
    _sync_report(DB, report)
    return ser.report(report), 200


@bp.post("/baggage/reports/<ident>/compensate")
def compensate_report(ident):
    authenticate()
    role = request.headers.get("X-User-Role")
    if role != "BaggageServiceAgent":
        fail("ERR_FORBIDDEN_ROLE")
    report = _report(ident)
    if report.get("_paid_compensation"):
        fail("ERR_COMPENSATION_ALREADY_PAID")
    if report["claim_status"] != "APPROVED":
        fail("ERR_CLAIM_NOT_APPROVED")
    if report["status"] != "DELIVERED":
        fail("ERR_INVALID_STATE")
    claim = next((c for c in DB.claims.values() if c["mishandled_report_id"] == report["id"]), None)
    pre_liability = report["final_liability_cents"]
    approved, applied = calc.settlement(DB, report, claim, pre_liability)
    report["status"] = "COMPENSATED"
    report["claim_status"] = "SETTLED"
    report["approved_cents"] = approved
    report["compensation_settled_cents"] = applied
    report["_paid_compensation"] = True
    bag = DB.bags.get(report["bag_id"])
    delivery = recompute.ensure_delivery(DB, bag)
    delivery["mishandled_report_id"] = report["id"]
    delivery["status"] = "COMPENSATED"
    touch(DB, delivery)
    _sync_report(DB, report)
    return ser.report(report), 200


@bp.post("/baggage/reports/<ident>/close")
def close_report(ident):
    authenticate()
    role = request.headers.get("X-User-Role")
    if role != "BaggageServiceAgent":
        fail("ERR_FORBIDDEN_ROLE")
    report = _report(ident)
    if report["status"] == "COMPENSATED":
        report["status"] = "CLOSED"
    elif report["status"] == "INVESTIGATING":
        if report["claim_status"] not in ("NONE", "DENIED"):
            fail("ERR_CLAIM_PENDING")
        report["status"] = "CLOSED"
    else:
        fail("ERR_INVALID_STATE")
    _sync_report(DB, report)
    return ser.report(report), 200


@bp.post("/baggage/reports/<ident>/reopen")
def reopen_report(ident):
    authenticate()
    role = request.headers.get("X-User-Role")
    if role != "BaggageServiceAgent":
        fail("ERR_FORBIDDEN_ROLE")
    report = _report(ident)
    payload = body()
    expected = version_token(payload, "expected_report_version")
    # PRD §3.11: REOPENED is reachable only from COMPENSATED or CLOSED.
    if report["status"] not in ("COMPENSATED", "CLOSED"):
        fail("ERR_INVALID_STATE")
    if expected != report["version"]:
        fail("ERR_STALE_VERSION")
    reversible = report["claim_status"] in ("SETTLED", "APPROVED") or report.get("_paid_compensation")
    report["status"] = "REOPENED"
    if reversible:
        report["claim_status"] = "FILED"
        report["compensation_settled_cents"] = 0
        report["approved_cents"] = 0
        bag = DB.bags.get(report["bag_id"])
        delivery = calc.delivery_of(DB, bag["id"]) if bag else None
        if delivery is not None and delivery["status"] == "COMPENSATED":
            delivery["status"] = "DELIVERED"
            delivery["mishandled_report_id"] = report["id"]
            touch(DB, delivery)
    report["_paid_compensation"] = False
    _sync_report(DB, report)
    return ser.report(report), 200


@bp.post("/baggage/reports/<ident>/loss-settlement")
def loss_settlement(ident):
    authenticate()
    role = request.headers.get("X-User-Role")
    if role != "BaggageServiceAgent":
        fail("ERR_FORBIDDEN_ROLE")
    report = _report(ident)
    payload = body()
    paid = integer(payload, "paid_cents")
    approved = min(paid, report["compensation_offer_cents"])
    bag = DB.bags.get(report["bag_id"])
    airline = calc.airline_of_bag(DB, bag) if bag else None
    if airline is not None:
        approved = min(approved, airline["compensation_cap_cents"])
    report["approved_cents"] = approved
    report["compensation_settled_cents"] = approved
    report["status"] = "COMPENSATED"
    report["claim_status"] = "SETTLED"
    report["_paid_compensation"] = True
    delivery = recompute.ensure_delivery(DB, bag)
    delivery["mishandled_report_id"] = report["id"]
    delivery["status"] = "COMPENSATED"
    touch(DB, delivery)
    _sync_report(DB, report)
    return ser.report(report), 200


# ---------------------------------------------------------------- claims ----
@bp.post("/baggage/reports/<ident>/claims")
def file_claim(ident):
    authenticate()
    role = request.headers.get("X-User-Role")
    if role != "BaggageServiceAgent":
        fail("ERR_FORBIDDEN_ROLE")
    report = _report(ident)
    payload = body()
    requested = integer(payload, "requested_amount_cents")
    for existing in DB.claims.values():
        if existing["mishandled_report_id"] == report["id"]:
            fail("ERR_INVALID_STATE")
    # PRD §3.12: "A request exceeding the carrier's cap is refused outright with
    # ERR_COMPENSATION_OVER_CAP (422)" — the refused filing never becomes the
    # report's claim_amount_cents, so the report keeps claim_status NONE.
    if calc.request_over_cap(DB, report, requested):
        fail("ERR_COMPENSATION_OVER_CAP")
    row = new_row(DB, {
        "mishandled_report_id": report["id"],
        "requested_amount_cents": requested,
        "decision": "PENDING",
        "decided_by": None,
        "decided_utc": None,
    })
    DB.add("claims", row)
    report["claim_status"] = "FILED"
    report["claim_amount_cents"] = requested
    touch(DB, report)
    return ser.claim(row), 201


@bp.get("/baggage/reports/<ident>/claims")
def list_report_claims(ident):
    authenticate()
    report = _report(ident)
    rows = [c for c in DB.claims.values() if c["mishandled_report_id"] == report["id"]]
    window, page = _listed(rows, request.args, ser.claim)
    return window, page


@bp.post("/baggage/claims/<ident>/decide")
def decide_claim(ident):
    authenticate()
    role = request.headers.get("X-User-Role")
    if role != "BaggageServiceAgent":
        fail("ERR_FORBIDDEN_ROLE")
    claim = DB.claims.get(ident)
    if claim is None:
        fail("ERR_REPORT_NOT_FOUND")
    payload = body()
    decision = enum_value(payload, "decision", DECISIONS)
    if claim["decision"] != "PENDING":
        fail("ERR_CLAIM_ALREADY_DECIDED")
    report = _report(claim["mishandled_report_id"])
    claim["decision"] = decision
    claim["decided_by"] = request.headers.get("X-User-ID")
    claim["decided_utc"] = iso(DB.now())
    touch(DB, claim)
    if decision == "DENIED":
        report["claim_status"] = "DENIED"
        _sync_report(DB, report)
        return ser.claim(claim), 200
    if calc.request_over_cap(DB, report, claim["requested_amount_cents"]):
        claim["decision"] = "PENDING"
        claim["decided_by"] = None
        claim["decided_utc"] = None
        touch(DB, claim)
        fail("ERR_COMPENSATION_OVER_CAP")
    pre_liability = report["final_liability_cents"]
    approved, applied = calc.settlement(DB, report, claim, pre_liability)
    report["claim_status"] = "APPROVED"
    report["approved_cents"] = approved
    report["compensation_settled_cents"] = applied
    _sync_report(DB, report)
    return ser.claim(claim), 200
"""Warranty reimbursement rate disputes (PRD 3.8)."""

from flask import Blueprint, request

import calc
import db
import derive
import enums
import response
import serializers
import validation as v
from errors import ApiError
from middleware import guard, require_dealer_owner, require_manufacturer_owner

bp = Blueprint("disputes", __name__)

READ_ROLES = ["BoardAdmin", "LicensingAnalyst", "Dealer", "Manufacturer"]
RESPONSE_WINDOW_DAYS = 30
RATE_EFFECTIVE_DAYS_AFTER = 30


def _find(record_id):
    record = db.get("warranty_rate_dispute", record_id)
    if record is None:
        raise ApiError("ERR_DISPUTE_NOT_FOUND", "No such warranty rate dispute")
    return record


def _read_lines(body):
    raw_lines = v.req_list(body, "repair_order_lines", 1, 100)
    lines = []
    for index, raw in enumerate(raw_lines):
        if not isinstance(raw, dict):
            raise ApiError("ERR_INVALID_REQUEST", "repair_order_lines[%d] must be an object" % index)
        prefix = "repair_order_lines[%d]" % index
        for field in ("labor_charge_cents", "labor_hours", "repair_type"):
            if field not in raw or raw[field] is None:
                raise ApiError("ERR_INVALID_REQUEST", "%s.%s is required" % (prefix, field))
        lines.append({
            "labor_charge_cents": v._int_value(
                raw["labor_charge_cents"], prefix + ".labor_charge_cents", 0, None
            ),
            "labor_hours": v._decimal_value(
                raw["labor_hours"], prefix + ".labor_hours", None, None, 1, 0
            ),
            "repair_type": v._enum_value(raw["repair_type"], prefix + ".repair_type", enums.REPAIR_TYPES),
        })
    return lines


@bp.post("/warranty-rate-disputes")
def create_dispute():
    caller = guard(["Dealer"])
    peeked = v.peek_body()
    if isinstance(peeked.get("dealer_id"), str):
        require_dealer_owner(caller, peeked["dealer_id"])

    body = v.read_body()
    dealer_id = v.req_string(body, "dealer_id", 1, 100)
    manufacturer_id = v.req_string(body, "manufacturer_id", 1, 100)
    lines = _read_lines(body)

    dealer = db.get("dealer", dealer_id)
    if dealer is None:
        raise ApiError("ERR_DEALER_NOT_FOUND", "No such dealership")
    manufacturer = db.get("manufacturer", manufacturer_id)
    if manufacturer is None:
        raise ApiError("ERR_MANUFACTURER_NOT_FOUND", "No such franchisor")

    if manufacturer["state_registration_status"] != "REGISTERED":
        raise ApiError("ERR_MANUFACTURER_REGISTRATION_LAPSED", "The franchisor's registration has lapsed")
    if dealer["license_status"] != "LICENSED":
        raise ApiError("ERR_DEALER_LICENSE_NOT_ACTIVE", "Only a LICENSED dealership may bring a rate dispute")

    for existing in db.where("warranty_rate_dispute", dealer_id=dealer_id, manufacturer_id=manufacturer_id):
        if existing["status"] in derive.OPEN_DISPUTE_STATES:
            raise ApiError("ERR_OPEN_DISPUTE_EXISTS", "That pair already has an open dispute")

    qualifying = calc.qualifying_indexes(lines)
    if len(qualifying) < calc.MINIMUM_QUALIFYING_LINES:
        raise ApiError("ERR_INSUFFICIENT_RO_SAMPLE", "The sample carries fewer than 5 qualifying lines")

    declared = calc.declared_rate_cents(lines)
    if declared <= manufacturer["posted_warranty_labor_rate_cents"]:
        raise ApiError("ERR_RATE_NOT_ABOVE_POSTED", "The declared rate does not exceed the posted rate")

    record = db.insert("warranty_rate_dispute", {
        "dealer_id": dealer_id,
        "manufacturer_id": manufacturer_id,
        "status": "FILED",
        "repair_order_lines": lines,
        "filed_on": db.today(),
        "qualifying_line_count": len(qualifying),
        "declared_rate_cents": declared,
        "counter_rate_cents": None,
        "manufacturer_response_type": None,
        "excluded_line_indexes": [],
        "spread_pct": None,
        "approved_rate_cents": None,
        "effective_on": None,
        "decided_on": None,
        "denial_reason_code": None,
    })
    derive.recompute_all()
    return response.object_response(serializers.warranty_rate_dispute(record), 201)


@bp.post("/warranty-rate-disputes/<record_id>/response")
def answer_dispute(record_id):
    caller = guard(["Manufacturer"])
    dispute = db.get("warranty_rate_dispute", record_id)
    if dispute is not None:
        require_manufacturer_owner(caller, dispute["manufacturer_id"])
    dispute = _find(record_id)

    body = v.read_body()
    response_type = v.req_enum(body, "manufacturer_response_type", enums.RESPONSE_TYPES)
    raw_indexes = v.opt_list(body, "excluded_line_indexes", 0, 100)
    excluded = []
    if raw_indexes is not None:
        for position, raw in enumerate(raw_indexes):
            value = v._int_value(
                raw, "excluded_line_indexes[%d]" % position, 0, len(dispute["repair_order_lines"]) - 1
            )
            if value in excluded:
                raise ApiError("ERR_INVALID_REQUEST", "excluded_line_indexes entries must be unique")
            excluded.append(value)

    if dispute["status"] != "FILED":
        raise ApiError("ERR_INVALID_DISPUTE_STATE", "Only a FILED dispute may be answered")
    manufacturer = db.get("manufacturer", dispute["manufacturer_id"])
    if manufacturer is None or manufacturer["state_registration_status"] != "REGISTERED":
        raise ApiError("ERR_MANUFACTURER_REGISTRATION_LAPSED", "The franchisor's registration has lapsed")
    if db.today() > dispute["filed_on"] + calc._timedelta(RESPONSE_WINDOW_DAYS):
        raise ApiError("ERR_RESPONSE_WINDOW_CLOSED", "The 30-day response window has closed")

    dispute["manufacturer_response_type"] = response_type
    if response_type == "REBUT":
        dispute["excluded_line_indexes"] = excluded
        counter = calc.counter_rate_cents(dispute["repair_order_lines"], excluded)
        dispute["counter_rate_cents"] = counter
        dispute["spread_pct"] = calc.spread_pct(dispute["declared_rate_cents"], counter)
    dispute["status"] = "UNDER_REVIEW"
    db.touch(dispute)
    derive.recompute_all()
    return response.object_response(serializers.warranty_rate_dispute(dispute), 200)


@bp.post("/warranty-rate-disputes/<record_id>/decision")
def decide_dispute(record_id):
    guard(["BoardAdmin"])
    body = v.read_body()
    outcome = v.req_enum(body, "outcome", enums.DECISION_OUTCOMES)
    denial_reason_code = v.opt_string(body, "denial_reason_code", 1, 500)
    if outcome == "DENIED" and denial_reason_code is None:
        raise ApiError("ERR_INVALID_REQUEST", "denial_reason_code is required when the board denies")

    dispute = _find(record_id)
    admitted = ("UNDER_REVIEW",) if outcome == "APPROVED" else ("FILED", "UNDER_REVIEW")
    if dispute["status"] not in admitted:
        raise ApiError(
            "ERR_INVALID_DISPUTE_STATE",
            "A dispute in %s may not be %s" % (dispute["status"], outcome.lower()),
        )

    dealer = db.get("dealer", dispute["dealer_id"])
    manufacturer = db.get("manufacturer", dispute["manufacturer_id"])
    reference_date = db.today()

    if outcome == "APPROVED":
        if dealer is None or dealer["license_status"] != "LICENSED" or dealer["franchise_status"] not in (
            "FRANCHISED", "TERMINATION_PENDING"
        ):
            raise ApiError("ERR_DEALER_LICENSE_NOT_ACTIVE", "The dealership's standing bars an approval")
        if dispute["qualifying_line_count"] < calc.MINIMUM_QUALIFYING_LINES:
            raise ApiError("ERR_INSUFFICIENT_RO_SAMPLE", "The sample carries fewer than 5 qualifying lines")
        posted = 0 if manufacturer is None else manufacturer["posted_warranty_labor_rate_cents"]
        if dispute["declared_rate_cents"] <= posted:
            raise ApiError("ERR_RATE_NOT_ABOVE_POSTED", "The declared rate does not exceed the posted rate")

        approved = calc.approved_rate_cents(
            dispute["manufacturer_response_type"],
            dispute["declared_rate_cents"],
            dispute["counter_rate_cents"],
            dispute["spread_pct"],
        )
        dispute["approved_rate_cents"] = approved
        dispute["decided_on"] = reference_date
        dispute["effective_on"] = reference_date + calc._timedelta(RATE_EFFECTIVE_DAYS_AFTER)
        dispute["status"] = "APPROVED"
        db.touch(dispute)
        dealer["approved_warranty_labor_rate_cents"] = approved
        db.touch(dealer)
    else:
        dispute["denial_reason_code"] = denial_reason_code
        dispute["decided_on"] = reference_date
        dispute["status"] = "DENIED"
        db.touch(dispute)

    derive.recompute_all()
    return response.object_response(serializers.warranty_rate_dispute(dispute), 200)


@bp.get("/warranty-rate-disputes/<record_id>")
def read_dispute(record_id):
    guard(READ_ROLES)
    return response.object_response(serializers.warranty_rate_dispute(_find(record_id)), 200)


@bp.get("/warranty-rate-disputes")
def list_disputes():
    guard(READ_ROLES)
    dealer_id = v.query_string("dealer_id")
    manufacturer_id = v.query_string("manufacturer_id")
    status = v.query_enum("status", enums.DISPUTE_STATUSES)
    limit, offset = response.read_pagination(request.args)
    rows = [
        row for row in db.ordered("warranty_rate_dispute")
        if (dealer_id is None or row["dealer_id"] == dealer_id)
        and (manufacturer_id is None or row["manufacturer_id"] == manufacturer_id)
        and (status is None or row["status"] == status)
    ]
    window, total = response.page(rows, limit, offset)
    return response.array_response(
        [serializers.warranty_rate_dispute(row) for row in window], limit, offset, len(rows)
    )

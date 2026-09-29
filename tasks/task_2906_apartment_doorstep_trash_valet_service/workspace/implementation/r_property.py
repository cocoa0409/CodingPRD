"""Property and ServiceContract endpoints (PRD s3.1)."""

import re

from flask import Blueprint

import shape
from authz import admit, get_contract, get_property, property_of_contract
from calc import contracts_of_property, nights_of_contract, statements_of_contract
from envelope import array_response, object_response
from errors import ApiError
from rollups import cancel_night
from serializers import contract_out, property_out
from shape import pagination, paginate, q
from store import (
    OPEN_ROUTE_STATUSES,
    WEEKDAY_SET,
    db,
    parse_date,
    sort_rows,
    stamp_new,
    touch,
)

bp = Blueprint("property", __name__)

MARKET_CODE_RE = re.compile(r"^[A-Z]{3}$")
PROPERTY_STATUSES = ("ONBOARDING", "ACTIVE", "SUSPENDED", "TERMINATED")
CONTRACT_STATUSES = ("DRAFT", "ACTIVE", "TERMINATED")
LIVE_CONTRACT_STATUSES = ("DRAFT", "ACTIVE")


# ---------------------------------------------------------------------------
# Property
# ---------------------------------------------------------------------------
@bp.route("/valet/properties", methods=["POST"])
def create_property():
    admit(("PlatformAdmin",))
    body = shape.body()
    name = shape.req_str(body, "name", min_len=1, max_len=120, non_blank=True)
    unit_count = shape.req_int(body, "unit_count", lo=1, hi=500)
    market_code = shape.req_str(body, "market_code")
    if not MARKET_CODE_RE.match(market_code):
        shape.bad("Field 'market_code' must be exactly three uppercase letters.")
    capacity = shape.opt_int(body, "compactor_capacity_lbs", lo=1000, default=6000)

    row = {
        "name": name,
        "unit_count": unit_count,
        "market_code": market_code,
        "compactor_capacity_lbs": capacity,
        "status": "ONBOARDING",
        "active_contract_id": None,
        "escalation_level": 0,
        "pending_fine_revenue_cents": 0,
        "delinquent_resident_count": 0,
    }
    stamp_new(row)
    db.properties[row["id"]] = row
    return object_response(property_out(row), 201)


@bp.route("/valet/properties/<property_id>", methods=["GET"])
def read_property(property_id):
    admit((
        "PlatformAdmin",
        "ValetOpsManager",
        "ComplianceOfficer",
        "BillingAnalyst",
        "PropertyManager",
    ))
    row = get_property(property_id)
    return object_response(property_out(row))


@bp.route("/valet/properties", methods=["GET"])
def list_properties():
    admit(("PlatformAdmin", "ValetOpsManager", "ComplianceOfficer", "BillingAnalyst"))
    limit, offset = pagination()
    f_status = q("status")
    f_market = q("market_code")
    f_contract = q("active_contract_id")
    rows = sort_rows(list(db.properties.values()))
    if f_status is not None:
        rows = [r for r in rows if r["status"] == f_status]
    if f_market is not None:
        rows = [r for r in rows if r["market_code"] == f_market]
    if f_contract is not None:
        rows = [r for r in rows if r["active_contract_id"] == f_contract]
    page, total, has_more = paginate(rows, limit, offset)
    return array_response([property_out(r) for r in page], limit, offset, total, has_more)


# ---------------------------------------------------------------------------
# ServiceContract
# ---------------------------------------------------------------------------
@bp.route("/valet/properties/<property_id>/contracts", methods=["POST"])
def create_contract(property_id):
    admit(("PlatformAdmin", "BillingAnalyst"))
    prop = get_property(property_id)
    body = shape.body()
    fee = shape.req_int(body, "per_unit_monthly_fee_cents", lo=100, hi=100000)
    share_bps = shape.req_int(body, "property_revenue_share_bps", lo=0, hi=5000)
    days = shape.req_str_array(body, "service_night_days", WEEKDAY_SET, min_items=1, max_items=7)
    eff_from = shape.req_date(body, "effective_from")
    eff_to = shape.req_date(body, "effective_to")
    if eff_to < eff_from:
        shape.bad("Field 'effective_to' must not precede 'effective_from'.")
    sla_bps = shape.req_int(body, "sla_missed_threshold_bps", lo=1, hi=10000)

    # rung 14: closed-interval intersection with a DRAFT or ACTIVE contract
    for other in contracts_of_property(prop["id"]):
        if other["status"] not in LIVE_CONTRACT_STATUSES:
            continue
        other_from = parse_date(other["effective_from"])
        other_to = parse_date(other["effective_to"])
        if eff_from <= other_to and other_from <= eff_to:
            raise ApiError("ERR_CONTRACT_PERIOD_OVERLAP")

    row = {
        "property_id": prop["id"],
        "per_unit_monthly_fee_cents": fee,
        "property_revenue_share_bps": share_bps,
        "service_night_days": days,
        "effective_from": body["effective_from"].strip(),
        "effective_to": body["effective_to"].strip(),
        "sla_missed_threshold_bps": sla_bps,
        "status": "DRAFT",
        "last_invoiced_period": None,
    }
    stamp_new(row)
    db.contracts[row["id"]] = row
    return object_response(contract_out(row), 201)


@bp.route("/valet/contracts/<contract_id>", methods=["GET"])
def read_contract(contract_id):
    admit(("PlatformAdmin", "ValetOpsManager", "BillingAnalyst", "PropertyManager"))
    row = get_contract(contract_id)
    return object_response(contract_out(row))


@bp.route("/valet/contracts", methods=["GET"])
def list_contracts():
    admit(("PlatformAdmin", "ValetOpsManager", "BillingAnalyst"))
    limit, offset = pagination()
    f_property = q("property_id")
    f_status = q("status")
    rows = sort_rows(list(db.contracts.values()))
    if f_property is not None:
        rows = [r for r in rows if r["property_id"] == f_property]
    if f_status is not None:
        rows = [r for r in rows if r["status"] == f_status]
    page, total, has_more = paginate(rows, limit, offset)
    return array_response([contract_out(r) for r in page], limit, offset, total, has_more)


@bp.route("/valet/contracts/<contract_id>/activate", methods=["POST"])
def activate_contract(contract_id):
    admit(("PlatformAdmin",))
    contract = get_contract(contract_id)
    shape.body()

    # rung 8
    if contract["status"] == "TERMINATED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if contract["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")
    prop = property_of_contract(contract)
    if prop is None or prop["status"] == "TERMINATED":
        raise ApiError("ERR_INVALID_STATE")
    for other in contracts_of_property(prop["id"]):
        if other["id"] != contract["id"] and other["status"] == "ACTIVE":
            raise ApiError("ERR_INVALID_STATE")

    contract["status"] = "ACTIVE"
    touch(contract)
    prop["active_contract_id"] = contract["id"]
    if prop["status"] == "ONBOARDING":
        prop["status"] = "ACTIVE"
    touch(prop)
    return object_response(contract_out(contract))


@bp.route("/valet/contracts/<contract_id>/terminate", methods=["POST"])
def terminate_contract(contract_id):
    admit(("PlatformAdmin",))
    contract = get_contract(contract_id)
    body = shape.body()
    shape.opt_str(body, "reason", max_len=500)

    # rung 8
    if contract["status"] == "TERMINATED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    was_active = contract["status"] == "ACTIVE"
    if was_active:
        for statement in statements_of_contract(contract["id"]):
            if statement["status"] == "DRAFT":
                raise ApiError("ERR_INVALID_STATE")

    contract["status"] = "TERMINATED"
    touch(contract)

    if was_active:
        for night in nights_of_contract(contract["id"]):
            if night["verification_status"] in ("SCHEDULED", "IN_PROGRESS"):
                cancel_night(night, cancel_route_statuses=OPEN_ROUTE_STATUSES)
        prop = property_of_contract(contract)
        if prop is not None:
            remaining = [
                c for c in contracts_of_property(prop["id"])
                if c["id"] != contract["id"] and c["status"] in LIVE_CONTRACT_STATUSES
            ]
            if not remaining:
                prop["active_contract_id"] = None
                prop["status"] = "TERMINATED"
                touch(prop)
    return object_response(contract_out(contract))

"""Research fund endpoints (PRD §2.4, §3.1)."""

from flask import Blueprint

from db import DB, new_row, touch
from errors import ApiError
from http_util import body_json, optional, required, require_role
from response import success_object
from routes._common import arg, filtered, list_response, ordered
from services import (
    commitment_share_ceiling, derive_fund_split, get_or_404, serialize_fund,
)

bp = Blueprint("funds", __name__)


@bp.post("/programs/research-funds")
def create_fund():
    require_role("PlatformAdmin")
    data = body_json()
    fund_code = required(data, "fund_code", "str")
    fiscal_year = required(data, "fiscal_year", "int")
    if fiscal_year < 1900:
        raise ApiError("ERR_INVALID_REQUEST")
    fundraising = optional(data, "fundraising_raised_cents", 0, "int")
    if fundraising < 0:
        raise ApiError("ERR_INVALID_REQUEST")
    federal = optional(data, "federal_grant_cents", 0, "int")
    if federal < 0:
        raise ApiError("ERR_INVALID_REQUEST")
    pct = required(data, "research_allocation_pct", "number")
    if not (0 < pct < 1):
        raise ApiError("ERR_INVALID_REQUEST")

    fund = new_row({
        "fund_code": fund_code,
        "fiscal_year": fiscal_year,
        "fundraising_raised_cents": fundraising,
        "research_allocation_pct": pct,
        "federal_grant_cents": federal,
        "patient_support_balance_cents": 0,
        "research_balance_cents": 0,
    })
    derive_fund_split(fund)
    DB["funds"][fund["id"]] = fund
    return success_object(serialize_fund(fund), 201)


@bp.get("/programs/research-funds")
def list_funds():
    require_role("Any")
    rows = ordered(DB["funds"].values())
    return list_response(rows, serialize_fund)


@bp.get("/programs/research-funds/<fund_id>")
def get_fund(fund_id):
    require_role("Any")
    fund = get_or_404("funds", fund_id)
    derive_fund_split(fund)
    return success_object(serialize_fund(fund), 200)


@bp.post("/programs/research-funds/<fund_id>/donations")
def create_donation(fund_id):
    require_role("PlatformAdmin")
    fund = get_or_404("funds", fund_id)
    data = body_json()
    amount = required(data, "amount_cents", "int")
    # `amount_cents` is a plain integer with no declared lower bound: a positive
    # amount is a donation and a negative amount is its compensating reversal.
    # Either way the pool split is re-derived and the fund's version advances by
    # one (PRD §2.4).
    is_federal = optional(data, "is_federal_grant", False, "bool")
    if is_federal:
        fund["federal_grant_cents"] = int(fund["federal_grant_cents"]) + amount
    else:
        fund["fundraising_raised_cents"] = int(fund["fundraising_raised_cents"]) + amount
    derive_fund_split(fund)
    touch(fund)
    return success_object(serialize_fund(fund), 201)


@bp.get("/programs/research-funds/<fund_id>/services")
def list_fund_services(fund_id):
    require_role("Any")
    get_or_404("funds", fund_id)
    service_code = arg("service_code")
    from services import serialize_service
    rows = ordered([s for s in DB["services"].values() if s["fund_id"] == fund_id])
    rows = filtered(rows, service_code=service_code)
    return list_response(rows, serialize_service)
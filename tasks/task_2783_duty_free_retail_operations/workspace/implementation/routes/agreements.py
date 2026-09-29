"""Concession agreements: drafting, activation, projection and settlement (PRD section 3.10)."""
from flask import Blueprint

import clock
import db
import response
from errors import ApiError
from middleware import body, endpoint
from services import rent
from services.lookup import fetch, fetch_body, listing
from services.scope import STAFF_ROLES
from services.validate import PERIOD_CODE, req_int, req_string, req_ts

bp = Blueprint("agreements", __name__)


@bp.post("/concession-agreements")
@endpoint("TerminalAdmin")
def create_agreement():
    payload = body()
    terminal = fetch_body("terminals", "terminal_id", payload)
    period_code = req_string(payload, "period_code", pattern=PERIOD_CODE)
    period_start = req_ts(payload, "period_start_utc")
    period_end = req_ts(payload, "period_end_utc")
    if period_end <= period_start:
        raise ApiError("ERR_INVALID_REQUEST",
                       "period_end_utc must be strictly later than period_start_utc.")
    rent_pct_bps = req_int(payload, "rent_pct_bps", minimum=0, maximum=10000)
    minimum_guarantee_cents = req_int(payload, "minimum_guarantee_cents", minimum=0)
    if rent.agreement_for_period(terminal["id"], period_code) is not None:
        raise ApiError("ERR_DUPLICATE_AGREEMENT_PERIOD")
    agreement = db.base()
    agreement.update({
        "terminal_id": terminal["id"],
        "period_code": period_code,
        "period_start_utc": clock.fmt(period_start),
        "period_end_utc": clock.fmt(period_end),
        "rent_pct_bps": rent_pct_bps,
        "minimum_guarantee_cents": minimum_guarantee_cents,
        "status": "DRAFT",
        "gross_sales_cents": 0,
        "percentage_rent_cents": 0,
        "final_rent_cents": None,
        "marketing_credit_cents": None,
        "net_rent_cents": None,
        "rent_basis": None,
        "closed_at": None,
    })
    db.agreements[agreement["id"]] = agreement
    return response.created(db.public(agreement))


@bp.get("/concession-agreements/<agreement_id>")
@endpoint(*STAFF_ROLES)
def get_agreement(agreement_id):
    return response.single(db.public(fetch("agreements", agreement_id)))


@bp.get("/concession-agreements")
@endpoint(*STAFF_ROLES)
def list_agreements():
    rows, limit, offset, total = listing(
        db.agreements, ("terminal_id", "period_code", "status")
    )
    return response.collection(rows, limit, offset, total)


@bp.get("/concession-agreements/<agreement_id>/rent-projection")
@endpoint("TerminalAdmin")
def rent_projection(agreement_id):
    agreement = fetch("agreements", agreement_id)
    return response.single(rent.projection(agreement))


@bp.post("/concession-agreements/<agreement_id>/activate")
@endpoint("TerminalAdmin")
def activate_agreement(agreement_id):
    agreement = fetch("agreements", agreement_id)
    if agreement["status"] != "DRAFT":
        raise ApiError("ERR_AGREEMENT_NOT_ACTIVE")
    for other in db.agreements.values():
        if (other["id"] != agreement["id"]
                and other["terminal_id"] == agreement["terminal_id"]
                and other["status"] == "ACTIVE"):
            raise ApiError("ERR_AGREEMENT_ALREADY_ACTIVE")
    agreement["status"] = "ACTIVE"
    agreement["rent_basis"] = rent.derive_basis(
        agreement["percentage_rent_cents"], agreement["minimum_guarantee_cents"]
    )
    db.touch(agreement)
    return response.single(db.public(agreement))


@bp.post("/concession-agreements/<agreement_id>/close-period")
@endpoint("TerminalAdmin")
def close_period(agreement_id):
    agreement = fetch("agreements", agreement_id)
    if agreement["status"] != "ACTIVE":
        raise ApiError("ERR_AGREEMENT_NOT_ACTIVE")
    if clock.now() < clock.parse(agreement["period_end_utc"]):
        raise ApiError("ERR_PERIOD_NOT_ENDED")
    rent.settle(agreement)
    db.touch(agreement)
    return response.single(db.public(agreement))

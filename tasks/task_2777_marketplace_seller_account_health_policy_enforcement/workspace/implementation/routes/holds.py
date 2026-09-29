"""Disbursement holds: creation, release and forfeiture (PRD 3.9)."""

from datetime import timedelta

from flask import Blueprint, request

import clock
import constants as C
import db
import guards
import middleware as mw
import response
import serializers as ser
import validators as v
from errors import ApiError
from services import calc, notify

bp = Blueprint("holds", __name__)

BUFFER = timedelta(hours=C.HOLD_BUFFER_HOURS)


def _too_close(new_start, new_end, other):
    """Closed intervals must be separated by strictly more than 24 hours."""
    if new_start > other["coverage_end"]:
        return (new_start - other["coverage_end"]) <= BUFFER
    if new_end < other["coverage_start"]:
        return (other["coverage_start"] - new_end) <= BUFFER
    return True


@bp.post("/disbursement-holds")
@mw.require(C.ROLE_INVESTIGATOR)
def create_hold():
    data = v.body()
    seller = guards.body_fk(db.SELLERS, data.get("seller_id"), "ERR_SELLER_NOT_FOUND")
    action = guards.body_fk(db.ENFORCEMENT_ACTIONS, data.get("enforcement_action_id"),
                            "ERR_ACTION_NOT_FOUND")

    v.req_str(data, "seller_id", 1, None)
    if v.present(data, "enforcement_action_id"):
        v.req_str(data, "enforcement_action_id", 1, None)
    # A sweeping FULL_HOLD row is minted by cascades only, and reserve_basis NONE
    # exists only on those rows, so neither is a legitimate input here.
    hold_type = v.req_enum(data, "hold_type", ("RESERVE",))
    reserve_basis = v.req_enum(data, "reserve_basis", ("ROLLING", "CLAIM_EXPOSURE"))
    coverage_start = v.req_datetime(data, "coverage_start")
    coverage_end = v.req_datetime(data, "coverage_end")
    if coverage_end <= coverage_start:
        v.bad("'coverage_end' must be strictly later than 'coverage_start'.")
    expected_version = v.req_int(data, "expected_seller_version", minimum=0)
    if seller is None:
        raise ApiError("ERR_SELLER_NOT_FOUND")

    guards.ensure_not_banned(seller)

    if seller["disbursement_state"] == "NORMAL":
        raise ApiError("ERR_SELLER_NOT_UNDER_HOLD_POSTURE")
    if expected_version != seller["version"]:
        raise ApiError("ERR_STALE_SELLER_VERSION")

    for other in db.holds_of(seller["id"]):
        if other["state"] != "ACTIVE":
            continue
        if _too_close(coverage_start, coverage_end, other):
            raise ApiError("ERR_HOLD_COVERAGE_OVERLAP")

    if action is not None and action["seller_id"] != seller["id"]:
        raise ApiError("ERR_HOLD_ACTION_SELLER_MISMATCH")

    tier = calc.risk_tier(seller)
    amount = calc.reserve_requirement_cents(reserve_basis, tier, seller)
    if amount > seller["available_balance_cents"]:
        raise ApiError("ERR_HOLD_EXCEEDS_AVAILABLE")

    row = db.new_row(
        "hold",
        seller_id=seller["id"],
        enforcement_action_id=action["id"] if action is not None else None,
        hold_type=hold_type,
        reserve_basis=reserve_basis,
        risk_tier=tier,
        held_amount_cents=amount,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
        state="ACTIVE",
        auto_created=False,
        created_by_user_id=mw.actor(),
        released_at=None,
        release_reason=None,
        forfeited_amount_cents=0,
    )
    db.DISBURSEMENT_HOLDS[row["id"]] = row
    db.set_field(seller, "available_balance_cents",
                 seller["available_balance_cents"] - amount)
    db.set_field(seller, "held_balance_cents", seller["held_balance_cents"] + amount)
    db.mark_dirty(seller)
    notify.emit(seller["id"], "FUNDS_HELD", "DISBURSEMENT_HOLD", row["id"],
                amount_cents=amount)
    return response.one(row, ser.hold, 201)


@bp.get("/disbursement-holds")
@mw.require(C.ROLE_INVESTIGATOR, C.ROLE_OFFICER)
def list_holds():
    limit, offset = v.pagination()
    rows = db.sorted_rows(db.DISBURSEMENT_HOLDS)
    for field in ("seller_id", "enforcement_action_id", "state"):
        if field in request.args:
            wanted = request.args.get(field)
            rows = [r for r in rows if r.get(field) == wanted]
    page, total = response.paginate(rows, limit, offset)
    return response.many(page, ser.hold, limit, offset, total)


@bp.get("/disbursement-holds/<hold_id>")
@mw.require(C.ROLE_INVESTIGATOR, C.ROLE_OFFICER)
def read_hold(hold_id):
    return response.one(guards.hold(hold_id), ser.hold, 200)


@bp.post("/disbursement-holds/<hold_id>/release")
@mw.require(C.ROLE_OFFICER)
def release_hold(hold_id):
    hold = guards.hold(hold_id)
    mw.ensure_distinct(hold["created_by_user_id"])

    data = v.body()
    reason = v.req_enum(data, "release_reason", C.CALLER_RELEASE_REASONS)

    seller = db.SELLERS[hold["seller_id"]]
    guards.ensure_not_banned(seller)

    if hold["state"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")
    if hold["hold_type"] != "RESERVE":
        raise ApiError("ERR_HOLD_NOT_MANUALLY_RELEASABLE")

    amount = hold["held_amount_cents"]
    db.set_field(hold, "state", "RELEASED")
    db.set_field(hold, "released_at", clock.now())
    db.set_field(hold, "release_reason", reason)
    db.set_field(seller, "held_balance_cents", seller["held_balance_cents"] - amount)
    db.set_field(seller, "available_balance_cents",
                 seller["available_balance_cents"] + amount)
    db.mark_dirty(seller)
    notify.emit(seller["id"], "FUNDS_RELEASED", "DISBURSEMENT_HOLD", hold["id"],
                amount_cents=amount)
    return response.one(hold, ser.hold, 200)


@bp.post("/disbursement-holds/<hold_id>/forfeit")
@mw.require(C.ROLE_OFFICER)
def forfeit_hold(hold_id):
    hold = guards.hold(hold_id)
    mw.ensure_distinct(hold["created_by_user_id"])

    data = v.body()
    amount = v.req_int(data, "forfeited_amount_cents", minimum=0)

    # No ban check: forfeiture is legitimate only once the account is closed.
    seller = db.SELLERS[hold["seller_id"]]
    if hold["state"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")
    if seller["enforcement_state"] != "BANNED":
        raise ApiError("ERR_SELLER_NOT_BANNED")
    if amount > hold["held_amount_cents"]:
        raise ApiError("ERR_FORFEIT_EXCEEDS_HOLD")

    held = hold["held_amount_cents"]
    db.set_field(hold, "state", "FORFEITED")
    db.set_field(hold, "forfeited_amount_cents", amount)
    db.set_field(seller, "held_balance_cents", seller["held_balance_cents"] - held)
    db.set_field(seller, "lifetime_debited_cents",
                 seller["lifetime_debited_cents"] + amount)
    db.set_field(seller, "available_balance_cents",
                 seller["available_balance_cents"] + (held - amount))
    db.mark_dirty(seller)
    return response.one(hold, ser.hold, 200)

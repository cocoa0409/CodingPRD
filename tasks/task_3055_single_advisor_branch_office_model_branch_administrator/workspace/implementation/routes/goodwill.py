"""Goodwill transfer routes: valuation, negotiation, completion cascade (§3.7)."""
from datetime import timedelta
from decimal import Decimal
from flask import Blueprint, request

import db
from errors import err
from middleware import auth_context, require_role
from helpers import (
    body_json, require_fields, require_enum, parse_dt, get_or_404, stamp_new,
    touch, paginate, sort_by_created_at, round_half_up_cents, recompute_staffing,
)
from response import success_object, success_list

bp = Blueprint("goodwill", __name__)
PREFIX = "/branch-office/goodwill-transfers"

VALUATION_MODES = {"INTERNAL_SUCCESSION", "OPEN_MARKET"}
NEGOTIABLE = {"OFFERED", "NEGOTIATING"}


def _trailing_window(created):
    """[first day of (created_month - 12 months), first day of created_month)."""
    first_of_month = created.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    year = first_of_month.year
    month = first_of_month.month - 12
    while month <= 0:
        month += 12
        year -= 1
    start = first_of_month.replace(year=year, month=month)
    return start, first_of_month


def _trailing_revenue(branch_id, created):
    start, end = _trailing_window(created)
    total = 0
    for rec in db.production_records.values():
        if rec.get("status") != "POSTED":
            continue
        adv = db.advisors.get(rec.get("advisor_id"))
        if adv is None or adv.get("branch_id") != branch_id:
            continue
        posted = parse_dt(rec["posted_at"], "posted_at")
        if start <= posted < end:
            total += rec.get("gross_commission_cents", 0)
    return total


@bp.route(PREFIX, methods=["POST"])
def create_transfer():
    user_id, role = auth_context()
    require_role(role, {"HomeOfficeAdmin"})
    body = body_json()
    require_fields(body, ["branch_id", "retiring_advisor_id", "successor_advisor_id",
                          "valuation_mode", "escrow_deposit_cents"])
    branch = get_or_404(db.branches, body["branch_id"], "Branch")
    retiring = get_or_404(db.advisors, body["retiring_advisor_id"], "Advisor")
    successor = get_or_404(db.advisors, body["successor_advisor_id"], "Advisor")
    mode = require_enum(body, "valuation_mode", VALUATION_MODES)
    escrow = body["escrow_deposit_cents"]
    if isinstance(escrow, bool) or not isinstance(escrow, int) or escrow < 0:
        raise err("ERR_INVALID_REQUEST", "escrow_deposit_cents must be an integer >= 0.")
    created = db.clock.now()
    trailing = _trailing_revenue(branch["id"], created)
    multiple = Decimal("0.75") if mode == "INTERNAL_SUCCESSION" else Decimal("1.10")
    offer = round_half_up_cents(Decimal(trailing) * multiple)
    transfer = stamp_new({
        "branch_id": branch["id"],
        "retiring_advisor_id": retiring["id"],
        "successor_advisor_id": successor["id"],
        "valuation_mode": mode,
        "trailing_revenue_cents": trailing,
        "offer_price_cents": offer,
        "escrow_deposit_cents": escrow,
        "negotiation_round": 0,
        "status": "OFFERED",
        # The initial offer is made on the retiring advisor's behalf, so it is
        # the most recent offer for turn-alternation purposes.
        "_last_offer_by": retiring["id"],
    })
    db.goodwill_transfers[transfer["id"]] = transfer
    return success_object(_public(transfer), 201)


def _public(t):
    """Strip internal negotiation-tracking field."""
    return {k: v for k, v in t.items() if not k.startswith("_")}


@bp.route(PREFIX, methods=["GET"])
def list_transfers():
    user_id, role = auth_context()
    require_role(role, {"HomeOfficeAdmin", "Advisor"})
    items = list(db.goodwill_transfers.values())
    succ = request.args.get("successor_advisor_id")
    if succ:
        items = [t for t in items if t.get("successor_advisor_id") == succ]
    status = request.args.get("status")
    if status:
        items = [t for t in items if t.get("status") == status]
    items = sort_by_created_at(items)
    page, limit, offset, total, has_more = paginate([_public(t) for t in items])
    return success_list(page, limit, offset, total, has_more)


@bp.route(f"{PREFIX}/<tid>", methods=["GET"])
def get_transfer(tid):
    user_id, role = auth_context()
    require_role(role, {"HomeOfficeAdmin", "Advisor"})
    return success_object(_public(get_or_404(db.goodwill_transfers, tid, "GoodwillTransfer")))


def _check_party(t, user_id):
    if user_id not in (t.get("retiring_advisor_id"), t.get("successor_advisor_id")):
        raise err("ERR_UNAUTHORIZED", "Acting advisor is not a party to this transfer.")


def _check_turn(t, user_id):
    """Strict alternation: acting advisor must not have made the immediately preceding offer."""
    if t.get("_last_offer_by") == user_id:
        raise err("ERR_NEGOTIATION_TURN", "The acting advisor made the immediately preceding offer.")


@bp.route(f"{PREFIX}/<tid>/counter-offer", methods=["POST"])
def counter_offer(tid):
    user_id, role = auth_context()
    require_role(role, {"Advisor"})
    t = get_or_404(db.goodwill_transfers, tid, "GoodwillTransfer")
    _check_party(t, user_id)
    if t.get("status") not in NEGOTIABLE:
        raise err("ERR_INVALID_STATE", "Transfer is not OFFERED or NEGOTIATING.")
    _check_turn(t, user_id)
    body = body_json()
    require_fields(body, ["expected_transfer_version", "offer_price_cents"])
    price = body["offer_price_cents"]
    if isinstance(price, bool) or not isinstance(price, int) or price <= 0:
        raise err("ERR_INVALID_REQUEST", "offer_price_cents must be a positive integer.")
    ev = body["expected_transfer_version"]
    if isinstance(ev, bool) or not isinstance(ev, int):
        raise err("ERR_INVALID_REQUEST", "expected_transfer_version must be an integer.")
    if ev != t.get("version"):
        raise err("ERR_STALE_VERSION", "expected_transfer_version does not match the transfer's current version.")
    t["offer_price_cents"] = price
    t["negotiation_round"] = t.get("negotiation_round", 0) + 1
    t["status"] = "NEGOTIATING"
    t["_last_offer_by"] = user_id
    touch(t)
    return success_object(_public(t))


@bp.route(f"{PREFIX}/<tid>/accept", methods=["POST"])
def accept_transfer(tid):
    user_id, role = auth_context()
    require_role(role, {"Advisor"})
    t = get_or_404(db.goodwill_transfers, tid, "GoodwillTransfer")
    _check_party(t, user_id)
    if t.get("status") not in NEGOTIABLE:
        raise err("ERR_INVALID_STATE", "Transfer is not OFFERED or NEGOTIATING.")
    _check_turn(t, user_id)
    # escrow sufficiency: >= round_half_up(offer * 0.10)
    required = round_half_up_cents(Decimal(t.get("offer_price_cents", 0)) * Decimal("0.10"))
    if t.get("escrow_deposit_cents", 0) < required:
        raise err("ERR_ESCROW_INSUFFICIENT", "Escrow deposit is below 10% of the offer price.")
    t["status"] = "ACCEPTED"
    touch(t)
    return success_object(_public(t))


@bp.route(f"{PREFIX}/<tid>/decline", methods=["POST"])
def decline_transfer(tid):
    user_id, role = auth_context()
    require_role(role, {"Advisor"})
    t = get_or_404(db.goodwill_transfers, tid, "GoodwillTransfer")
    _check_party(t, user_id)
    if t.get("status") not in NEGOTIABLE:
        raise err("ERR_INVALID_STATE", "Transfer is not OFFERED or NEGOTIATING.")
    _check_turn(t, user_id)
    t["status"] = "DECLINED"
    t["escrow_deposit_cents"] = 0  # refunded
    touch(t)
    return success_object(_public(t))


@bp.route(f"{PREFIX}/<tid>/complete", methods=["POST"])
def complete_transfer(tid):
    user_id, role = auth_context()
    require_role(role, {"HomeOfficeAdmin"})
    t = get_or_404(db.goodwill_transfers, tid, "GoodwillTransfer")
    if t.get("status") != "ACCEPTED":
        raise err("ERR_INVALID_STATE", "Transfer is not ACCEPTED.")
    retiring = db.advisors.get(t.get("retiring_advisor_id"))
    successor = db.advisors.get(t.get("successor_advisor_id"))
    if retiring is None or successor is None:
        raise err("ERR_NOT_FOUND", "Transfer party not found.")
    if retiring.get("status") != "RETIRING":
        raise err("ERR_INVALID_STATE", "Retiring advisor is not RETIRING.")
    if successor.get("status") not in ("VALIDATED", "PRACTICING"):
        raise err("ERR_INVALID_STATE", "Successor advisor is not VALIDATED or PRACTICING.")
    # cascade
    retiring["status"] = "RETIRED"
    retiring["branch_id"] = None
    touch(retiring)
    successor["branch_id"] = t["branch_id"]
    successor["predecessor_advisor_id"] = retiring["id"]
    if successor.get("status") == "VALIDATED":
        successor["status"] = "PRACTICING"
    touch(successor)
    branch = db.branches.get(t["branch_id"])
    if branch is not None:
        recompute_staffing(branch)
        touch(branch)
    t["status"] = "COMPLETED"
    t["escrow_deposit_cents"] = 0  # applied to the sale; escrow balance returns to 0
    touch(t)
    return success_object(_public(t))


@bp.route(f"{PREFIX}/<tid>/cancel", methods=["POST"])
def cancel_transfer(tid):
    user_id, role = auth_context()
    require_role(role, {"HomeOfficeAdmin"})
    t = get_or_404(db.goodwill_transfers, tid, "GoodwillTransfer")
    if t.get("status") not in NEGOTIABLE:
        raise err("ERR_INVALID_STATE", "Transfer is not OFFERED or NEGOTIATING.")
    t["status"] = "CANCELLED"
    t["escrow_deposit_cents"] = 0  # refunded
    touch(t)
    return success_object(_public(t))


def expire_transfers():
    """Expire OFFERED/NEGOTIATING transfers whose created_at + 30 days <= clock (inclusive)."""
    now = db.clock.now()
    for t in db.goodwill_transfers.values():
        if t.get("status") in NEGOTIABLE:
            created = parse_dt(t["created_at"], "created_at")
            if now >= created + timedelta(days=30):
                t["status"] = "EXPIRED"
                t["escrow_deposit_cents"] = 0  # refunded
                touch(t)

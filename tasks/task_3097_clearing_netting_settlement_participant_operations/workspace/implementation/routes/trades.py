"""Trade submissions and the comparison state dimensions."""

from flask import Blueprint, request

from db import db
from errors import (
    api_error,
    ERR_FINANCIAL_STANDARD_NOT_MET,
    ERR_INVALID_REQUEST,
    ERR_PARTICIPANT_NOT_ACTIVE,
    ERR_PARTICIPANT_NOT_FOUND,
    ERR_RESOURCE_NOT_FOUND,
    ERR_SELF_TRADE_FORBIDDEN,
)
from middleware import CLEARING_MEMBER, PLATFORM_ADMIN, RISK_OFFICER, principal
from request import body, check_unknown, pagination, require
from routes.common import ok, ok_array, ok_list, paginate
from serializers import trade as serialize_trade
from services.trades import cancel, create_trade, dispute, lock_in, resolve_dispute, unmatch

bp = Blueprint("trades", __name__)

SIDES = ("BUY", "SELL")

CREATE_FIELDS = (
    "counterparty_participant_id",
    "security_id",
    "side",
    "quantity",
    "trade_price_cents",
    "trade_date",
)


def _acting_participant(actor):
    participant = db.participants.get(actor.user_id)
    if participant is None:
        raise api_error(ERR_PARTICIPANT_NOT_FOUND)
    return participant


@bp.post("/clearing/trade-submissions")
def create_trade_route():
    actor = principal((CLEARING_MEMBER,))
    participant = _acting_participant(actor)

    data = body()
    check_unknown(data, CREATE_FIELDS)
    counterparty_id = require(data, "counterparty_participant_id", type_=str)
    security_id = require(data, "security_id", type_=str)
    side = require(data, "side", type_=str, enum=SIDES)
    quantity = require(data, "quantity", type_=int, min_value=1)
    trade_price_cents = require(data, "trade_price_cents", type_=int, min_value=1)
    trade_date = require(data, "trade_date", type_=str)

    counterparty = db.participants.get(counterparty_id)
    if counterparty is None:
        raise api_error(ERR_PARTICIPANT_NOT_FOUND)
    if db.securities.get(security_id) is None:
        from errors import ERR_SECURITY_NOT_FOUND

        raise api_error(ERR_SECURITY_NOT_FOUND)

    if participant["membership_status"] != "ACTIVE":
        raise api_error(ERR_PARTICIPANT_NOT_ACTIVE)
    if participant["financial_standard_status"] == "FAIL":
        raise api_error(ERR_FINANCIAL_STANDARD_NOT_MET)
    if counterparty_id == participant["id"]:
        raise api_error(ERR_SELF_TRADE_FORBIDDEN)

    from timeutil import is_iso_instant, normalize_iso

    if not is_iso_instant(trade_date):
        raise api_error(ERR_INVALID_REQUEST, "trade_date must be an ISO 8601 UTC instant.")
    # Canonicalize the instant once, here. The normalized value is what both
    # the comparison tuple and the settlement-date derivation see, so two
    # spellings of the same instant always compare equal.
    normalized_trade_date = normalize_iso(trade_date)

    record = create_trade(
        participant["id"],
        counterparty_id,
        security_id,
        side,
        quantity,
        trade_price_cents,
        normalized_trade_date,
    )
    return ok(serialize_trade(record), 201)


@bp.get("/clearing/trade-submissions")
def list_trades_route():
    principal((PLATFORM_ADMIN, RISK_OFFICER, CLEARING_MEMBER))
    limit, offset = pagination()
    rows = list(db.trade_submissions.values())
    filters = {
        "participant_id": request.args.get("participant_id"),
        "counterparty_participant_id": request.args.get("counterparty_participant_id"),
        "security_id": request.args.get("security_id"),
        "lock_status": request.args.get("lock_status"),
        "match_status": request.args.get("match_status"),
    }
    for field, value in filters.items():
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    page, total = paginate(rows, limit, offset, lambda r: r["created_at"])
    return ok_list([serialize_trade(r) for r in page], limit, offset, total)


@bp.get("/clearing/trade-submissions/<tid>")
def read_trade_route(tid):
    principal((PLATFORM_ADMIN, RISK_OFFICER, CLEARING_MEMBER))
    record = db.trade_submissions.get(tid)
    if record is None:
        raise api_error(ERR_RESOURCE_NOT_FOUND)
    return ok(serialize_trade(record))


@bp.post("/clearing/trade-submissions/<tid>/lock-in")
def lock_in_route(tid):
    principal((CLEARING_MEMBER,))
    record = db.trade_submissions.get(tid)
    if record is None:
        raise api_error(ERR_RESOURCE_NOT_FOUND)
    lock_in(record)
    return ok(serialize_trade(record))


@bp.post("/clearing/trade-submissions/<tid>/dispute")
def dispute_route(tid):
    principal((CLEARING_MEMBER,))
    record = db.trade_submissions.get(tid)
    if record is None:
        raise api_error(ERR_RESOURCE_NOT_FOUND)
    dispute(record)
    return ok(serialize_trade(record))


@bp.post("/clearing/trade-submissions/<tid>/resolve-dispute")
def resolve_dispute_route(tid):
    principal((PLATFORM_ADMIN,))
    record = db.trade_submissions.get(tid)
    if record is None:
        raise api_error(ERR_RESOURCE_NOT_FOUND)
    resolve_dispute(record)
    return ok(serialize_trade(record))


@bp.post("/clearing/trade-submissions/<tid>/unmatch")
def unmatch_route(tid):
    principal((PLATFORM_ADMIN,))
    record = db.trade_submissions.get(tid)
    if record is None:
        raise api_error(ERR_RESOURCE_NOT_FOUND)
    unmatch(record)
    return ok(serialize_trade(record))


@bp.post("/clearing/trade-submissions/<tid>/cancel")
def cancel_route(tid):
    actor = principal((CLEARING_MEMBER, PLATFORM_ADMIN))
    record = db.trade_submissions.get(tid)
    if record is None:
        raise api_error(ERR_RESOURCE_NOT_FOUND)
    cancel(record, allow_privileged=(actor.role == PLATFORM_ADMIN))
    return ok(serialize_trade(record))
"""Preclearance requests: filing, decision, resubmission and execution."""

from datetime import timedelta

from flask import Blueprint, request

import auth
import clock
import envelope
import services
import store
import validate
from auth import AUDITOR, COMPLIANCE, PARTICIPANT, PLAN_ADMIN
from errors import ApiError, invalid

bp = Blueprint("preclearance", __name__)

LIST_READERS = (PLAN_ADMIN, COMPLIANCE, AUDITOR)
ROW_READERS = (PLAN_ADMIN, COMPLIANCE, AUDITOR, PARTICIPANT)
CLEARANCE_VALIDITY = timedelta(days=5)
MAX_PRECLEARANCE_REVISIONS = 2


def _trade_date_ok(window, trade_date):
    open_date = clock.parse_instant(window["open_at"]).date()
    close_date = clock.parse_instant(window["close_at"]).date()
    if not (open_date <= trade_date <= close_date):
        return False
    return trade_date >= clock.today()


def _check_cap(window, shares):
    cap = window["aggregate_share_cap"]
    if cap is not None and window["approved_shares_cumulative"] + shares > cap:
        raise ApiError("ERR_WINDOW_SHARE_CAP_EXCEEDED")


@bp.route("/preclearance-requests", methods=["POST"])
def create_request():
    actor = auth.begin(PARTICIPANT, COMPLIANCE)
    body = actor.body
    participant_ref = validate.raw_id(body, "participant_id")
    auth.scope(actor, participant_ref)
    if participant_ref is not None:
        services.participant_or_404(participant_ref)
    window_ref = validate.raw_id(body, "window_id")
    if window_ref is not None:
        services.window_or_404(window_ref)
    participant_id = validate.field_id(body, "participant_id")
    window_id = validate.field_id(body, "window_id")
    participant = services.participant_or_404(participant_id)
    window = services.window_or_404(window_id)
    transaction_type = validate.field_enum(
        body, "transaction_type", ("SELL", "BUY", "GIFT"))
    requested_shares = validate.field_int(body, "requested_shares", minimum=1)
    intended_trade_date = validate.field_date(body, "intended_trade_date")

    if not services.window_is_tradeable(window):
        raise ApiError("ERR_TRADING_WINDOW_CLOSED")
    if participant["employment_status"] != "ACTIVE":
        raise ApiError("ERR_PARTICIPANT_NOT_ACTIVE")
    if not _trade_date_ok(window, intended_trade_date):
        raise ApiError("ERR_TRADE_DATE_OUTSIDE_WINDOW")
    _check_cap(window, requested_shares)

    row = store.base_row()
    row.update({
        "participant_id": participant_id,
        "window_id": window_id,
        "transaction_type": transaction_type,
        "requested_shares": requested_shares,
        "intended_trade_date": clock.fmt_date(intended_trade_date),
        "requested_by_user_id": actor.user_id,
        "status": "SUBMITTED",
        "revision_count": 0,
        "decided_by_user_id": None,
        "decided_at": None,
        "decision_note": None,
        "valid_until": None,
        "executed_shares": 0,
        "executed_at": None,
        "price_per_share_cents": None,
    })
    store.preclearances[row["id"]] = row
    return envelope.created(store.public(row))


@bp.route("/preclearance-requests", methods=["GET"])
def list_requests():
    auth.begin(*LIST_READERS)
    rows = list(store.preclearances.values())
    for param in ("participant_id", "window_id", "status"):
        value = request.args.get(param)
        if value is not None:
            rows = [r for r in rows if r[param] == value]
    return envelope.page(store.sort_default(rows))


@bp.route("/preclearance-requests/<request_id>", methods=["GET"])
def read_request(request_id):
    actor = auth.begin(*ROW_READERS)
    row = services.preclearance_or_404(request_id)
    auth.scope(actor, row["participant_id"])
    return envelope.ok(store.public(row))


@bp.route("/preclearance-requests/<request_id>/decide", methods=["POST"])
def decide_request(request_id):
    actor = auth.begin(COMPLIANCE)
    row = services.preclearance_or_404(request_id)
    decision = validate.field_enum(
        actor.body, "decision", ("REQUEST_INFO", "APPROVE", "DENY"))
    note = validate.field_str(actor.body, "decision_note", required=False)
    if row["status"] != "SUBMITTED":
        raise ApiError("ERR_PRECLEARANCE_INVALID_STATE")
    if actor.user_id == row["requested_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    window = store.windows[row["window_id"]]
    now = clock.now()

    if decision == "REQUEST_INFO":
        if row["revision_count"] >= MAX_PRECLEARANCE_REVISIONS:
            raise ApiError("ERR_MAX_PRECLEARANCE_REVISIONS_EXCEEDED")
        row["status"] = "INFO_REQUESTED"
        row["decision_note"] = note
        row["decided_by_user_id"] = actor.user_id
        row["decided_at"] = clock.fmt_instant(now)
    elif decision == "DENY":
        row["status"] = "DENIED"
        row["decision_note"] = note
        row["decided_by_user_id"] = actor.user_id
        row["decided_at"] = clock.fmt_instant(now)
    else:
        if not services.window_is_tradeable(window):
            raise ApiError("ERR_TRADING_WINDOW_CLOSED")
        participant = store.participants[row["participant_id"]]
        if participant["employment_status"] != "ACTIVE":
            raise ApiError("ERR_PARTICIPANT_NOT_ACTIVE")
        if not _trade_date_ok(window, clock.parse_date(row["intended_trade_date"])):
            raise ApiError("ERR_TRADE_DATE_OUTSIDE_WINDOW")
        for plan in store.trading_plans.values():
            if (plan["participant_id"] == row["participant_id"]
                    and plan["status"] == "EFFECTIVE"):
                raise ApiError("ERR_TRADING_PLAN_CONFLICT")
        _check_cap(window, row["requested_shares"])
        row["status"] = "APPROVED"
        row["decision_note"] = note
        row["decided_by_user_id"] = actor.user_id
        row["decided_at"] = clock.fmt_instant(now)
        horizon = now + CLEARANCE_VALIDITY
        close_at = clock.parse_instant(window["close_at"])
        row["valid_until"] = clock.fmt_instant(min(horizon, close_at))
        window["approved_shares_cumulative"] += row["requested_shares"]
        store.touch(window)
    store.touch(row)
    return envelope.ok(store.public(row))


@bp.route("/preclearance-requests/<request_id>/resubmit", methods=["POST"])
def resubmit_request(request_id):
    actor = auth.begin(PARTICIPANT, COMPLIANCE)
    row = services.preclearance_or_404(request_id)
    auth.scope(actor, row["participant_id"])
    requested_shares = validate.field_int(actor.body, "requested_shares", minimum=1)
    intended_trade_date = validate.field_date(actor.body, "intended_trade_date")
    if row["status"] != "INFO_REQUESTED":
        raise ApiError("ERR_PRECLEARANCE_INVALID_STATE")
    participant = store.participants[row["participant_id"]]
    if participant["employment_status"] != "ACTIVE":
        raise ApiError("ERR_PARTICIPANT_NOT_ACTIVE")
    window = store.windows[row["window_id"]]
    if not _trade_date_ok(window, intended_trade_date):
        raise ApiError("ERR_TRADE_DATE_OUTSIDE_WINDOW")
    _check_cap(window, requested_shares)
    row["status"] = "SUBMITTED"
    row["requested_shares"] = requested_shares
    row["intended_trade_date"] = clock.fmt_date(intended_trade_date)
    row["decision_note"] = None
    row["revision_count"] += 1
    store.touch(row)
    return envelope.ok(store.public(row))


@bp.route("/preclearance-requests/<request_id>/execute", methods=["POST"])
def execute_request(request_id):
    actor = auth.begin(PARTICIPANT, COMPLIANCE)
    row = services.preclearance_or_404(request_id)
    auth.scope(actor, row["participant_id"])
    executed_shares = validate.field_int(actor.body, "executed_shares", minimum=1)
    price = validate.field_int(actor.body, "price_per_share_cents", minimum=0)
    if row["status"] != "APPROVED":
        raise ApiError("ERR_PRECLEARANCE_INVALID_STATE")
    now = clock.now()
    if row["valid_until"] is not None and now > clock.parse_instant(row["valid_until"]):
        raise ApiError("ERR_PRECLEARANCE_EXPIRED")
    if executed_shares > row["requested_shares"]:
        raise invalid("executed_shares may not exceed requested_shares.")
    window = store.windows[row["window_id"]]
    if not services.window_is_tradeable(window):
        raise ApiError("ERR_TRADING_WINDOW_CLOSED")
    row["status"] = "EXECUTED"
    row["executed_shares"] = executed_shares
    row["price_per_share_cents"] = price
    row["executed_at"] = clock.fmt_instant(now)
    store.touch(row)
    participant = store.participants[row["participant_id"]]
    services.maybe_create_report(
        participant, "PRECLEARANCE_EXECUTION", row["id"], now, executed_shares)
    return envelope.ok(store.public(row))

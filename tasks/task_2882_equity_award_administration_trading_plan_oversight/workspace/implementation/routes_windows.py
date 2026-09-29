"""Trading windows and their lifecycle."""

from datetime import timedelta

from flask import Blueprint, request

import auth
import clock
import envelope
import services
import store
import validate
from auth import AUDITOR, BOARD, COMPLIANCE, DELEGATED, PARTICIPANT, PLAN_ADMIN
from errors import ApiError

bp = Blueprint("windows", __name__)

WINDOW_READERS = (PLAN_ADMIN, BOARD, DELEGATED, COMPLIANCE, AUDITOR, PARTICIPANT)
BLACKOUT_BUFFER = timedelta(hours=48)
NON_CLOSED = ("SCHEDULED", "OPEN", "SUSPENDED")


@bp.route("/trading-windows", methods=["POST"])
def schedule_window():
    actor = auth.begin(COMPLIANCE)
    body = actor.body
    plan_ref = validate.raw_id(body, "plan_id")
    if plan_ref is not None:
        services.plan_or_404(plan_ref)
    plan_id = validate.field_id(body, "plan_id")
    plan = services.plan_or_404(plan_id)
    quarter_label = validate.field_str(body, "quarter_label")
    open_at = validate.field_instant(body, "open_at")
    close_at = validate.field_instant(body, "close_at")
    if close_at <= open_at:
        raise ApiError("ERR_INVALID_REQUEST", "close_at must be strictly after open_at.")
    cap = validate.field_int(body, "aggregate_share_cap", required=False, minimum=1)
    services.require_plan_active(plan)

    siblings = [
        w for w in store.windows.values()
        if w["plan_id"] == plan_id and w["status"] in NON_CLOSED
    ]
    for other in siblings:
        other_open = clock.parse_instant(other["open_at"])
        other_close = clock.parse_instant(other["close_at"])
        if open_at < other_close and other_open < close_at:
            raise ApiError("ERR_TRADING_WINDOW_OVERLAP")
    for other in siblings:
        other_close = clock.parse_instant(other["close_at"])
        if other_close <= open_at and (open_at - other_close) < BLACKOUT_BUFFER:
            raise ApiError("ERR_TRADING_WINDOW_BUFFER_VIOLATION")

    row = store.base_row()
    row.update({
        "plan_id": plan_id,
        "quarter_label": quarter_label,
        "open_at": clock.fmt_instant(open_at),
        "close_at": clock.fmt_instant(close_at),
        "aggregate_share_cap": cap,
        "status": "SCHEDULED",
        "approved_shares_cumulative": 0,
        "suspension_reason": None,
    })
    store.windows[row["id"]] = row
    return envelope.created(store.public(row))


@bp.route("/trading-windows/<window_id>", methods=["GET"])
def read_window(window_id):
    auth.begin(*WINDOW_READERS)
    return envelope.ok(store.public(services.window_or_404(window_id)))


@bp.route("/equity-plans/<plan_id>/trading-windows", methods=["GET"])
def list_windows(plan_id):
    auth.begin(*WINDOW_READERS)
    services.plan_or_404(plan_id)
    rows = [w for w in store.windows.values() if w["plan_id"] == plan_id]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return envelope.page(store.sort_by(rows, "open_at"))


@bp.route("/trading-windows/<window_id>/status", methods=["POST"])
def window_status(window_id):
    actor = auth.begin(COMPLIANCE)
    window = services.window_or_404(window_id)
    action = validate.field_enum(
        actor.body, "action", ("OPEN", "SUSPEND", "RESUME", "CLOSE"))
    reason = validate.field_str(actor.body, "suspension_reason", required=False)
    current = window["status"]
    if action == "OPEN":
        if current != "SCHEDULED":
            raise ApiError("ERR_WINDOW_INVALID_STATE")
        services.require_plan_not_terminated(services.plan_or_404(window["plan_id"]))
        window["status"] = "OPEN"
    elif action == "SUSPEND":
        if current != "OPEN":
            raise ApiError("ERR_WINDOW_INVALID_STATE")
        window["status"] = "SUSPENDED"
        window["suspension_reason"] = reason
        services.suspend_window_cascade(window, reason)
    elif action == "RESUME":
        if current != "SUSPENDED":
            raise ApiError("ERR_WINDOW_INVALID_STATE")
        window["status"] = "OPEN"
        window["suspension_reason"] = None
    else:
        if current not in NON_CLOSED:
            raise ApiError("ERR_WINDOW_INVALID_STATE")
        window["status"] = "CLOSED"
        services.close_window_cascade(window)
    store.touch(window)
    return envelope.ok(store.public(window))

"""FeeSchedule routes: create with window tiling validation, get, list."""
from flask import Blueprint, request

from auth import require_roles, ALL_ROLES
from store import db
from response import ok, ok_list, ApiError, err_not_found, err_invalid_request
from helpers import new_record, paginate, sort_by_created, reevaluate, _recompute_schedule_status
from clock import parse
import views

bp = Blueprint("fee_schedules", __name__)


def get_schedule_or_404(sid):
    s = db["fee_schedules"].get(sid)
    if not s:
        raise err_not_found("FeeSchedule not found")
    return s


def _check_window_tiling(new_from, new_to, exclude_id=None):
    """Windows must not overlap; when a predecessor exists, new window must
    start exactly at the predecessor's effective_to (gap=0 adjacency)."""
    siblings = [s for s in db["fee_schedules"].values() if s["id"] != exclude_id]
    # overlap check
    for s in siblings:
        ef, et = parse(s["effective_from"]), parse(s["effective_to"])
        if new_from < et and ef < new_to:
            raise ApiError("ERR_SCHEDULE_WINDOW_VIOLATION", 409,
                           "Schedule window overlaps a sibling schedule")
    # adjacency: if any sibling ends at or before new_from, the latest such
    # must end exactly at new_from
    preds = [s for s in siblings if parse(s["effective_to"]) <= new_from]
    if preds:
        latest_end = max(parse(s["effective_to"]) for s in preds)
        if latest_end != new_from:
            raise ApiError("ERR_SCHEDULE_WINDOW_VIOLATION", 409,
                           "New schedule must start exactly at the predecessor's effective_to")
    # if any sibling starts after new_from, the earliest such must start exactly at new_to
    succs = [s for s in siblings if parse(s["effective_from"]) >= new_to]
    if succs:
        earliest_start = min(parse(s["effective_from"]) for s in succs)
        if earliest_start != new_to:
            raise ApiError("ERR_SCHEDULE_WINDOW_VIOLATION", 409,
                           "New schedule must end exactly at the successor's effective_from")


@bp.route("/fee-schedules", methods=["POST"])
def create_schedule():
    require_roles("BrokerOfRecord")
    body = request.get_json(silent=True) or {}

    def need_int(key, lo=None, hi=None):
        v = body.get(key)
        if not isinstance(v, int) or isinstance(v, bool):
            raise err_invalid_request(f"{key} is required and must be an integer")
        if lo is not None and v < lo:
            raise err_invalid_request(f"{key} must be >= {lo}")
        if hi is not None and v > hi:
            raise err_invalid_request(f"{key} must be <= {hi}")
        return v

    name = body.get("schedule_name")
    if not isinstance(name, str) or not name:
        raise err_invalid_request("schedule_name is required")
    desk_fee = need_int("desk_fee_cents", 0)
    overhead = need_int("overhead_share_bps", 0, 10000)
    retention = need_int("retention_bps", 0, 10000)
    referral = need_int("referral_fee_bps", 0, 5000)
    tech = need_int("tech_subscription_monthly_cents", 0)
    marketing = need_int("marketing_monthly_cents", 0)
    ef_s = body.get("effective_from")
    et_s = body.get("effective_to")
    ef = parse(ef_s)
    et = parse(et_s)
    if ef is None or et is None:
        raise err_invalid_request("effective_from and effective_to must be ISO-8601 timestamps")
    if et <= ef:
        raise err_invalid_request("effective_to must be after effective_from")
    _check_window_tiling(ef, et)
    rec = new_record()
    rec.update({
        "schedule_name": name,
        "desk_fee_cents": desk_fee,
        "overhead_share_bps": overhead,
        "retention_bps": retention,
        "referral_fee_bps": referral,
        "tech_subscription_monthly_cents": tech,
        "marketing_monthly_cents": marketing,
        "effective_from": ef_s,
        "effective_to": et_s,
        "status": "DRAFT",
    })
    _recompute_schedule_status(rec)
    db["fee_schedules"][rec["id"]] = rec
    return ok(views.schedule_view(rec), 201)


@bp.route("/fee-schedules/<scheduleId>", methods=["GET"])
def get_schedule(scheduleId):
    require_roles(*ALL_ROLES)
    reevaluate()
    s = get_schedule_or_404(scheduleId)
    return ok(views.schedule_view(s))


@bp.route("/fee-schedules", methods=["GET"])
def list_schedules():
    require_roles(*ALL_ROLES)
    reevaluate()
    items = list(db["fee_schedules"].values())
    args = request.args
    if args.get("status") is not None:
        items = [s for s in items if s["status"] == args.get("status")]
    if args.get("fee_schedule_id") is not None:
        items = [s for s in items if s["id"] == args.get("fee_schedule_id")]
    items = sort_by_created(items)
    page, total, limit, offset = paginate(items)
    return ok_list([views.schedule_view(s) for s in page], total, limit, offset)

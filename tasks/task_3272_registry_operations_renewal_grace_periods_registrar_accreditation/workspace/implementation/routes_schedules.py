from datetime import timedelta
from decimal import Decimal

import db
import clock
import fiscal
from util import fmt_iso, parse_iso, round_half_up_cents
from services import schedule_view, ANNUAL_CAP_RATE, NOTICE_DAYS
from middleware import require_roles, body_json, require_fields, pagination_params
from response import success_object, success_list
from errors import err_invalid_request, err_not_found, ApiError
from flask import Blueprint, request

bp = Blueprint("price_schedules", __name__)

FEE_FIELDS = ["create_fee_cents", "renew_fee_cents", "restore_fee_cents", "transfer_fee_cents"]


def _jan1_baseline(effective_on):
    """Schedule EFFECTIVE on Jan 1 of effective_on's calendar year; else first ever proposed."""
    year = effective_on.year
    jan1 = effective_on.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    chosen = None
    for s in db.price_schedules.values():
        if parse_iso(s["effective_on"]) <= jan1:
            if chosen is None or parse_iso(s["effective_on"]) > parse_iso(chosen["effective_on"]):
                chosen = s
    if chosen is None:
        rows = sorted(db.price_schedules.values(), key=lambda s: (s["created_at"], s["id"]))
        if rows:
            chosen = rows[0]
    return chosen


@bp.post("/price-schedules")
def create_schedule():
    require_roles("RegistryAdmin")
    data = body_json()
    require_fields(data, FEE_FIELDS + ["effective_on"])
    fees = {}
    for f in FEE_FIELDS:
        v = data[f]
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise err_invalid_request(f"{f} must be a non-negative integer")
        fees[f] = v
    try:
        effective_on = parse_iso(data["effective_on"])
    except Exception:
        raise err_invalid_request("effective_on must be an ISO-8601 datetime")
    now = clock.now()
    if effective_on <= now:
        raise err_invalid_request("effective_on must be strictly in the future")
    supersedes = data.get("supersedes_schedule_id")
    if supersedes is not None:
        if not isinstance(supersedes, str) or supersedes not in db.price_schedules:
            raise err_not_found("supersedes_schedule_id does not exist")
    # price cap vs Jan-1 baseline
    baseline = _jan1_baseline(effective_on)
    if baseline is not None:
        for f in FEE_FIELDS:
            ceiling = round_half_up_cents(Decimal(baseline[f]) * (Decimal(1) + ANNUAL_CAP_RATE))
            if fees[f] > ceiling:
                raise ApiError("ERR_PRICE_CAP_EXCEEDED",
                               f"{f} exceeds Jan-1 baseline * 1.10", 409)
    # 180-day notice
    if effective_on - now < timedelta(days=NOTICE_DAYS):
        raise ApiError("ERR_PRICE_NOTICE_TOO_SHORT",
                       "effective_on - announced_at < 180 days", 409)
    rec = db.new_common(now)
    rec.update({
        **fees,
        "effective_on": fmt_iso(effective_on),
        "announced_at": fmt_iso(now),
        "supersedes_schedule_id": supersedes,
        "status": "PROPOSED",
    })
    db.price_schedules[rec["id"]] = rec
    fiscal.emit_announced_notices(rec)
    return success_object(schedule_view(rec), 201)


@bp.get("/price-schedules")
def list_schedules():
    require_roles("RegistryAdmin", "RegistrarOperator", "RegistryFinance")
    limit, offset = pagination_params()
    rows = sorted(db.price_schedules.values(), key=lambda s: s["created_at"])
    status = request.args.get("status")
    sup = request.args.get("supersedes_schedule_id")
    if status:
        rows = [s for s in rows if s["status"] == status]
    if sup:
        rows = [s for s in rows if s["supersedes_schedule_id"] == sup]
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([schedule_view(s) for s in page], limit, offset, total)


@bp.get("/price-schedules/<sid>")
def get_schedule(sid):
    require_roles("RegistryAdmin", "RegistrarOperator", "RegistryFinance")
    s = db.price_schedules.get(sid)
    if s is None:
        raise err_not_found()
    return success_object(schedule_view(s))

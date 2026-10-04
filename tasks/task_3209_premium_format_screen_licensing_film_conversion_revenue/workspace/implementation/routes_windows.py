"""ReleaseWindow endpoints."""
from __future__ import annotations

from flask import Blueprint, request

from db import db
from errors import (
    ERR_WINDOW_NOT_FOUND, ERR_INVALID_STATE, ERR_WINDOW_IN_PAST,
    conflict, not_found,
)
from util import (
    require_role, get_body, req_str, req_int, parse_pagination, paginate,
    success_object, success_list, stamp_new, touch, sort_by_created,
    parse_iso_datetime, iso_format,
)
from domain import (
    serialize_release_window, serialize_screen_slot, serialize_revenue_share_statement,
)

bp = Blueprint("release_windows", __name__)


def get_window_or_404(window_id):
    w = db.release_windows.get(window_id)
    if w is None:
        raise not_found(ERR_WINDOW_NOT_FOUND, f"Release window {window_id} not found")
    return w


@bp.post("/v1/release-windows")
def create_window():
    require_role("ReleaseScheduler")
    body = get_body()
    window_label = req_str(body, "window_label")
    start = parse_iso_datetime(body.get("window_start_date"), "window_start_date")
    end = parse_iso_datetime(body.get("window_end_date"), "window_end_date")
    pool = req_int(body, "total_premium_screen_seconds_pool")

    from errors import bad_request, ERR_INVALID_REQUEST
    for w in db.release_windows.values():
        if w.get("window_label") == window_label:
            raise bad_request(ERR_INVALID_REQUEST, "window_label must be unique")

    win = {
        "window_label": window_label,
        "window_start_date": iso_format(start),
        "window_end_date": iso_format(end),
        "_window_start_date_dt": start,
        "_window_end_date_dt": end,
        "total_premium_screen_seconds_pool": pool,
        "committed_premium_screen_seconds": 0,
        "status": "DRAFT",
    }
    stamp_new(win)
    db.release_windows[win["id"]] = win
    return success_object(serialize_release_window(win), 201)


@bp.get("/v1/release-windows")
def list_windows():
    require_role("ReleaseScheduler", "BoxOfficeAnalyst", "PlatformContractManager", "NetworkPlanner")
    limit, offset = parse_pagination()
    items = sort_by_created(list(db.release_windows.values()))
    status = request.args.get("status")
    if status:
        items = [w for w in items if w.get("status") == status]
    page, total = paginate(items, limit, offset)
    return success_list([serialize_release_window(w) for w in page], total, limit, offset)


@bp.get("/v1/release-windows/<window_id>")
def get_window(window_id):
    require_role("ReleaseScheduler", "BoxOfficeAnalyst", "PlatformContractManager", "NetworkPlanner")
    w = get_window_or_404(window_id)
    return success_object(serialize_release_window(w))


@bp.post("/v1/release-windows/<window_id>/open")
def open_window(window_id):
    require_role("ReleaseScheduler")
    w = get_window_or_404(window_id)
    if w.get("status") != "DRAFT":
        raise conflict(ERR_INVALID_STATE, f"Window in state {w.get('status')} cannot open")
    if not (w["_window_start_date_dt"] > db.logical_clock):
        raise conflict(ERR_WINDOW_IN_PAST, "window_start_date must be strictly in the future")
    w["status"] = "OPEN_FOR_BOOKING"
    touch(w)
    return success_object(serialize_release_window(w))


@bp.post("/v1/release-windows/<window_id>/lock")
def lock_window(window_id):
    require_role("ReleaseScheduler")
    w = get_window_or_404(window_id)
    if w.get("status") != "OPEN_FOR_BOOKING":
        raise conflict(ERR_INVALID_STATE, f"Window in state {w.get('status')} cannot lock")
    w["status"] = "LOCKED"
    touch(w)
    for slot in db.screen_slots.values():
        if slot.get("window_id") == w["id"] and slot.get("status") == "PROPOSED":
            slot["status"] = "REJECTED"
            touch(slot)
    return success_object(serialize_release_window(w))


@bp.post("/v1/release-windows/<window_id>/reopen")
def reopen_window(window_id):
    require_role("ReleaseScheduler")
    w = get_window_or_404(window_id)
    if w.get("status") != "LOCKED":
        raise conflict(ERR_INVALID_STATE, f"Window in state {w.get('status')} cannot reopen")
    w["status"] = "REOPENED"
    touch(w)
    return success_object(serialize_release_window(w))


@bp.post("/v1/release-windows/<window_id>/resume-booking")
def resume_booking(window_id):
    require_role("ReleaseScheduler")
    w = get_window_or_404(window_id)
    if w.get("status") != "REOPENED":
        raise conflict(ERR_INVALID_STATE, f"Window in state {w.get('status')} cannot resume booking")
    w["status"] = "OPEN_FOR_BOOKING"
    touch(w)
    return success_object(serialize_release_window(w))


@bp.get("/v1/release-windows/<window_id>/screen-slots")
def list_window_slots(window_id):
    require_role("ReleaseScheduler", "BoxOfficeAnalyst")
    w = get_window_or_404(window_id)
    limit, offset = parse_pagination()
    items = [s for s in db.screen_slots.values() if s.get("window_id") == w["id"]]
    status = request.args.get("status")
    if status:
        items = [s for s in items if s.get("status") == status]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return success_list([serialize_screen_slot(s) for s in page], total, limit, offset)


@bp.get("/v1/release-windows/<window_id>/revenue-share-statements")
def list_window_statements(window_id):
    require_role("ReleaseScheduler", "BoxOfficeAnalyst", "PlatformContractManager")
    w = get_window_or_404(window_id)
    limit, offset = parse_pagination()
    items = [s for s in db.revenue_share_statements.values() if s.get("window_id") == w["id"]]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return success_list([serialize_revenue_share_statement(s) for s in page], total, limit, offset)

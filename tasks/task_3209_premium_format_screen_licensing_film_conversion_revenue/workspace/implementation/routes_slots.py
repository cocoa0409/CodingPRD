"""ScreenSlot endpoints."""
from __future__ import annotations

from flask import Blueprint, request

from db import db
from errors import (
    ERR_SLOT_NOT_FOUND, ERR_WINDOW_NOT_FOUND, ERR_AUDITORIUM_NOT_FOUND,
    ERR_FILM_NOT_FOUND, ERR_CONVERSION_ORDER_NOT_FOUND, ERR_INVALID_STATE,
    ERR_WINDOW_NOT_OPEN, ERR_AUDITORIUM_NOT_READY, ERR_CONVERSION_NOT_APPROVED,
    ERR_SLOT_OVERLAP, ERR_SLOT_OUTSIDE_WINDOW, ERR_WINDOW_CAPACITY_EXCEEDED,
    ERR_SLOT_ALREADY_STARTED, ERR_STALE_VERSION, ERR_INVALID_REQUEST,
    bad_request, conflict, not_found, ApiError,
)
from util import (
    require_role, require_auth, get_body, req_str, req_int, opt_enum,
    parse_pagination, paginate, success_object, success_list, stamp_new, touch,
    sort_by_created, parse_iso_datetime, iso_format, forbidden,
)
from domain import (
    serialize_screen_slot, serialize_box_office_report,
    recompute_slot_derived, recompute_window_committed, recompute_statements_for_slot,
)

bp = Blueprint("screen_slots", __name__)

PRIORITY_ORDER = {"BLOCKBUSTER": 0, "STANDARD": 1, "FILLER": 2}


def get_slot_or_404(slot_id):
    s = db.screen_slots.get(slot_id)
    if s is None:
        raise not_found(ERR_SLOT_NOT_FOUND, f"Slot {slot_id} not found")
    return s


@bp.post("/v1/screen-slots")
def create_slot():
    require_role("ReleaseScheduler")
    body = get_body()
    window_id = req_str(body, "window_id")
    auditorium_id = req_str(body, "auditorium_id")
    studio_film_id = req_str(body, "studio_film_id")
    conversion_order_id = req_str(body, "conversion_order_id")
    start = parse_iso_datetime(body.get("slot_start_date"), "slot_start_date")
    end = parse_iso_datetime(body.get("slot_end_date"), "slot_end_date")
    showings_per_day = req_int(body, "showings_per_day")
    if showings_per_day < 1:
        raise bad_request(ERR_INVALID_REQUEST, "showings_per_day must be >= 1")
    priority_tier = opt_enum(body, "priority_tier",
                             {"BLOCKBUSTER", "STANDARD", "FILLER"}, "STANDARD")
    expected_window_version = body.get("expected_window_version")
    if expected_window_version is None or isinstance(expected_window_version, bool) \
            or not isinstance(expected_window_version, int):
        raise bad_request(ERR_INVALID_REQUEST, "expected_window_version is required and must be an integer")

    # Body FK existence in declared input order: window, auditorium, film, conversion
    win = db.release_windows.get(window_id)
    if win is None:
        raise not_found(ERR_WINDOW_NOT_FOUND, f"Window {window_id} not found")
    if auditorium_id not in db.auditoriums:
        raise not_found(ERR_AUDITORIUM_NOT_FOUND, f"Auditorium {auditorium_id} not found")
    if studio_film_id not in db.films:
        raise not_found(ERR_FILM_NOT_FOUND, f"Film {studio_film_id} not found")
    if conversion_order_id not in db.conversion_orders:
        raise not_found(ERR_CONVERSION_ORDER_NOT_FOUND,
                        f"Conversion order {conversion_order_id} not found")

    days = (end - start).days
    if days < 1:
        raise bad_request(ERR_INVALID_REQUEST, "slot duration must be at least 1 day")

    # Slot interval must lie within window bounds
    if start < win["_window_start_date_dt"] or end > win["_window_end_date_dt"]:
        raise conflict(ERR_SLOT_OUTSIDE_WINDOW, "Slot interval outside window bounds")

    # OCC check
    if expected_window_version != win.get("version"):
        raise ApiError(ERR_STALE_VERSION,
                       "expected_window_version does not match ReleaseWindow.version", 412)

    slot = {
        "window_id": window_id,
        "auditorium_id": auditorium_id,
        "studio_film_id": studio_film_id,
        "conversion_order_id": conversion_order_id,
        "slot_start_date": iso_format(start),
        "slot_end_date": iso_format(end),
        "_slot_start_dt": start,
        "_slot_end_dt": end,
        "showings_per_day": showings_per_day,
        "priority_tier": priority_tier,
        "weekly_gross_cents": 0,
        "weekly_admissions": 0,
        "per_screen_attendance_ratio": 0,
        "status": "PROPOSED",
    }
    stamp_new(slot)
    recompute_slot_derived(slot)
    db.screen_slots[slot["id"]] = slot
    # Screen-slot creation bumps parent window version
    touch(win)
    return success_object(serialize_screen_slot(slot), 201)


@bp.get("/v1/screen-slots")
def list_slots():
    require_role("ReleaseScheduler", "BoxOfficeAnalyst", "PlatformContractManager")
    limit, offset = parse_pagination()
    items = sort_by_created(list(db.screen_slots.values()))
    for key in ("window_id", "auditorium_id", "studio_film_id", "conversion_order_id", "status"):
        v = request.args.get(key)
        if v:
            items = [s for s in items if s.get(key) == v]
    page, total = paginate(items, limit, offset)
    return success_list([serialize_screen_slot(s) for s in page], total, limit, offset)


@bp.get("/v1/screen-slots/<slot_id>")
def get_slot(slot_id):
    require_role("ReleaseScheduler", "BoxOfficeAnalyst", "PlatformContractManager", "StudioRelationshipManager")
    s = get_slot_or_404(slot_id)
    return success_object(serialize_screen_slot(s))


def _slot_fits_capacity(win, slot):
    return win.get("committed_premium_screen_seconds", 0) + slot.get("committed_screen_seconds", 0) \
        <= win.get("total_premium_screen_seconds_pool", 0)


def _slot_overlaps_existing(slot):
    for other in db.screen_slots.values():
        if other["id"] == slot["id"]:
            continue
        if other.get("auditorium_id") != slot.get("auditorium_id"):
            continue
        if other.get("status") not in ("CONFIRMED", "HELD_OVER"):
            continue
        # half-open [start, end) overlap: start < other.end AND other.start < end
        if slot["_slot_start_dt"] < other["_slot_end_dt"] and other["_slot_start_dt"] < slot["_slot_end_dt"]:
            return True
    return False


def _do_confirm(slot, win):
    """Shared confirmation logic (PROPOSED|HELD_OVER -> CONFIRMED)."""
    aud = db.auditoriums.get(slot.get("auditorium_id"))
    co = db.conversion_orders.get(slot.get("conversion_order_id"))
    if win.get("status") != "OPEN_FOR_BOOKING":
        raise conflict(ERR_WINDOW_NOT_OPEN, "Window is not OPEN_FOR_BOOKING")
    if aud is None or aud.get("status") not in ("CERTIFIED", "OPERATING"):
        raise conflict(ERR_AUDITORIUM_NOT_READY, "Auditorium not ready")
    if co is None or co.get("status") != "APPROVED_FOR_RELEASE":
        raise conflict(ERR_CONVERSION_NOT_APPROVED, "Conversion order not approved for release")
    if _slot_overlaps_existing(slot):
        raise conflict(ERR_SLOT_OVERLAP, "Slot overlaps another confirmed/held-over slot on the auditorium")
    if not _slot_fits_capacity(win, slot):
        # Record the capacity failure for waitlist promotion on later pulls
        slot["_capacity_failed"] = True
        raise conflict(ERR_WINDOW_CAPACITY_EXCEEDED, "Window capacity exceeded")
    slot["status"] = "CONFIRMED"
    touch(slot)
    recompute_window_committed(win)
    touch(win)
    recompute_slot_derived(slot)
    recompute_statements_for_slot(slot)


@bp.post("/v1/screen-slots/<slot_id>/confirm")
def confirm_slot(slot_id):
    require_role("ReleaseScheduler")
    slot = get_slot_or_404(slot_id)
    if slot.get("status") not in ("PROPOSED", "HELD_OVER"):
        raise conflict(ERR_INVALID_STATE, f"Slot in state {slot.get('status')} cannot be confirmed")
    win = db.release_windows.get(slot.get("window_id"))
    if win is None:
        raise not_found(ERR_WINDOW_NOT_FOUND, "Window not found")
    _do_confirm(slot, win)
    return success_object(serialize_screen_slot(slot))


@bp.post("/v1/screen-slots/<slot_id>/reject")
def reject_slot(slot_id):
    require_role("ReleaseScheduler")
    slot = get_slot_or_404(slot_id)
    if slot.get("status") != "PROPOSED":
        raise conflict(ERR_INVALID_STATE, f"Slot in state {slot.get('status')} cannot be rejected")
    slot["status"] = "REJECTED"
    touch(slot)
    return success_object(serialize_screen_slot(slot))


def _promote_waitlist(win):
    """Auto-confirm highest-priority PROPOSED slot that previously failed capacity and now fits."""
    candidates = []
    for slot in db.screen_slots.values():
        if slot.get("window_id") != win["id"]:
            continue
        if slot.get("status") != "PROPOSED":
            continue
        if not slot.get("_capacity_failed"):
            continue
        candidates.append(slot)
    if not candidates:
        return
    candidates.sort(key=lambda s: (PRIORITY_ORDER.get(s.get("priority_tier", "STANDARD"), 1),
                                   s.get("created_at", "")))
    for cand in candidates:
        # eligible per all other confirm gates too
        aud = db.auditoriums.get(cand.get("auditorium_id"))
        co = db.conversion_orders.get(cand.get("conversion_order_id"))
        if win.get("status") != "OPEN_FOR_BOOKING":
            return
        if aud is None or aud.get("status") not in ("CERTIFIED", "OPERATING"):
            continue
        if co is None or co.get("status") != "APPROVED_FOR_RELEASE":
            continue
        if _slot_overlaps_existing(cand):
            continue
        if not _slot_fits_capacity(win, cand):
            continue
        cand["status"] = "CONFIRMED"
        cand.pop("_capacity_failed", None)
        touch(cand)
        recompute_window_committed(win)
        touch(win)
        recompute_slot_derived(cand)
        recompute_statements_for_slot(cand)
        # depth-3 cascade: deliver the conversion order if eligible
        if co.get("status") == "APPROVED_FOR_RELEASE" and co.get("delivered_master_url"):
            co["status"] = "DELIVERED"
            touch(co)
        return


@bp.post("/v1/screen-slots/<slot_id>/pull")
def pull_slot(slot_id):
    require_role("ReleaseScheduler")
    slot = get_slot_or_404(slot_id)
    if slot.get("status") not in ("CONFIRMED", "SUSPENDED", "HELD_OVER"):
        raise conflict(ERR_INVALID_STATE, f"Slot in state {slot.get('status')} cannot be pulled")
    prior = slot["status"]
    if prior == "CONFIRMED":
        if not (db.logical_clock < slot["_slot_start_dt"]):
            raise conflict(ERR_SLOT_ALREADY_STARTED, "Slot has already started")
    slot["status"] = "PULLED"
    touch(slot)
    win = db.release_windows.get(slot.get("window_id"))
    if win is not None:
        recompute_window_committed(win)
        touch(win)
    recompute_statements_for_slot(slot)
    if prior == "CONFIRMED" and win is not None:
        _promote_waitlist(win)
    return success_object(serialize_screen_slot(slot))


@bp.get("/v1/screen-slots/<slot_id>/box-office-reports")
def list_slot_reports(slot_id):
    user_id, role = require_auth()
    if role not in ("BoxOfficeAnalyst", "ReleaseScheduler", "ExhibitorFinanceUser"):
        raise forbidden(f"Role {role} is not permitted to perform this operation")
    slot = get_slot_or_404(slot_id)
    if role == "ExhibitorFinanceUser":
        aud = db.auditoriums.get(slot.get("auditorium_id"))
        if aud is None or aud.get("agreement_id") != user_id:
            raise forbidden("ExhibitorFinanceUser may only access own agreement resources")
    limit, offset = parse_pagination()
    items = [r for r in db.box_office_reports.values() if r.get("screen_slot_id") == slot["id"]]
    status = request.args.get("status")
    if status:
        items = [r for r in items if r.get("status") == status]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return success_list([serialize_box_office_report(r) for r in page], total, limit, offset)

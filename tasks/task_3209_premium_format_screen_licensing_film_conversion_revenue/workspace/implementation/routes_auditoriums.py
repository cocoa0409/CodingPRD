"""Auditorium endpoints."""
from __future__ import annotations

from flask import Blueprint, request

from db import db
from errors import (
    ERR_AUDITORIUM_NOT_FOUND, ERR_AGREEMENT_NOT_FOUND, ERR_INVALID_STATE,
    ERR_MARKET_CAPACITY_EXCEEDED, ERR_UNRESOLVED_CRITICAL_ALERTS, ERR_INVALID_REQUEST,
    bad_request, conflict, not_found,
)
from util import (
    require_role, get_body, req_str, req_int, req_list, req_obj, parse_pagination,
    paginate, success_object, success_list, stamp_new, touch, sort_by_created,
)
from domain import (
    serialize_auditorium, serialize_qa_alert, serialize_screen_slot,
    restore_auditorium, recompute_market_opened_screen_count,
)
from util import iso_format

bp = Blueprint("auditoriums", __name__)

VALID_FORMATS = {"PREMIUM_2D", "PREMIUM_3D", "PREMIUM_70MM"}


def get_auditorium_or_404(auditorium_id):
    a = db.auditoriums.get(auditorium_id)
    if a is None:
        raise not_found(ERR_AUDITORIUM_NOT_FOUND, f"Auditorium {auditorium_id} not found")
    return a


@bp.post("/v1/auditoriums")
def create_auditorium():
    require_role("PlatformContractManager")
    body = get_body()
    agreement_id = req_str(body, "agreement_id")
    auditorium_label = req_str(body, "auditorium_label")
    screen_geometry = req_obj(body, "screen_geometry")
    for f in ("width_m", "height_m", "curvature_deg"):
        v = screen_geometry.get(f)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise bad_request(ERR_INVALID_REQUEST, f"screen_geometry.{f} must be a number")
    seating_capacity = req_int(body, "seating_capacity")
    supported_formats = req_list(body, "supported_formats")
    for f in supported_formats:
        if f not in VALID_FORMATS:
            raise bad_request(ERR_INVALID_REQUEST, f"supported_formats entry {f} invalid")
    sound_calibration_profile = req_obj(body, "sound_calibration_profile")
    # agreement FK existence
    if agreement_id not in db.agreements:
        raise not_found(ERR_AGREEMENT_NOT_FOUND, f"Agreement {agreement_id} not found")

    aud = {
        "agreement_id": agreement_id,
        "auditorium_label": auditorium_label,
        "screen_geometry": screen_geometry,
        "seating_capacity": seating_capacity,
        "supported_formats": supported_formats,
        "sound_calibration_profile": sound_calibration_profile,
        "last_calibration_at": None,
        "_last_calibration_at_dt": None,
        "calibration_overdue": False,
        "current_week_admissions": 0,
        "quality_score_arithmetic": 0.0,
        "quality_score_recency": 0.0,
        "status": "DESIGN",
    }
    stamp_new(aud)
    db.auditoriums[aud["id"]] = aud
    return success_object(serialize_auditorium(aud), 201)


@bp.get("/v1/auditoriums")
def list_auditoriums():
    require_role("NetworkPlanner", "PlatformContractManager", "FieldEngineer", "ReleaseScheduler")
    limit, offset = parse_pagination()
    items = sort_by_created(list(db.auditoriums.values()))
    agreement_id = request.args.get("agreement_id")
    status = request.args.get("status")
    if agreement_id:
        items = [a for a in items if a.get("agreement_id") == agreement_id]
    if status:
        items = [a for a in items if a.get("status") == status]
    page, total = paginate(items, limit, offset)
    return success_list([serialize_auditorium(a) for a in page], total, limit, offset)


@bp.get("/v1/auditoriums/<auditorium_id>")
def get_auditorium(auditorium_id):
    require_role("NetworkPlanner", "PlatformContractManager", "FieldEngineer", "ReleaseScheduler")
    aud = get_auditorium_or_404(auditorium_id)
    return success_object(serialize_auditorium(aud))


@bp.post("/v1/auditoriums/<auditorium_id>/begin-construction")
def begin_construction(auditorium_id):
    require_role("PlatformContractManager")
    aud = get_auditorium_or_404(auditorium_id)
    if aud.get("status") != "DESIGN":
        raise conflict(ERR_INVALID_STATE, f"Auditorium in state {aud.get('status')}")
    agr = db.agreements.get(aud.get("agreement_id"))
    if agr is None or agr.get("status") not in ("SIGNED", "ACTIVE"):
        raise conflict(ERR_INVALID_STATE,
                       "Parent agreement must be SIGNED or ACTIVE to begin construction")
    aud["status"] = "CONSTRUCTION"
    touch(aud)
    return success_object(serialize_auditorium(aud))


@bp.post("/v1/auditoriums/<auditorium_id>/begin-calibration")
def begin_calibration(auditorium_id):
    require_role("FieldEngineer")
    aud = get_auditorium_or_404(auditorium_id)
    if aud.get("status") != "CONSTRUCTION":
        raise conflict(ERR_INVALID_STATE, f"Auditorium in state {aud.get('status')}")
    aud["status"] = "CALIBRATION"
    touch(aud)
    return success_object(serialize_auditorium(aud))


@bp.post("/v1/auditoriums/<auditorium_id>/certify")
def certify(auditorium_id):
    require_role("FieldEngineer")
    aud = get_auditorium_or_404(auditorium_id)
    if aud.get("status") != "CALIBRATION":
        raise conflict(ERR_INVALID_STATE, f"Auditorium in state {aud.get('status')}")
    aud["status"] = "CERTIFIED"
    aud["_last_calibration_at_dt"] = db.logical_clock
    aud["last_calibration_at"] = iso_format(db.logical_clock)
    aud["calibration_overdue"] = False
    touch(aud)
    return success_object(serialize_auditorium(aud))


@bp.post("/v1/auditoriums/<auditorium_id>/open")
def open_auditorium(auditorium_id):
    require_role("PlatformContractManager")
    aud = get_auditorium_or_404(auditorium_id)
    if aud.get("status") != "CERTIFIED":
        raise conflict(ERR_INVALID_STATE, f"Auditorium in state {aud.get('status')}")
    agr = db.agreements.get(aud.get("agreement_id"))
    market = db.markets.get(agr.get("market_id")) if agr else None
    if market is not None:
        operating_count = 0
        for other in db.auditoriums.values():
            if other.get("status") != "OPERATING":
                continue
            oagr = db.agreements.get(other.get("agreement_id"))
            if oagr and oagr.get("market_id") == market["id"]:
                operating_count += 1
        if not (market.get("screen_capacity_cap", 0) > operating_count):
            raise conflict(ERR_MARKET_CAPACITY_EXCEEDED,
                           "Market screen capacity cap reached")
    aud["status"] = "OPERATING"
    touch(aud)
    if market is not None:
        recompute_market_opened_screen_count(market)
        touch(market)
    return success_object(serialize_auditorium(aud))


@bp.post("/v1/auditoriums/<auditorium_id>/return-to-service")
def return_to_service(auditorium_id):
    require_role("FieldEngineer")
    aud = get_auditorium_or_404(auditorium_id)
    if aud.get("status") != "DEGRADED":
        raise conflict(ERR_INVALID_STATE, f"Auditorium in state {aud.get('status')}")
    for alert in db.qa_alerts.values():
        if alert.get("auditorium_id") == aud["id"] and alert.get("severity") == "CRITICAL":
            if alert.get("status") != "RESOLVED":
                raise conflict(ERR_UNRESOLVED_CRITICAL_ALERTS,
                               "Unresolved CRITICAL alerts block return-to-service")
    aud["status"] = "OPERATING"
    touch(aud)
    restore_auditorium(aud)
    return success_object(serialize_auditorium(aud))


@bp.post("/v1/auditoriums/<auditorium_id>/decommission")
def decommission(auditorium_id):
    require_role("PlatformContractManager")
    aud = get_auditorium_or_404(auditorium_id)
    if aud.get("status") not in ("OPERATING", "DEGRADED"):
        raise conflict(ERR_INVALID_STATE, f"Auditorium in state {aud.get('status')}")
    was_operating = aud.get("status") == "OPERATING"
    aud["status"] = "DECOMMISSIONED"
    touch(aud)
    if was_operating:
        agr = db.agreements.get(aud.get("agreement_id"))
        if agr:
            market = db.markets.get(agr.get("market_id"))
            if market is not None:
                market["opened_screen_count"] = max(0, market.get("opened_screen_count", 0) - 1)
                touch(market)
    # cascade slots
    for slot in db.screen_slots.values():
        if slot.get("auditorium_id") != aud["id"]:
            continue
        if slot.get("status") == "PROPOSED":
            slot["status"] = "REJECTED"
            touch(slot)
        elif slot.get("status") == "CONFIRMED" and was_operating:
            slot["status"] = "PULLED"
            touch(slot)
            win = db.release_windows.get(slot.get("window_id"))
            if win is not None:
                from domain import recompute_window_committed, recompute_statements_for_slot
                recompute_window_committed(win)
                touch(win)
                recompute_statements_for_slot(slot)
        elif slot.get("status") == "SUSPENDED" and not was_operating:
            slot["status"] = "PULLED"
            touch(slot)
            from domain import recompute_statements_for_slot
            recompute_statements_for_slot(slot)
    return success_object(serialize_auditorium(aud))


@bp.get("/v1/auditoriums/<auditorium_id>/qa-alerts")
def list_auditorium_qa_alerts(auditorium_id):
    require_role("FieldEngineer", "NetworkPlanner", "PlatformContractManager")
    aud = get_auditorium_or_404(auditorium_id)
    limit, offset = parse_pagination()
    items = [a for a in db.qa_alerts.values() if a.get("auditorium_id") == aud["id"]]
    status = request.args.get("status")
    if status:
        items = [a for a in items if a.get("status") == status]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return success_list([serialize_qa_alert(a) for a in page], total, limit, offset)


@bp.get("/v1/auditoriums/<auditorium_id>/screen-slots")
def list_auditorium_slots(auditorium_id):
    require_role("ReleaseScheduler", "BoxOfficeAnalyst", "PlatformContractManager")
    aud = get_auditorium_or_404(auditorium_id)
    limit, offset = parse_pagination()
    items = [s for s in db.screen_slots.values() if s.get("auditorium_id") == aud["id"]]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return success_list([serialize_screen_slot(s) for s in page], total, limit, offset)

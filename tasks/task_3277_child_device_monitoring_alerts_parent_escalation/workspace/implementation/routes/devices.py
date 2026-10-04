"""Device routes: get, unpair, screen-time windows, bypass events, access grants."""
from flask import Blueprint, request
from datetime import timedelta
from db import store, clock, parse_iso, fmt_iso
from errors import fail
from response import success_object, success_list, parse_pagination
from middleware import authenticate, require_role, require_parent_scope, family_id_of_device
import services as svc

bp = Blueprint("devices", __name__)

WEEKDAYS = {"MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"}
WINDOW_KINDS = {"BLOCKED", "ALLOWED"}
BYPASS_KINDS = {"VPN", "SECONDARY_ACCOUNT", "TIMEZONE_SHIFT", "UNINSTALL_ATTEMPT"}
GRANT_PAD = timedelta(minutes=5)


def _get_device(device_id):
    d = store.devices.get(device_id)
    if not d:
        fail("ERR_NOT_FOUND", "Device not found")
    return d


@bp.get("/api/devices/<device_id>")
def get_device(device_id):
    role, uid = authenticate()
    require_role(role, {"Parent", "PlatformAdmin"})
    d = _get_device(device_id)
    if role == "Parent":
        require_parent_scope(uid, family_id_of_device(d))
    return success_object(svc.ser_device(d))


@bp.post("/api/devices/<device_id>/unpair")
def unpair_device(device_id):
    role, uid = authenticate()
    require_role(role, {"Parent"})
    d = _get_device(device_id)
    require_parent_scope(uid, family_id_of_device(d))
    if d["pairing_status"] == "UNPAIRED":
        fail("ERR_ALREADY_TERMINAL", "Device is already UNPAIRED")
    with store.lock:
        d["pairing_status"] = "UNPAIRED"
        svc.touch(d)
        family = svc.family_of_device(d["id"])
        if family:
            svc.recompute_device_count(family)
    return success_object(svc.ser_device(d))


def _validate_window_bounds(start_minute, end_minute):
    if not isinstance(start_minute, int) or isinstance(start_minute, bool):
        fail("ERR_INVALID_REQUEST", "start_minute must be an integer")
    if not isinstance(end_minute, int) or isinstance(end_minute, bool):
        fail("ERR_INVALID_REQUEST", "end_minute must be an integer")
    if start_minute < 0 or start_minute > 1439:
        fail("ERR_INVALID_REQUEST", "start_minute must be in 0..1439")
    if end_minute < 1 or end_minute > 1440:
        fail("ERR_INVALID_REQUEST", "end_minute must be in 1..1440")
    if end_minute <= start_minute:
        fail("ERR_INVALID_REQUEST", "end_minute must be greater than start_minute")


def _blocked_overlap(device_id, weekday, start_minute, end_minute, exclude_id=None):
    """Half-open interval intersection against ACTIVE BLOCKED windows on same device+weekday."""
    for w in store.screen_time_windows.values():
        if w["id"] == exclude_id:
            continue
        if (w.get("device_id") == device_id and w.get("weekday") == weekday
                and w.get("window_kind") == "BLOCKED"
                and w.get("window_status") == "ACTIVE"):
            if start_minute < w["end_minute"] and w["start_minute"] < end_minute:
                return True
    return False


@bp.post("/api/devices/<device_id>/screen-time-windows")
def create_window(device_id):
    role, uid = authenticate()
    require_role(role, {"Parent"})
    d = _get_device(device_id)
    require_parent_scope(uid, family_id_of_device(d))
    if d["pairing_status"] != "PAIRED":
        fail("ERR_DEVICE_NOT_PAIRED", "Device is not paired")
    body = request.get_json(silent=True) or {}
    weekday = body.get("weekday")
    if weekday not in WEEKDAYS:
        fail("ERR_INVALID_REQUEST", "invalid weekday")
    window_kind = body.get("window_kind")
    if window_kind not in WINDOW_KINDS:
        fail("ERR_INVALID_REQUEST", "invalid window_kind")
    _validate_window_bounds(body.get("start_minute"), body.get("end_minute"))
    start_minute = body["start_minute"]
    end_minute = body["end_minute"]
    if window_kind == "BLOCKED" and _blocked_overlap(d["id"], weekday, start_minute, end_minute):
        fail("ERR_WINDOW_OVERLAP", "BLOCKED window overlaps an existing ACTIVE BLOCKED window")
    with store.lock:
        w = svc.new_entity()
        w.update({
            "device_id": d["id"],
            "weekday": weekday,
            "start_minute": start_minute,
            "end_minute": end_minute,
            "window_kind": window_kind,
            "window_status": "ACTIVE",
        })
        store.screen_time_windows[w["id"]] = w
    return success_object(svc.ser_window(w), status=201)


@bp.get("/api/devices/<device_id>/screen-time-windows")
def list_windows(device_id):
    role, uid = authenticate()
    require_role(role, {"Parent"})
    d = _get_device(device_id)
    require_parent_scope(uid, family_id_of_device(d))
    limit, offset = parse_pagination(request.args)
    items = [w for w in store.screen_time_windows.values()
             if w.get("device_id") == d["id"]]
    page, total = svc.paginate(items, limit, offset)
    return success_list([svc.ser_window(w) for w in page], limit, offset, total)


@bp.post("/api/screen-time-windows/<window_id>/state")
def window_state(window_id):
    role, uid = authenticate()
    require_role(role, {"Parent"})
    w = store.screen_time_windows.get(window_id)
    if not w:
        fail("ERR_NOT_FOUND", "Window not found")
    require_parent_scope(uid, family_id_of_device(store.devices.get(w["device_id"])))
    body = request.get_json(silent=True) or {}
    to_status = body.get("to_status")
    if to_status not in ("ACTIVE", "DISABLED"):
        fail("ERR_INVALID_REQUEST", "to_status must be ACTIVE or DISABLED")
    current = w["window_status"]
    if current == to_status:
        fail("ERR_INVALID_STATE", "Window already in state %s" % to_status)
    if to_status == "ACTIVE":
        device = store.devices.get(w["device_id"])
        if not device or device["pairing_status"] != "PAIRED":
            fail("ERR_DEVICE_NOT_PAIRED", "Device is not paired")
        if (w["window_kind"] == "BLOCKED"
                and _blocked_overlap(w["device_id"], w["weekday"],
                                     w["start_minute"], w["end_minute"],
                                     exclude_id=w["id"])):
            fail("ERR_WINDOW_OVERLAP", "Re-enabling would overlap an ACTIVE BLOCKED window")
    with store.lock:
        w["window_status"] = to_status
        svc.touch(w)
    return success_object(svc.ser_window(w))


@bp.post("/api/devices/<device_id>/bypass-events")
def create_bypass_event(device_id):
    role, uid = authenticate()
    require_role(role, {"DeviceAgent"})
    d = _get_device(device_id)
    if uid != d["id"]:
        fail("ERR_FORBIDDEN_ROLE", "DeviceAgent may only report for its own device")
    if d["pairing_status"] != "PAIRED":
        fail("ERR_DEVICE_NOT_PAIRED", "Device is not paired")
    body = request.get_json(silent=True) or {}
    bypass_kind = body.get("bypass_kind")
    if bypass_kind not in BYPASS_KINDS:
        fail("ERR_INVALID_REQUEST", "invalid bypass_kind")
    detected = parse_iso(body.get("detected_at"))
    if detected is None:
        fail("ERR_INVALID_REQUEST", "detected_at must be an ISO8601 timestamp")
    if detected > clock.now():
        fail("ERR_INVALID_REQUEST", "detected_at must not lie in the future")
    with store.lock:
        e = svc.new_entity()
        e.update({
            "device_id": d["id"],
            "bypass_kind": bypass_kind,
            "detected_at": fmt_iso(detected),
            "_detected_dt": detected,
            "counted_in_strikes": False,
        })
        store.bypass_events[e["id"]] = e
        svc.recompute_device_posture(d)
    return success_object(svc.ser_bypass_event(e), status=201)


@bp.get("/api/devices/<device_id>/bypass-events")
def list_bypass_events(device_id):
    role, uid = authenticate()
    require_role(role, {"Parent", "PlatformAdmin"})
    d = _get_device(device_id)
    if role == "Parent":
        require_parent_scope(uid, family_id_of_device(d))
    limit, offset = parse_pagination(request.args)
    items = [e for e in store.bypass_events.values()
             if e.get("device_id") == d["id"]]
    page, total = svc.paginate(items, limit, offset)
    return success_list([svc.ser_bypass_event(e) for e in page], limit, offset, total)


@bp.post("/api/devices/<device_id>/access-grants")
def create_grant(device_id):
    role, uid = authenticate()
    require_role(role, {"Parent"})
    d = _get_device(device_id)
    require_parent_scope(uid, family_id_of_device(d))
    if d["pairing_status"] != "PAIRED":
        fail("ERR_DEVICE_NOT_PAIRED", "Device is not paired")
    if d["device_posture"] == "LOCKDOWN":
        fail("ERR_DEVICE_LOCKED_DOWN", "Device is in LOCKDOWN")
    body = request.get_json(silent=True) or {}
    start = parse_iso(body.get("start_at"))
    end = parse_iso(body.get("end_at"))
    if start is None or end is None:
        fail("ERR_INVALID_REQUEST", "start_at and end_at must be ISO8601 timestamps")
    if start >= end:
        fail("ERR_INVALID_REQUEST", "start_at must be strictly before end_at")
    reason = body.get("reason", "")
    if not isinstance(reason, str):
        fail("ERR_INVALID_REQUEST", "reason must be a string")
    # Padded closed-interval conflict against SCHEDULED/ACTIVE grants
    for g in store.access_grants.values():
        if g.get("device_id") != d["id"]:
            continue
        if g.get("grant_status") not in ("SCHEDULED", "ACTIVE"):
            continue
        gs = parse_iso(g["start_at"]) - GRANT_PAD
        ge = parse_iso(g["end_at"]) + GRANT_PAD
        if start <= ge and gs <= end:
            fail("ERR_GRANT_CONFLICT", "Grant conflicts with an existing grant")
    with store.lock:
        g = svc.new_entity()
        g.update({
            "device_id": d["id"],
            "start_at": fmt_iso(start),
            "end_at": fmt_iso(end),
            "reason": reason,
            "grant_status": "SCHEDULED",
        })
        store.access_grants[g["id"]] = g
        svc.recompute_grant(g)
    return success_object(svc.ser_grant(g), status=201)


@bp.get("/api/devices/<device_id>/access-grants")
def list_grants(device_id):
    role, uid = authenticate()
    require_role(role, {"Parent"})
    d = _get_device(device_id)
    require_parent_scope(uid, family_id_of_device(d))
    limit, offset = parse_pagination(request.args)
    items = [g for g in store.access_grants.values()
             if g.get("device_id") == d["id"]]
    page, total = svc.paginate(items, limit, offset)
    return success_list([svc.ser_grant(g) for g in page], limit, offset, total)

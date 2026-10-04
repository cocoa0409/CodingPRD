"""NetworkSlice and SliceBinding endpoints."""

from flask import Blueprint, request

from auth import require_roles
from db import DB
from errors import err, ok_list, ok_object
from helpers import (apply_filters, get_body, new_resource, paged, req_enum,
                     req_int, req_str, stamp, touch)
from validate import get_device, get_site, get_site_mutable, get_slice

bp = Blueprint("slices", __name__)

SLICE_READ = ("NetworkArchitect", "RFEngineer", "FieldTechnician")
BINDING_READ = ("NetworkArchitect", "FieldTechnician")
SLICE_TYPES = ("EMBB", "URLLC", "MMTC")


@bp.post("/sites/<sid>/slices")
def create_slice(sid):
    require_roles("NetworkArchitect")
    get_site_mutable(sid)
    body = get_body()
    name = req_str(body, "slice_name")
    stype = req_enum(body, "slice_type", SLICE_TYPES)
    bw = req_int(body, "guaranteed_bandwidth_mbps", minimum=0)
    latency = req_int(body, "max_latency_ms", minimum=0)
    max_dev = req_int(body, "max_devices", minimum=0)
    if any(s["site_id"] == sid and s["slice_name"] == name for s in DB.slices.values()):
        raise err("ERR_DUPLICATE_IDENTIFIER", "slice_name already used within this Site")
    s = new_resource()
    s.update({
        "site_id": sid,
        "slice_name": name,
        "slice_type": stype,
        "guaranteed_bandwidth_mbps": bw,
        "max_latency_ms": latency,
        "max_devices": max_dev,
        "bound_device_count": 0,
        "status": "DEFINED",
    })
    DB.slices[s["id"]] = s
    return ok_object(s, 201)


@bp.get("/sites/<sid>/slices")
def list_slices_for_site(sid):
    require_roles(*SLICE_READ)
    get_site(sid)
    items = [s for s in DB.slices.values() if s["site_id"] == sid]
    items = apply_filters(items, [("status", "status"), ("slice_type", "slice_type")])
    window, total, limit, offset = paged(items)
    return ok_list(window, total, limit, offset)


@bp.get("/sites/<sid>/slices/<slid>")
def get_one_slice(sid, slid):
    require_roles(*SLICE_READ)
    get_site(sid)
    return ok_object(get_slice(slid, sid))


@bp.post("/sites/<sid>/slices/<slid>/activate")
def activate_slice(sid, slid):
    require_roles("NetworkArchitect")
    site = get_site_mutable(sid)
    s = get_slice(slid, sid)
    if s["status"] == "RETIRED":
        raise err("ERR_ALREADY_TERMINAL", "Slice is retired")
    if s["status"] not in ("DEFINED", "SUSPENDED"):
        raise err("ERR_INVALID_STATE", "Slice must be DEFINED or SUSPENDED to activate")
    if site["status"] != "OPERATIONAL":
        raise err("ERR_INVALID_STATE", "Site must be OPERATIONAL to activate a slice")
    if s["slice_type"] == "URLLC":
        design = next((d for d in DB.designs.values()
                       if d["site_id"] == sid and d["status"] == "APPROVED"), None)
        placement = design["edge_compute_placement"] if design is not None else "NONE"
        if placement not in ("ON_PREMISE", "NEAR_EDGE"):
            raise err("ERR_URLLC_REQUIRES_EDGE",
                      "URLLC slices require edge_compute_placement ON_PREMISE or NEAR_EDGE")
    projected = sum(o["guaranteed_bandwidth_mbps"] for o in DB.slices.values()
                    if o["site_id"] == sid and o["status"] == "ACTIVATED")
    projected += s["guaranteed_bandwidth_mbps"]
    if projected > site["target_capacity_mbps"]:
        raise err("ERR_SLICE_BANDWIDTH_EXCEEDED",
                  "Activated slice bandwidth would exceed the site's target capacity")
    s["status"] = "ACTIVATED"
    touch(s)
    return ok_object(s)


@bp.post("/sites/<sid>/slices/<slid>/suspend")
def suspend_slice(sid, slid):
    require_roles("NetworkArchitect")
    get_site_mutable(sid)
    s = get_slice(slid, sid)
    if s["status"] == "RETIRED":
        raise err("ERR_ALREADY_TERMINAL", "Slice is retired")
    if s["status"] != "ACTIVATED":
        raise err("ERR_INVALID_STATE", "Slice must be ACTIVATED to suspend")
    now = stamp()
    for b in DB.bindings.values():
        if b["slice_id"] == slid and b.get("unbound_at_utc") is None:
            b["unbound_at_utc"] = now
    s["bound_device_count"] = 0
    s["status"] = "SUSPENDED"
    touch(s)
    return ok_object(s)


@bp.post("/sites/<sid>/slices/<slid>/retire")
def retire_slice(sid, slid):
    require_roles("NetworkArchitect")
    get_site_mutable(sid)
    s = get_slice(slid, sid)
    if s["status"] == "RETIRED":
        raise err("ERR_ALREADY_TERMINAL", "Slice is already retired")
    if s["status"] not in ("DEFINED", "ACTIVATED", "SUSPENDED"):
        raise err("ERR_INVALID_STATE", "Slice cannot be retired from its current state")
    if s.get("bound_device_count", 0) != 0:
        raise err("ERR_INVALID_STATE", "Slice must have zero bound devices to retire")
    s["status"] = "RETIRED"
    touch(s)
    return ok_object(s)


@bp.post("/sites/<sid>/slices/<slid>/bind-device")
def bind_device(sid, slid):
    require_roles("FieldTechnician")
    get_site_mutable(sid)
    s = get_slice(slid, sid)
    body = get_body()
    device_id = req_str(body, "device_id")
    d = DB.devices.get(device_id)
    if d is None or d["site_id"] != sid:
        raise err("ERR_REFERENCE_NOT_FOUND", "device_id does not reference a device on this Site")
    if s["status"] != "ACTIVATED":
        raise err("ERR_INVALID_STATE", "Slice must be ACTIVATED to bind devices")
    if d["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Device must be ACTIVE to bind to a slice")
    existing = next((b for b in DB.bindings.values()
                     if b["slice_id"] == slid and b["device_id"] == device_id
                     and b.get("unbound_at_utc") is None), None)
    if existing is not None:
        return ok_object(existing, 201)
    if s.get("bound_device_count", 0) >= s["max_devices"]:
        raise err("ERR_SLICE_DEVICE_CAP_EXCEEDED", "Slice has reached its device cap")
    b = new_resource(common=False)
    b.update({
        "slice_id": slid,
        "device_id": device_id,
        "bound_at_utc": stamp(),
        "unbound_at_utc": None,
    })
    DB.bindings[b["id"]] = b
    s["bound_device_count"] = s.get("bound_device_count", 0) + 1
    touch(s)
    return ok_object(b, 201)


@bp.post("/sites/<sid>/slices/<slid>/unbind-device")
def unbind_device(sid, slid):
    require_roles("FieldTechnician")
    get_site_mutable(sid)
    s = get_slice(slid, sid)
    body = get_body()
    device_id = req_str(body, "device_id")
    d = DB.devices.get(device_id)
    if d is None:
        raise err("ERR_REFERENCE_NOT_FOUND", "device_id does not reference an existing device")
    b = next((x for x in DB.bindings.values()
              if x["slice_id"] == slid and x["device_id"] == device_id
              and x.get("unbound_at_utc") is None), None)
    if b is None:
        raise err("ERR_INVALID_STATE", "No active binding exists for this device on this slice")
    b["unbound_at_utc"] = stamp()
    if s.get("bound_device_count", 0) > 0:
        s["bound_device_count"] -= 1
        touch(s)
    return ok_object(b)


@bp.get("/sites/<sid>/slices/<slid>/bindings")
def list_bindings_for_slice(sid, slid):
    require_roles(*BINDING_READ)
    get_site(sid)
    get_slice(slid, sid)
    items = [b for b in DB.bindings.values() if b["slice_id"] == slid]
    active_only = request.args.get("active_only")
    if active_only is not None and active_only.lower() in ("true", "1", "yes"):
        items = [b for b in items if b.get("unbound_at_utc") is None]
    items = apply_filters(items, [("device_id", "device_id")])
    window, total, limit, offset = paged(items)
    return ok_list(window, total, limit, offset)


@bp.get("/slices/<slid>")
def get_slice_flat(slid):
    require_roles(*SLICE_READ)
    return ok_object(get_slice(slid))


@bp.get("/slices")
def list_slices_flat():
    require_roles(*SLICE_READ)
    items = list(DB.slices.values())
    items = apply_filters(items, [("site_id", "site_id"), ("status", "status"), ("slice_type", "slice_type")])
    window, total, limit, offset = paged(items)
    return ok_list(window, total, limit, offset)


@bp.get("/slice-bindings/<bid>")
def get_binding_flat(bid):
    require_roles(*BINDING_READ)
    b = DB.bindings.get(bid)
    if b is None:
        raise err("ERR_NOT_FOUND", "SliceBinding not found")
    return ok_object(b)


@bp.get("/slice-bindings")
def list_bindings_flat():
    require_roles(*BINDING_READ)
    items = list(DB.bindings.values())
    items = apply_filters(items, [("slice_id", "slice_id"), ("device_id", "device_id")])
    active_only = request.args.get("active_only")
    if active_only is not None and active_only.lower() in ("true", "1", "yes"):
        items = [b for b in items if b.get("unbound_at_utc") is None]
    window, total, limit, offset = paged(items)
    return ok_list(window, total, limit, offset)

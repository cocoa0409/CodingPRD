"""TV manufacturers, device models, lab bookings, OS updates routes."""

from datetime import timedelta

from flask import Blueprint, request

import errors as E
from db import store
from middleware import (
    get_json_body,
    parse_iso8601,
    parse_pagination,
    require_bool,
    require_datetime,
    require_enum,
    require_nonnegative_int,
    require_roles,
    require_str,
    to_iso_z,
)
from response import created, list_response, ok
from services.common import (
    device_model_view,
    lab_booking_view,
    manufacturer_view,
    os_update_view,
    LAB_BUFFER_HOURS,
    LAB_CAPACITY,
)

bp = Blueprint("devices", __name__)

RECOVERY_POLICIES = {"STRAIGHT_LINE", "MONETIZATION"}


def get_manufacturer_or_404(mid):
    m = store.manufacturers.get(mid)
    if m is None:
        E.not_found("TvManufacturer not found")
    return m


def get_model_or_404(mid):
    m = store.device_models.get(mid)
    if m is None:
        E.not_found("DeviceModel not found")
    return m


def get_os_update_or_404(uid):
    u = store.os_updates.get(uid)
    if u is None:
        E.not_found("OsUpdate not found")
    return u


@bp.post("/manufacturers")
def create_manufacturer():
    require_roles("PlatformAdmin")
    body = get_json_body()
    legal_name = require_str(body, "legal_name")
    royalty = require_nonnegative_int(body, "royalty_per_device_cents")
    m = store.new_entity()
    m.update({
        "legal_name": legal_name,
        "royalty_per_device_cents": royalty,
        "license_status": "LICENSED",
    })
    store.manufacturers[m["id"]] = m
    return created(manufacturer_view(m))


@bp.get("/manufacturers/<mid>")
def get_manufacturer(mid):
    require_roles("PlatformAdmin", "AdOps", "TvManufacturer")
    return ok(manufacturer_view(get_manufacturer_or_404(mid)))


@bp.post("/manufacturers/<mid>/suspend")
def suspend_manufacturer(mid):
    require_roles("PlatformAdmin")
    m = get_manufacturer_or_404(mid)
    body = get_json_body()
    if "reason" in body and body["reason"] is not None and not isinstance(body["reason"], str):
        E.invalid_request("reason must be a string")
    if m["license_status"] != "LICENSED":
        E.invalid_state("Manufacturer license must be LICENSED to suspend")
    m["license_status"] = "SUSPENDED"
    store.touch(m)
    return ok(manufacturer_view(m))


@bp.post("/manufacturers/<mid>/reinstate")
def reinstate_manufacturer(mid):
    require_roles("PlatformAdmin")
    m = get_manufacturer_or_404(mid)
    if m["license_status"] != "SUSPENDED":
        E.invalid_state("Manufacturer license must be SUSPENDED to reinstate")
    for dm in store.device_models.values():
        if dm["manufacturer_id"] == m["id"] and dm["update_compliance"] == "OVERDUE":
            E.raise_err(E.ERR_UPDATE_OVERDUE,
                        "Manufacturer has OVERDUE device models")
    m["license_status"] = "LICENSED"
    store.touch(m)
    return ok(manufacturer_view(m))


@bp.get("/manufacturers/<mid>/device-models")
def manufacturer_models(mid):
    require_roles("PlatformAdmin", "AdOps", "TvManufacturer")
    get_manufacturer_or_404(mid)
    limit, offset = parse_pagination()
    items = sorted(
        [d for d in store.device_models.values() if d["manufacturer_id"] == mid],
        key=lambda x: x["_seq"],
    )
    return list_response([device_model_view(d) for d in items], limit, offset, len(items))


@bp.get("/manufacturers/<mid>/lab-bookings")
def manufacturer_lab_bookings(mid):
    require_roles("PlatformAdmin", "AdOps", "TvManufacturer")
    get_manufacturer_or_404(mid)
    limit, offset = parse_pagination()
    items = sorted(
        [b for b in store.lab_bookings.values() if b["manufacturer_id"] == mid],
        key=lambda x: x["_seq"],
    )
    return list_response([lab_booking_view(b) for b in items], limit, offset, len(items))


# ---- device models ----

@bp.post("/device-models")
def create_device_model():
    user_id, role = require_roles("TvManufacturer")
    body = get_json_body()
    manufacturer_id = require_str(body, "manufacturer_id")
    model_code = require_str(body, "model_code")
    recovery = require_enum(body, "recovery_policy", RECOVERY_POLICIES)
    if manufacturer_id != user_id:
        E.forbidden("TvManufacturer caller may only submit models for itself")
    if manufacturer_id not in store.manufacturers:
        E.not_found("TvManufacturer not found")
    for dm in store.device_models.values():
        if dm["manufacturer_id"] == manufacturer_id and dm["model_code"] == model_code:
            E.raise_err(E.ERR_DUPLICATE_MODEL_CODE,
                        "model_code already exists for this manufacturer")
    dm = store.new_entity()
    dm.update({
        "manufacturer_id": manufacturer_id,
        "model_code": model_code,
        "recovery_policy": recovery,
        "cert_status": "SUBMITTED",
        "update_compliance": "COMPLIANT",
    })
    store.device_models[dm["id"]] = dm
    return created(device_model_view(dm))


@bp.get("/device-models/<mid>")
def get_device_model(mid):
    require_roles("PlatformAdmin", "AdOps", "TvManufacturer")
    return ok(device_model_view(get_model_or_404(mid)))


@bp.post("/device-models/<mid>/lab-bookings")
def create_lab_booking(mid):
    user_id, role = require_roles("TvManufacturer")
    dm = get_model_or_404(mid)
    if dm["manufacturer_id"] != user_id:
        E.forbidden("TvManufacturer caller does not own this model")
    body = get_json_body()
    bench_code = require_str(body, "bench_code")
    ws = require_datetime(body, "window_start")
    we = require_datetime(body, "window_end")
    if we < ws:
        E.invalid_request("window_end must be >= window_start (closed interval)")
    mfr = store.manufacturers.get(dm["manufacturer_id"])
    if mfr is None:
        E.not_found("TvManufacturer not found")
    if mfr["license_status"] != "LICENSED":
        E.raise_err(E.ERR_MANUFACTURER_NOT_LICENSED,
                    "Manufacturer license must be LICENSED")
    if dm["cert_status"] != "SUBMITTED":
        E.invalid_state("Device model must be SUBMITTED to book a lab bench")
    # Overlap before capacity (pinned order in scaffold calculation).
    buf = timedelta(hours=LAB_BUFFER_HOURS)
    new_lo = ws - buf
    new_hi = we + buf
    for b in store.lab_bookings.values():
        if b["bench_code"] != bench_code or b["status"] != "BOOKED":
            continue
        es = parse_iso8601(b["window_start"], "window_start") - buf
        ee = parse_iso8601(b["window_end"], "window_end") + buf
        # closed intervals: intersect iff new_lo <= ee and new_hi >= es
        if new_lo <= ee and new_hi >= es:
            E.raise_err(E.ERR_BENCH_OVERLAP,
                        "Lab window (buffered) overlaps a BOOKED booking on this bench_code")
    in_lab = sum(
        1 for d in store.device_models.values()
        if d["manufacturer_id"] == dm["manufacturer_id"] and d["cert_status"] == "LAB_TESTING"
    )
    if in_lab >= LAB_CAPACITY:
        E.raise_err(E.ERR_LAB_CAPACITY_EXCEEDED,
                    "Manufacturer already has 3 device models in LAB_TESTING")
    lb = store.new_entity()
    lb.update({
        "manufacturer_id": dm["manufacturer_id"],
        "device_model_id": dm["id"],
        "bench_code": bench_code,
        "window_start": to_iso_z(ws),
        "window_end": to_iso_z(we),
        "status": "BOOKED",
    })
    store.lab_bookings[lb["id"]] = lb
    dm["cert_status"] = "LAB_TESTING"
    store.touch(dm)
    return created(lab_booking_view(lb))


@bp.get("/device-models/<mid>/lab-bookings")
def model_lab_bookings(mid):
    require_roles("PlatformAdmin", "AdOps", "TvManufacturer")
    get_model_or_404(mid)
    limit, offset = parse_pagination()
    items = sorted(
        [b for b in store.lab_bookings.values() if b["device_model_id"] == mid],
        key=lambda x: x["_seq"],
    )
    return list_response([lab_booking_view(b) for b in items], limit, offset, len(items))


@bp.post("/device-models/<mid>/certify")
def certify_model(mid):
    require_roles("PlatformAdmin")
    dm = get_model_or_404(mid)
    if dm["cert_status"] != "LAB_TESTING":
        E.invalid_state("Device model must be in LAB_TESTING to certify")
    finished = None
    for b in store.lab_bookings.values():
        if b["device_model_id"] == dm["id"] and b["status"] == "BOOKED":
            we = parse_iso8601(b["window_end"], "window_end")
            if we < store.clock:
                finished = b
                break
    if finished is None:
        E.invalid_state("No finished BOOKED lab booking exists for this model")
    dm["cert_status"] = "CERTIFIED"
    store.touch(dm)
    finished["status"] = "COMPLETED"
    store.touch(finished)
    return ok(device_model_view(dm))


@bp.post("/device-models/<mid>/reject")
def reject_model(mid):
    require_roles("PlatformAdmin")
    dm = get_model_or_404(mid)
    body = get_json_body()
    if "reason" in body and body["reason"] is not None and not isinstance(body["reason"], str):
        E.invalid_request("reason must be a string")
    if dm["cert_status"] != "LAB_TESTING":
        E.invalid_state("Device model must be in LAB_TESTING to reject")
    dm["cert_status"] = "REJECTED"
    store.touch(dm)
    for b in store.lab_bookings.values():
        if b["device_model_id"] == dm["id"] and b["status"] == "BOOKED":
            b["status"] = "CANCELLED"
            store.touch(b)
    return ok(device_model_view(dm))


@bp.post("/device-models/<mid>/resubmit")
def resubmit_model(mid):
    user_id, role = require_roles("TvManufacturer")
    dm = get_model_or_404(mid)
    if dm["manufacturer_id"] != user_id:
        E.forbidden("TvManufacturer caller does not own this model")
    if dm["cert_status"] != "REJECTED":
        E.invalid_state("Device model must be REJECTED to resubmit")
    mfr = store.manufacturers.get(dm["manufacturer_id"])
    if mfr is None:
        E.not_found("TvManufacturer not found")
    if mfr["license_status"] != "LICENSED":
        E.raise_err(E.ERR_MANUFACTURER_NOT_LICENSED,
                    "Manufacturer license must be LICENSED")
    dm["cert_status"] = "SUBMITTED"
    store.touch(dm)
    return ok(device_model_view(dm))


@bp.post("/device-models/<mid>/decertify")
def decertify_model(mid):
    require_roles("PlatformAdmin")
    dm = get_model_or_404(mid)
    body = get_json_body()
    if "reason" in body and body["reason"] is not None and not isinstance(body["reason"], str):
        E.invalid_request("reason must be a string")
    if dm["cert_status"] != "CERTIFIED":
        E.invalid_state("Device model must be CERTIFIED to decertify")
    dm["cert_status"] = "DECERTIFIED"
    store.touch(dm)
    return ok(device_model_view(dm))


@bp.post("/device-models/<mid>/refresh-compliance")
def refresh_compliance(mid):
    require_roles("PlatformAdmin")
    dm = get_model_or_404(mid)
    now = store.clock
    week = timedelta(days=7)
    has_grace = False
    has_overdue = False
    for u in store.os_updates.values():
        if not u["mandatory"] or u["status"] != "ROLLING":
            continue
        deadline = parse_iso8601(u["compliance_deadline"], "compliance_deadline")
        lacking = any(
            unit["device_model_id"] == dm["id"]
            and unit["status"] == "ACTIVATED"
            and unit["os_version_tag"] != u["version_tag"]
            for unit in store.device_units.values()
        )
        if not lacking:
            continue
        if now > deadline:
            has_overdue = True
        elif (deadline - week) < now <= deadline:
            has_grace = True
    new_state = dm["update_compliance"]
    if has_overdue:
        new_state = "OVERDUE"
    elif has_grace:
        new_state = "GRACE"
    else:
        new_state = "COMPLIANT"
    became_overdue = new_state == "OVERDUE" and dm["update_compliance"] != "OVERDUE"
    if new_state != dm["update_compliance"]:
        dm["update_compliance"] = new_state
        store.touch(dm)
    if became_overdue:
        mfr = store.manufacturers.get(dm["manufacturer_id"])
        if mfr is not None and mfr["license_status"] == "LICENSED":
            mfr["license_status"] = "SUSPENDED"
            store.touch(mfr)
    return ok(device_model_view(dm))


@bp.get("/device-models/<mid>/device-units")
def model_device_units(mid):
    require_roles("PlatformAdmin", "AdOps", "TvManufacturer")
    get_model_or_404(mid)
    limit, offset = parse_pagination()
    items = sorted(
        [u for u in store.device_units.values() if u["device_model_id"] == mid],
        key=lambda x: x["_seq"],
    )
    from services.common import device_unit_view
    return list_response([device_unit_view(u) for u in items], limit, offset, len(items))


# ---- OS updates ----

@bp.post("/os-updates")
def create_os_update():
    require_roles("PlatformAdmin")
    body = get_json_body()
    version_tag = require_str(body, "version_tag")
    mandatory = require_bool(body, "mandatory")
    rs = require_datetime(body, "rollout_start")
    cd = require_datetime(body, "compliance_deadline")
    for u in store.os_updates.values():
        if u["version_tag"] == version_tag:
            E.raise_err(E.ERR_DUPLICATE_VERSION_TAG, "os update version_tag already exists")
    u = store.new_entity()
    u.update({
        "version_tag": version_tag,
        "mandatory": mandatory,
        "rollout_start": to_iso_z(rs),
        "compliance_deadline": to_iso_z(cd),
        "status": "ROLLING",
    })
    store.os_updates[u["id"]] = u
    return created(os_update_view(u))


@bp.get("/os-updates")
def list_os_updates():
    require_roles("PlatformAdmin", "AdOps", "TvManufacturer")
    limit, offset = parse_pagination()
    mandatory = request.args.get("mandatory")
    items = sorted(store.os_updates.values(), key=lambda x: x["_seq"])
    if mandatory is not None:
        if mandatory.lower() == "true":
            items = [u for u in items if u["mandatory"] is True]
        elif mandatory.lower() == "false":
            items = [u for u in items if u["mandatory"] is False]
    return list_response([os_update_view(u) for u in items], limit, offset, len(items))


@bp.get("/os-updates/<uid>")
def get_os_update(uid):
    require_roles("PlatformAdmin", "AdOps", "TvManufacturer")
    return ok(os_update_view(get_os_update_or_404(uid)))


@bp.post("/os-updates/<uid>/withdraw")
def withdraw_os_update(uid):
    require_roles("PlatformAdmin")
    u = get_os_update_or_404(uid)
    if u["status"] != "ROLLING":
        E.invalid_state("OS update must be ROLLING to withdraw")
    u["status"] = "WITHDRAWN"
    store.touch(u)
    return ok(os_update_view(u))

"""Derived-state services: device posture ladder, campus posture aggregation,
posture-aware reads (time-driven expiry evaluation on read)."""

import math
from datetime import timedelta

from db import db
from helpers import touch, parse_dt, ts_now


def _install_expired(install: dict, now) -> bool:
    return parse_dt(install["expires_at"], "expires_at") <= now


def _install_expired_by_time(install: dict, now) -> bool:
    """Expiry for the system sweep: driven by the date-computed expiration
    only. An expiry clamped earlier by a BATT- fault self-test report is a
    fault condition (handled by the posture ladder / telemetry), not a
    time-driven sweep event — otherwise the clamped battery would be swept
    to EXPIRED_REMOVED before a recovery PASS report can restore it."""
    base = install.get("base_expires_at") or install["expires_at"]
    return parse_dt(base, "expires_at") <= now


def device_posture(device: dict, now) -> str:
    """§2.5 device readiness posture ladder, evaluated strictly in order."""
    if device["status"] in ("POST_EVENT", "MAINTENANCE", "DECOMMISSIONED"):
        return "OUT_OF_SERVICE"

    pad = db.installs.get(device.get("current_pad_install_id") or "")
    batt = db.installs.get(device.get("current_battery_install_id") or "")
    pad_active = pad is not None and pad["disposition"] == "ACTIVE"
    batt_active = batt is not None and batt["disposition"] == "ACTIVE"

    if not pad_active or not batt_active:
        return "OUT_OF_SERVICE"
    if _install_expired(pad, now) or _install_expired(batt, now):
        return "OUT_OF_SERVICE"
    if device.get("inspection_latched"):
        # Latest inspection FAILED: forced OUT_OF_SERVICE until a later
        # passing inspection restores the device (§3.3).
        return "OUT_OF_SERVICE"
    if device.get("last_selftest_status") == "FAIL":
        # A self-test FAIL gates readiness while it is the most recent
        # telemetry relative to the last passing inspection. A later PASS
        # inspection clears the failure (§3.3); a later PASS report restores
        # last_selftest_status to PASS, clearing this condition directly.
        insp = device.get("last_inspection_at")
        rep = device.get("last_selftest_reported_at")
        if rep is None or insp is None or \
                parse_dt(rep, "reported_at") >= parse_dt(insp, "last_inspection_at"):
            return "OUT_OF_SERVICE"

    last_insp = device.get("last_inspection_at")
    if last_insp is None or now > parse_dt(last_insp, "last_inspection_at") + timedelta(days=30):
        return "DEGRADED"

    horizon = now + timedelta(days=7)
    for inst in (pad, batt):
        exp = parse_dt(inst["expires_at"], "expires_at")
        if now < exp <= horizon:
            return "DEGRADED"
    return "READY"


def refresh_campus_posture(campus_id: str, now) -> None:
    """Recompute a campus posture from its non-decommissioned devices (§2.5).
    Only bumps campus version/timestamp when the posture actually changes."""
    campus = db.campuses.get(campus_id)
    if campus is None:
        return
    devices = [d for d in db.devices.values()
               if d["campus_id"] == campus_id and d["status"] != "DECOMMISSIONED"]
    total = len(devices)
    if total == 0:
        new = "OPERATIONAL"
    else:
        out = sum(1 for d in devices if d["readiness_posture"] == "OUT_OF_SERVICE")
        deg = sum(1 for d in devices if d["readiness_posture"] == "DEGRADED")
        if out >= max(1, math.ceil(total * 0.25)):
            new = "CRITICAL"
        elif out > 0 or deg >= max(1, math.floor(total * 0.50)):
            new = "DEGRADED"
        else:
            new = "OPERATIONAL"
    if campus["readiness_posture"] != new:
        campus["readiness_posture"] = new
        touch(campus)


def set_device_posture(device: dict, now) -> bool:
    """Recompute and store a device's posture. Bumps the device version when
    the derived value changes. Returns True if it changed."""
    new = device_posture(device, now)
    if device["readiness_posture"] != new:
        device["readiness_posture"] = new
        touch(device)
        return True
    return False


def recompute_device_and_campus(device: dict, now) -> None:
    set_device_posture(device, now)
    refresh_campus_posture(device["campus_id"], now)


def sweep_device_time_based(device: dict, now) -> None:
    """Apply time-driven transitions for a device on read (system sweeps):
    expired active installs -> EXPIRED_REMOVED; lapsed SCHEDULED inspections
    -> OVERDUE; posture recomputed; campus aggregation refreshed."""
    changed = False
    for field in ("current_pad_install_id", "current_battery_install_id"):
        inst_id = device.get(field)
        if not inst_id:
            continue
        inst = db.installs.get(inst_id)
        if inst and inst["disposition"] == "ACTIVE" and _install_expired_by_time(inst, now):
            inst["disposition"] = "EXPIRED_REMOVED"
            inst["removed_at"] = ts_now()
            touch(inst)
            device[field] = None
            changed = True
    for insp in db.inspections.values():
        if insp["device_id"] != device["id"]:
            continue
        if insp["outcome"] == "SCHEDULED":
            sched = parse_dt(insp["scheduled_for"], "scheduled_for")
            if now > sched + timedelta(days=7):
                insp["outcome"] = "OVERDUE"
                touch(insp)
                changed = True
    if changed:
        touch(device)
    recompute_device_and_campus(device, now)


def sweep_all(now) -> None:
    """Time-driven sweep across every device (used on campus reads / coverage)."""
    for device in list(db.devices.values()):
        sweep_device_time_based(device, now)

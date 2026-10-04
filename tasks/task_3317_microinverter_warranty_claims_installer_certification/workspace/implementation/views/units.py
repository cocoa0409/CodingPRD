"""Unit reads, the monitoring state machine, and the claim-filing preconditions (PRD 3.4)."""

from datetime import timedelta

import db
import shapes
from approval import as_instant, as_number, body
from auth import (
    ROLE_HOMEOWNER,
    ROLE_INSTALLER,
    ROLE_MONITORING,
    ROLE_PLATFORM_ADMIN,
    get_design_project,
    get_system,
    get_unit,
    require,
)
from errors import fail
from respond import iso, ok, ok_list, paginate, parse_iso
from services import common
from services import lots as lot_service

REQUIRED = object()

def list_units():
    from flask import request

    system_id = request.args.get("system_id")
    production_lot_id = request.args.get("production_lot_id")
    monitored_status = request.args.get("monitored_status")

    rows = list(db.DB.units.values())
    if system_id:
        rows = [u for u in rows if u.get("system_id") == system_id]
    if production_lot_id:
        rows = [u for u in rows if u.get("production_lot_id") == production_lot_id]
    if monitored_status:
        rows = [u for u in rows if u.get("monitored_status") == monitored_status]
    for unit in rows:
        common.recompute_unit(unit)
    rows = db.by_created_at(rows)
    window, meta = paginate(rows, request.args)
    return ok_list([shapes.unit(u) for u in window], pagination=meta)


def read_unit(unit_id):
    unit = get_unit(unit_id)
    common.recompute_unit(unit)
    return ok(shapes.unit(unit))


def observe_unit(unit_id):
    """POST /warranty/units/{id}/observations -- the two-phase monitoring machine."""
    data = body()
    performance_ratio = as_number(data, "performance_ratio", minimum=0)
    observed_at_raw = data.get("observed_at", REQUIRED)
    if observed_at_raw is REQUIRED or observed_at_raw is None:
        fail("ERR_INVALID_REQUEST_BODY", "missing required field `observed_at`")
    observed_at = as_instant(data, "observed_at")
    telemetry_absent = bool(data.get("telemetry_absent", False))

    unit = get_unit(unit_id)
    status = unit.get("monitored_status")
    ratio = common.dec(performance_ratio)
    threshold = common.UNDERPERFORMANCE_RATIO

    if status == "ONLINE":
        if ratio == 0:
            _enter_failed(unit)
        elif ratio < threshold:
            common.set_many(unit, {
                "monitored_status": "UNDERPERFORMING",
                "last_performance_ratio": float(ratio),
                "underperformance_streak_hours":
                    int(unit.get("underperformance_streak_hours", 0)) + 1,
            })
    elif status == "UNDERPERFORMING":
        if ratio >= threshold:
            common.set_many(unit, {
                "monitored_status": "ONLINE",
                "last_performance_ratio": float(ratio),
                "underperformance_streak_hours": 0,
            })
        else:
            # The streak counts consecutive hours observed below the threshold,
            # whether the unit has just slipped or is still slipping.
            common.set_many(unit, {
                "last_performance_ratio": float(ratio),
                "underperformance_streak_hours":
                    int(unit.get("underperformance_streak_hours", 0)) + 1,
            })
    elif status == "FAILED":
        if telemetry_absent:
            # failed_at is deliberately preserved: going silent does not erase
            # the evidence that the unit failed.
            common.set_many(unit, {"monitored_status": "OFFLINE"})
    elif status == "OFFLINE":
        if ratio >= threshold:
            common.set_many(unit, {
                "monitored_status": "ONLINE",
                "last_performance_ratio": float(ratio),
                "underperformance_streak_hours": 0,
            })

    common.recompute_unit(unit)
    return ok(shapes.unit(unit))


def diagnose_unit(unit_id):
    """POST /warranty/units/{id}/diagnostics -- the UNDERPERFORMING -> FAILED hop."""
    data = body()
    unit = get_unit(unit_id)
    status = unit.get("monitored_status")

    observed_at_raw = data.get("observed_at")
    if observed_at_raw is not None:
        as_instant(data, "observed_at")

    ratio_raw = data.get("performance_ratio")
    ratio = common.dec(ratio_raw) if ratio_raw is not None else None

    if status == "UNDERPERFORMING":
        streak = int(unit.get("underperformance_streak_hours", 0))
        ratio_zero = ratio is not None and ratio == 0
        ratio_repairs = ratio is not None and ratio >= common.UNDERPERFORMANCE_RATIO
        if ratio_repairs:
            common.set_many(unit, {
                "monitored_status": "ONLINE",
                "last_performance_ratio": float(ratio),
                "underperformance_streak_hours": 0,
            })
        elif ratio_zero or streak >= common.FAILURE_STREAK_HOURS:
            _enter_failed(unit)
    elif status == "FAILED":
        pass

    if ratio_raw is not None and unit.get("monitored_status") != "FAILED":
        common.set_many(unit, {"last_performance_ratio": float(ratio_raw)})
    common.recompute_unit(unit)
    return ok(shapes.unit(unit))


def _enter_failed(unit):
    """Both failure paths: stamp the instant, then ripple into the lot."""
    common.set_many(unit, {
        "monitored_status": "FAILED",
        "failed_at": iso(common.now()),
    })
    common.recompute_unit(unit)
    lot_service.refresh_lot_after_failure(unit)
    common.recompute_unit(unit)


# ------------------------------------------------- claim-filing precondition view


def claim_filing_gates(unit, installer):
    """The four ordered gates that protect claim filing (PRD 3.6).

    Exposed as a helper so the read-side view and POST /warranty/claims run the
    identical sequence.
    """
    common.require_active_certification(installer)
    common.require_certification_not_expired(installer)

    lot = db.DB.production_lots.get(unit.get("production_lot_id"))
    if lot is not None and lot.get("lot_status") == "RECALL":
        fail("ERR_LOT_RECALL_ACTIVE")

    position = common.replacement_window_position(unit.get("system_id"))
    if position <= 0:
        fail("ERR_REPLACEMENT_LIMIT_REACHED")


def register(app):
    app.add_url_rule("/warranty/units", "list_units",
                     require(ROLE_PLATFORM_ADMIN, ROLE_INSTALLER, ROLE_MONITORING,
                             ROLE_HOMEOWNER)(list_units), methods=["GET"])
    app.add_url_rule("/warranty/units/<unit_id>", "read_unit",
                     require(ROLE_PLATFORM_ADMIN, ROLE_INSTALLER, ROLE_MONITORING,
                             ROLE_HOMEOWNER)(read_unit), methods=["GET"])
    app.add_url_rule("/warranty/units/<unit_id>/observations", "observe_unit",
                     require(ROLE_MONITORING)(observe_unit), methods=["POST"])
    app.add_url_rule("/warranty/units/<unit_id>/diagnostics", "diagnose_unit",
                     require(ROLE_MONITORING)(diagnose_unit), methods=["POST"])
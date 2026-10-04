"""Labor shift and operations checkpoint routes (PRD 3.7, 3.10)."""

from flask import Blueprint, request

import calculations as calc
import services as svc
from auth import body, optional_bool, require_int, require_str
from errors import ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE
from response import paginate, success_list, success_object
from serializers import to_dict, to_list
from store import STORE

bp = Blueprint("shifts", __name__)


def _hub(record):
    return STORE.get("hubs", record["hub_id"])


# =============================================================================
# Labor shifts
# =============================================================================

@bp.route("/airhub/shifts", methods=["POST"])
def create_shift():
    payload = body()
    hub = STORE.get("hubs", payload.get("hub_id"))
    if hub is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND")
    code = require_str(payload, "shift_code")
    if any(s.get("hub_id") == hub["id"] and s.get("shift_code") == code
           for s in STORE.all("shifts")):
        raise ApiError(ERR_INVALID_REQUEST, "shift_code must be unique within the hub.")
    start = require_int(payload, "start_minutes")
    end = require_int(payload, "end_minutes")
    if end == start:
        raise ApiError(ERR_INVALID_REQUEST,
                       "end_minutes must differ from start_minutes.")
    headcount = require_int(payload, "headcount", minimum=1)
    productivity = require_int(payload, "productivity_grams_per_operator_hour", minimum=1)
    forecast = require_int(payload, "forecast_volume_grams", minimum=1)
    hazmat = optional_bool(payload, "certified_for_hazmat", False)
    shift = STORE.create("shifts", {
        "hub_id": hub["id"],
        "shift_code": code,
        "start_minutes": start,
        "end_minutes": end,
        "headcount": headcount,
        "productivity_grams_per_operator_hour": productivity,
        "forecast_volume_grams": forecast,
        "certified_for_hazmat": hazmat,
        "volume_variance_pct": 0.0,
        "staffing_posture": "GREEN",
        "status": "SCHEDULED",
    })
    calc.recompute_shift(STORE, hub, shift)
    return success_object(to_dict("shifts", shift), 201)


@bp.route("/airhub/shifts", methods=["GET"])
def list_shifts():
    rows = STORE.all("shifts")
    args = request.args
    for field in ("hub_id", "status"):
        value = args.get(field)
        if value:
            rows = [r for r in rows if r.get(field) == value]
    page, limit, offset, total = paginate(rows, args)
    return success_list(to_list("shifts", page), limit, offset, total)


@bp.route("/airhub/shifts/<shift_id>", methods=["GET"])
def get_shift(shift_id):
    shift = STORE.get("shifts", shift_id)
    hub = _hub(shift)
    calc.recompute_shift(STORE, hub, shift)
    return success_object(to_dict("shifts", shift))


@bp.route("/airhub/shifts/<shift_id>/cancel", methods=["POST"])
def cancel_shift(shift_id):
    shift = STORE.get("shifts", shift_id)
    if shift.get("status") in ("CANCELLED", "COMPLETED"):
        raise ApiError(ERR_INVALID_STATE)
    hub = _hub(shift)
    containing = calc.containing_shift(STORE, hub, STORE.minute())
    if containing is not None and containing["id"] == shift["id"]:
        raise ApiError(ERR_INVALID_STATE,
                       "The shift currently gating induction cannot be cancelled.")
    shift["status"] = "CANCELLED"
    STORE.touch("shifts", shift)
    return success_object(to_dict("shifts", shift))


@bp.route("/airhub/shifts/<shift_id>/complete", methods=["POST"])
def complete_shift(shift_id):
    shift = STORE.get("shifts", shift_id)
    hub = _hub(shift)
    calc.recompute_shift(STORE, hub, shift)
    if shift.get("status") == "COMPLETED":
        raise ApiError(ERR_INVALID_STATE)
    if shift.get("staffing_posture") == "SATURATED":
        raise ApiError(ERR_INVALID_STATE,
                       "The shift must be brought back under the overrun band first.")
    shift["status"] = "COMPLETED"
    STORE.touch("shifts", shift)
    return success_object(to_dict("shifts", shift))


@bp.route("/airhub/shifts/<shift_id>/forecast-volume", methods=["POST"])
def forecast_volume(shift_id):
    shift = STORE.get("shifts", shift_id)
    hub = _hub(shift)
    payload = body()
    forecast = require_int(payload, "forecast_volume_grams", minimum=1)
    shift["forecast_volume_grams"] = forecast
    calc.recompute_shift(STORE, hub, shift)
    STORE.touch("shifts", shift)
    return success_object(to_dict("shifts", shift))


# =============================================================================
# Operations checkpoints
# =============================================================================

@bp.route("/airhub/ops-runs", methods=["GET"])
def list_ops_runs():
    rows = STORE.all("ops_runs")
    args = request.args
    for field in ("hub_id", "level", "verdict"):
        value = args.get(field)
        if value:
            rows = [r for r in rows if r.get(field) == value]
    page, limit, offset, total = paginate(rows, args)
    return success_list(to_list("ops_runs", page), limit, offset, total)


@bp.route("/airhub/ops-runs/<ops_run_id>", methods=["GET"])
def get_ops_run(ops_run_id):
    run = STORE.get("ops_runs", ops_run_id)
    return success_object(to_dict("ops_runs", run))


@bp.route("/airhub/ops-runs/<ops_run_id>/advance", methods=["POST"])
def advance_ops_run(ops_run_id):
    run = STORE.get("ops_runs", ops_run_id)
    hub = _hub(run)
    if run.get("verdict") != "HELD":
        raise ApiError(ERR_INVALID_STATE)
    if not hub.get("contingency_mode"):
        raise ApiError(ERR_INVALID_STATE)
    run["verdict"] = "ADVANCED"
    for pkg in STORE.all("packages"):
        if pkg.get("hub_id") != hub["id"]:
            continue
        if pkg.get("commitment_status") == "DOWNGRADED":
            # PRD 3.10: the advance re-routes the COMMITMENT only.  The handling
            # dimension is left untouched -- only the diverge decision of 3.9 sets
            # DIVERTED -- so the package survives a later clear-contingency sweep
            # (which selects on DIVERTED handling AND REROUTED commitment).
            pkg["commitment_status"] = "REROUTED"
            pkg["final_commitment_minutes"] = (
                int(pkg["commitment_cutoff_minutes"]) + calc.NORMAL_REROUTE_BUFFER_MINUTES)
            svc.refresh_package_postures(pkg)
            STORE.touch("packages", pkg)
    for aircraft in STORE.all("aircraft"):
        bank = STORE.get("banks", aircraft.get("bank_id"))
        if not bank or bank.get("hub_id") != hub["id"]:
            continue
        if aircraft.get("status") != "CANCELLED" or not aircraft.get("maintenance_hold"):
            continue
        aircraft["status"] = "IN_FLIGHT"
        aircraft["actual_arrival_minutes"] = None
        STORE.touch("aircraft", aircraft)
    hub["ops_run_index"] = int(hub.get("ops_run_index") or 0) + 1
    STORE.touch("hubs", hub)
    svc.hub_and_shifts(STORE, hub)
    return success_object(to_dict("ops_runs", run))


@bp.route("/airhub/ops-runs/<ops_run_id>/release", methods=["POST"])
def release_ops_run(ops_run_id):
    run = STORE.get("ops_runs", ops_run_id)
    hub = _hub(run)
    if run.get("verdict") != "HELD":
        raise ApiError(ERR_INVALID_STATE)
    if hub.get("contingency_mode"):
        raise ApiError(ERR_INVALID_STATE)
    run["verdict"] = "RELEASED"
    reassigned = []
    for pkg in STORE.all("packages"):
        if pkg.get("hub_id") != hub["id"]:
            continue
        if pkg.get("commitment_status") == "DOWNGRADED":
            svc.cascade_upgrade_hold(pkg)
            STORE.touch("packages", pkg)
            reassigned.append(pkg)
    hub["ops_run_index"] = int(hub.get("ops_run_index") or 0) + 1
    STORE.touch("hubs", hub)
    svc.hub_and_shifts(STORE, hub)
    for pkg in reassigned:
        svc.new_failure(STORE, hub, pkg, "LATE_INBOUND")
    return success_object(to_dict("ops_runs", run))
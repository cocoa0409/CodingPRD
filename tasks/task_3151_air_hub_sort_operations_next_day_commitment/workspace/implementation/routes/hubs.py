"""Hub routes, the logical clock and the hub-level computed reads."""

from flask import Blueprint, request

import calculations as calc
import services as svc
from auth import (
    body,
    check_body_fks,
    ENDPOINTS,
    require_enum,
    require_int,
    require_str,
)
from errors import (
    ApiError,
    ERR_CLOCK_OUT_OF_ORDER,
    ERR_CONTINGENCY_NOT_DECLARED,
    ERR_HUB_NOT_LOCKED,
    ERR_INVALID_REQUEST,
)
from response import paginate, success_list, success_object
from serializers import to_dict, to_list
from store import STORE, parse_utc

bp = Blueprint("hubs", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    payload = body()
    require_str(payload, "current_utc")
    moment = parse_utc(payload["current_utc"])
    if moment is None:
        raise ApiError(ERR_INVALID_REQUEST, "current_utc must be an ISO 8601 instant.")
    if moment < STORE.clock:
        raise ApiError(ERR_CLOCK_OUT_OF_ORDER)
    STORE.set_clock(moment)
    return success_object({})


@bp.route("/airhub/hubs", methods=["POST"])
def create_hub():
    payload = body()
    check_body_fks(STORE, ENDPOINTS[("POST", "/airhub/hubs")], payload)
    iata = require_str(payload, "iata_code")
    if any(h.get("iata_code") == iata for h in STORE.all("hubs")):
        raise ApiError(ERR_INVALID_REQUEST, "iata_code must be unique across all hubs.")
    require_str(payload, "name")
    open_minutes = require_int(payload, "sort_window_open_minutes")
    close_minutes = require_int(payload, "sort_window_close_minutes")
    if close_minutes <= open_minutes:
        raise ApiError(ERR_INVALID_REQUEST,
                       "sort_window_close_minutes must be strictly greater than the open minute.")
    hub = STORE.create("hubs", {
        "iata_code": iata,
        "name": payload["name"],
        "sort_window_open_minutes": open_minutes,
        "sort_window_close_minutes": close_minutes,
        "live_planned_package_total": 0,
        "posture": "OPEN",
        "contingency_mode": False,
        "alternate_hub_id": payload.get("alternate_hub_id"),
        "ops_run_index": 0,
    })
    return success_object(to_dict("hubs", hub), 201)


@bp.route("/airhub/hubs", methods=["GET"])
def list_hubs():
    rows = STORE.all("hubs")
    args = request.args
    if args.get("iata_code"):
        rows = [r for r in rows if r["iata_code"] == args["iata_code"]]
    if args.get("alternate_hub_id"):
        rows = [r for r in rows if r.get("alternate_hub_id") == args["alternate_hub_id"]]
    if args.get("posture"):
        rows = [r for r in rows if r["posture"] == args["posture"]]
    page, limit, offset, total = paginate(rows, args)
    return success_list(to_list("hubs", page), limit, offset, total)


@bp.route("/airhub/hubs/<hub_id>", methods=["GET"])
def get_hub(hub_id):
    hub = STORE.get("hubs", hub_id)
    return success_object(to_dict("hubs", hub))


@bp.route("/airhub/hubs/<hub_id>/declare-contingency", methods=["POST"])
def declare_contingency(hub_id):
    hub = STORE.get("hubs", hub_id)
    if hub.get("contingency_mode"):
        raise ApiError(ERR_CONTINGENCY_NOT_DECLARED)
    hub["contingency_mode"] = True
    svc.hub_and_shifts(STORE, hub)
    return success_object(to_dict("hubs", hub))


@bp.route("/airhub/hubs/<hub_id>/clear-contingency", methods=["POST"])
def clear_contingency(hub_id):
    hub = STORE.get("hubs", hub_id)
    if not hub.get("contingency_mode"):
        raise ApiError(ERR_CONTINGENCY_NOT_DECLARED)
    hub["contingency_mode"] = False
    hub.pop("_volume_override", None)
    # "with the mode false the posture returns to OPEN or CONGESTED purely as a
    # function of live volume" — clearing is the one path that de-escalates a
    # GROUND_STOP hub, because GROUND_STOP is otherwise never produced by the
    # posture computation.
    live = calc.live_planned_package_total(STORE, hub["id"])
    hub["posture"] = calc.posture_from_volume(hub, live)
    # Every diverted package returns to its original commitment; every parked
    # package takes the assurance extension and emits a customer failure.
    original_levels = {p["id"]: _original_level(p) for p in STORE.all("packages")}
    for pkg in STORE.all("packages"):
        if pkg.get("hub_id") != hub["id"]:
            continue
        if pkg.get("handling_status") == "DIVERTED" and pkg.get("commitment_status") == "REROUTED":
            pkg["commitment_status"] = "COMMITTED"
            pkg["handling_status"] = "NORMAL"
            pkg["final_commitment_minutes"] = None
            pkg["service_level"] = original_levels.get(pkg["id"], pkg["service_level"])
            svc.refresh_package_postures(pkg)
            STORE.touch("packages", pkg)
            for failure in STORE.all("failures"):
                if failure.get("package_id") == pkg["id"] and failure.get("status") == "OPEN":
                    failure["status"] = "VOIDED"
                    svc.refresh_failure(STORE, failure)
        elif pkg.get("handling_status") == "HOLD_AT_HUB" and pkg.get("commitment_status") == "COMMITTED":
            svc.cascade_upgrade_hold(pkg)
            STORE.touch("packages", pkg)
            svc.new_failure(STORE, hub, pkg, "REVENUE_PRORATE")
    svc.hub_and_shifts(STORE, hub)
    return success_object(to_dict("hubs", hub))


def _commitment_level_for(package):
    """The level the package committed to, from its cutoff and the hub window."""
    hub = STORE.get("hubs", package["hub_id"])
    close = int(hub["sort_window_close_minutes"]) if hub else 0
    delta = int(package.get("commitment_cutoff_minutes") or close) - close
    if delta >= calc.GROUND_SLIP_MINUTES:
        return "GROUND"
    if delta >= calc.SECOND_DAY_SLIP_MINUTES:
        return "SECOND_DAY_AIR"
    return "NEXT_DAY_AIR"


def _original_level(package):
    return _commitment_level_for(package)


@bp.route("/airhub/hubs/<hub_id>/ground-stop", methods=["POST"])
def ground_stop(hub_id):
    hub = STORE.get("hubs", hub_id)
    if not hub.get("contingency_mode"):
        raise ApiError(ERR_HUB_NOT_LOCKED)
    hub["posture"] = "GROUND_STOP"
    hub.pop("_volume_override", None)
    for move in STORE.all("moves"):
        if move.get("hub_id") != hub["id"]:
            continue
        if move.get("status") not in ("PLANNED", "LOADING"):
            continue
        move["status"] = "REWORK_REQUIRED"
        for pkg in STORE.move_members(move["id"]):
            if pkg.get("sort_status") == "LOADED":
                pkg["sort_status"] = "SECONDARY_SORTED"
                svc.refresh_package_postures(pkg)
                STORE.touch("packages", pkg)
        calc.recompute_move(STORE, move)
        for buildup in STORE.all("buildups"):
            if buildup.get("load_move_id") == move["id"]:
                calc.recompute_buildup(STORE, buildup)
        STORE.touch("moves", move)
    STORE.touch("hubs", hub)
    return success_object(to_dict("hubs", hub))


@bp.route("/airhub/hubs/<hub_id>/run-ops", methods=["POST"])
def run_ops(hub_id):
    hub = STORE.get("hubs", hub_id)
    payload = body()
    require_int(payload, "minute_of_day")
    level = require_enum(payload, "level", ("MINOR", "MAJOR"))
    index = int(hub.get("ops_run_index") or 0) + 1
    run = STORE.create("ops_runs", {
        "hub_id": hub["id"],
        "run_index": index,
        "minute_of_day": payload["minute_of_day"],
        "level": level,
        "verdict": "HELD",
    })
    hub["ops_run_index"] = index
    STORE.touch("hubs", hub)
    _auto_close_banks(hub)
    return success_object(to_dict("ops_runs", run), 201)


def _auto_close_banks(hub):
    for bank in STORE.all("banks"):
        if bank.get("hub_id") != hub["id"] or bank.get("status") != "UNLOADED":
            continue
        aircraft_ids = {ac["id"] for ac in STORE.all("aircraft")
                        if ac.get("bank_id") == bank["id"]}
        pending = [p for p in STORE.all("packages")
                   if p.get("aircraft_id") in aircraft_ids
                   and p.get("induction_status") == "NOT_INDUCTED"]
        if pending:
            continue
        bank["status"] = "CLOSED"
        bank["effective_sort_budget_minutes"] = 0
        STORE.touch("banks", bank)


@bp.route("/airhub/hubs/<hub_id>/volume-override", methods=["POST"])
def volume_override(hub_id):
    hub = STORE.get("hubs", hub_id)
    payload = body()
    value = require_int(payload, "live_planned_package_total", minimum=0)
    hub["_volume_override"] = value
    calc.recompute_hub(STORE, hub)
    svc.hub_and_shifts(STORE, hub)
    return success_object(to_dict("hubs", hub))


@bp.route("/airhub/hubs/<hub_id>/refund-summary", methods=["GET"])
def refund_summary(hub_id):
    hub = STORE.get("hubs", hub_id)
    return success_object(calc.refund_summary(STORE, hub["id"]))


@bp.route("/airhub/hubs/<hub_id>/triage", methods=["GET"])
def triage(hub_id):
    hub = STORE.get("hubs", hub_id)
    minute = STORE.minute()
    shift = calc.containing_shift(STORE, hub, minute)
    if shift is None:
        result = {"triage": "NO_SHIFT", "staffing_posture": None, "shift_id": None}
    else:
        posture = shift.get("staffing_posture")
        if posture == "RED":
            label = "SHED_TO_NEXT_WINDOW"
        elif posture == "SATURATED":
            label = "THROTTLE_INDUCTION"
        else:
            label = "ACCEPT"
        result = {"triage": label, "staffing_posture": posture, "shift_id": shift["id"]}
    return success_object(result)
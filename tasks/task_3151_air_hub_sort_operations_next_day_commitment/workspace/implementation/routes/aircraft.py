"""Arrival bank and aircraft routes (PRD 3.2, 3.4)."""

from flask import Blueprint, request

import calculations as calc
import services as svc
from auth import (
    body,
    check_body_fks,
    ENDPOINTS,
    optional_bool,
    require_int,
    require_str,
)
from errors import (
    ApiError,
    ERR_BANK_NOT_UNLOADING,
    ERR_CONTINGENCY_NOT_DECLARED,
    ERR_HYDRAULIC_CREW_UNAVAILABLE,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_LATE_UNLOAD_REGRESSION,
    ERR_POSTURE_BLOCKS_INDUCTION,
    ERR_UNLOAD_FACE_OCCUPIED,
)
from response import paginate, success_list, success_object
from serializers import to_dict, to_list
from store import STORE

bp = Blueprint("aircraft", __name__)

CREW_UNAVAILABLE_MESSAGE = "The bank hydraulic-lift crew is unavailable."


def _bank_hub(bank):
    return STORE.get("hubs", bank["hub_id"])


def _bank_aircraft(bank_id):
    return [ac for ac in STORE.all("aircraft") if ac.get("bank_id") == bank_id]


# =============================================================================
# Arrival banks
# =============================================================================

@bp.route("/airhub/banks", methods=["POST"])
def create_bank():
    payload = body()
    check_body_fks(STORE, ENDPOINTS[("POST", "/airhub/banks")], payload)
    hub = STORE.get("hubs", payload.get("hub_id"))
    require_str(payload, "bank_code")
    start = require_int(payload, "scheduled_start_minutes")
    end = require_int(payload, "scheduled_end_minutes")
    if end <= start:
        raise ApiError(ERR_INVALID_REQUEST,
                       "scheduled_end_minutes must be greater than scheduled_start_minutes.")
    crew = optional_bool(payload, "hydraulic_crew_available", True)
    bank = STORE.create("banks", {
        "hub_id": hub["id"],
        "bank_code": payload["bank_code"],
        "scheduled_start_minutes": start,
        "scheduled_end_minutes": end,
        "actual_start_minutes": None,
        "hydraulic_crew_available": crew,
        "status": "SCHEDULED",
        "effective_sort_budget_minutes": 0,
        "planned_start_minutes": start,
    })
    return success_object(to_dict("banks", bank), 201)


@bp.route("/airhub/banks", methods=["GET"])
def list_banks():
    rows = STORE.all("banks")
    if request.args.get("hub_id"):
        rows = [r for r in rows if r["hub_id"] == request.args["hub_id"]]
    if request.args.get("status"):
        rows = [r for r in rows if r["status"] == request.args["status"]]
    page, limit, offset, total = paginate(rows, request.args)
    return success_list(to_list("banks", page), limit, offset, total)


@bp.route("/airhub/banks/<bank_id>", methods=["GET"])
def get_bank(bank_id):
    bank = STORE.get("banks", bank_id)
    hub = _bank_hub(bank)
    calc.recompute_bank(STORE, hub, bank)
    return success_object(to_dict("banks", bank))


@bp.route("/airhub/banks/<bank_id>/begin-unload", methods=["POST"])
def begin_bank_unload(bank_id):
    bank = STORE.get("banks", bank_id)
    hub = _bank_hub(bank)
    if not bank.get("hydraulic_crew_available"):
        raise ApiError(ERR_HYDRAULIC_CREW_UNAVAILABLE, CREW_UNAVAILABLE_MESSAGE)
    if hub.get("posture") == "GROUND_STOP":
        raise ApiError(ERR_POSTURE_BLOCKS_INDUCTION)
    landed = [ac for ac in _bank_aircraft(bank_id) if ac.get("status") == "LANDED"]
    if not landed:
        raise ApiError(ERR_INVALID_STATE,
                       "At least one aircraft in the bank must already be LANDED.")
    if bank.get("status") in ("CLOSED", "ABANDONED"):
        raise ApiError(ERR_INVALID_STATE)
    # A bank that has auto-settled to UNLOADED cycles its single face back for a
    # fresh landing: the LANDED gate above is what admits the call, and the face
    # is a resource the bank re-takes rather than a one-shot transition.
    bank["actual_start_minutes"] = STORE.minute()
    bank["status"] = "UNLOADING"
    for ac in landed:
        ac["status"] = "UNLOADING"
        STORE.touch("aircraft", ac)
    calc.recompute_bank(STORE, hub, bank)
    STORE.touch("banks", bank)
    return success_object(to_dict("banks", bank))


@bp.route("/airhub/banks/<bank_id>/abandon", methods=["POST"])
def abandon_bank(bank_id):
    bank = STORE.get("banks", bank_id)
    hub = _bank_hub(bank)
    if not hub.get("contingency_mode"):
        raise ApiError(ERR_CONTINGENCY_NOT_DECLARED)
    status = bank.get("status")
    if status == "EN_ROUTE":
        if not any(r.get("level") == "MAJOR" and r.get("verdict") == "HELD"
                   for r in STORE.all("ops_runs") if r.get("hub_id") == hub["id"]):
            raise ApiError(ERR_INVALID_STATE,
                           "Abandoning an EN_ROUTE bank requires a HELD MAJOR checkpoint.")
        affected = [ac for ac in _bank_aircraft(bank_id)
                    if ac.get("status") in ("SCHEDULED", "IN_FLIGHT")]
        for ac in affected:
            ac["status"] = "CANCELLED"
            STORE.touch("aircraft", ac)
            aboard = [p for p in STORE.all("packages") if p.get("aircraft_id") == ac["id"]]
            for pkg in aboard:
                svc.cascade_downgrade(pkg)
                STORE.touch("packages", pkg)
            # exactly one weather failure per cancelled aircraft
            svc.new_failure(STORE, hub, aboard[0] if aboard else None, "WEATHER")
    elif status == "UNLOADING":
        affected = [ac for ac in _bank_aircraft(bank_id)
                    if ac.get("status") in ("UNLOADING", "LANDED")]
        for ac in affected:
            ac["status"] = "CANCELLED"
            ac["maintenance_hold"] = True
            STORE.touch("aircraft", ac)
    else:
        raise ApiError(ERR_INVALID_STATE)
    bank["status"] = "ABANDONED"
    calc.recompute_bank(STORE, hub, bank)
    STORE.touch("banks", bank)
    svc.hub_and_shifts(STORE, hub)
    return success_object(to_dict("banks", bank))


# =============================================================================
# Aircraft
# =============================================================================

@bp.route("/airhub/aircraft", methods=["POST"])
def create_aircraft():
    payload = body()
    check_body_fks(STORE, ENDPOINTS[("POST", "/airhub/aircraft")], payload)
    bank = STORE.get("banks", payload.get("bank_id"))
    require_str(payload, "tail_number")
    require_str(payload, "origin_station_code")
    require_int(payload, "scheduled_arrival_minutes")
    capacity = require_int(payload, "capacity_weight_grams", minimum=1)
    aircraft = STORE.create("aircraft", {
        "bank_id": bank["id"],
        "tail_number": payload["tail_number"],
        "origin_station_code": payload["origin_station_code"],
        "scheduled_arrival_minutes": payload["scheduled_arrival_minutes"],
        "actual_arrival_minutes": None,
        "capacity_weight_grams": capacity,
        "inbound_weight_grams": None,
        "unload_completed_minutes": None,
        "maintenance_hold": False,
        "status": "SCHEDULED",
        "unload_slack_minutes": 0,
    })
    return success_object(to_dict("aircraft", aircraft), 201)


@bp.route("/airhub/aircraft", methods=["GET"])
def list_aircraft():
    rows = STORE.all("aircraft")
    if request.args.get("bank_id"):
        rows = [r for r in rows if r["bank_id"] == request.args["bank_id"]]
    if request.args.get("status"):
        rows = [r for r in rows if r["status"] == request.args["status"]]
    page, limit, offset, total = paginate(rows, request.args)
    return success_list(to_list("aircraft", page), limit, offset, total)


@bp.route("/airhub/aircraft/<aircraft_id>", methods=["GET"])
def get_aircraft(aircraft_id):
    aircraft = STORE.get("aircraft", aircraft_id)
    return success_object(to_dict("aircraft", aircraft))


@bp.route("/airhub/aircraft/<aircraft_id>/depart-origin", methods=["POST"])
def depart_origin(aircraft_id):
    aircraft = STORE.get("aircraft", aircraft_id)
    bank = STORE.get("banks", aircraft["bank_id"])
    hub = _bank_hub(bank)
    if aircraft.get("status") != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE)
    if hub.get("posture") == "GROUND_STOP":
        raise ApiError(ERR_POSTURE_BLOCKS_INDUCTION)
    aircraft["status"] = "IN_FLIGHT"
    STORE.touch("aircraft", aircraft)
    if bank.get("status") == "SCHEDULED":
        bank["status"] = "EN_ROUTE"
        calc.recompute_bank(STORE, hub, bank)
        STORE.touch("banks", bank)
    return success_object(to_dict("aircraft", aircraft))


@bp.route("/airhub/aircraft/<aircraft_id>/land", methods=["POST"])
def land_aircraft(aircraft_id):
    aircraft = STORE.get("aircraft", aircraft_id)
    bank = STORE.get("banks", aircraft["bank_id"])
    hub = _bank_hub(bank)
    if aircraft.get("status") != "IN_FLIGHT":
        raise ApiError(ERR_INVALID_STATE)
    if hub.get("posture") == "GROUND_STOP":
        raise ApiError(ERR_POSTURE_BLOCKS_INDUCTION)
    # Landing is gated on the ground stop alone: the hydraulic-lift crew gates
    # opening the bank's unload face, not the touchdown (PRD 3.2).
    payload = body()
    require_int(payload, "inbound_weight_grams")
    aircraft["status"] = "LANDED"
    aircraft["actual_arrival_minutes"] = STORE.minute()
    aircraft["inbound_weight_grams"] = payload["inbound_weight_grams"]
    STORE.touch("aircraft", aircraft)
    # A bank whose face has folded (auto-settled to UNLOADED) re-takes it for the
    # aircraft that has just landed, so the caller does not have to re-open it
    # before the next unload (PRD 3.2's single face, cycled).
    if bank.get("status") == "UNLOADED":
        bank["actual_start_minutes"] = STORE.minute()
        bank["status"] = "UNLOADING"
    calc.recompute_bank(STORE, hub, bank)
    STORE.touch("banks", bank)
    return success_object(to_dict("aircraft", aircraft))


@bp.route("/airhub/aircraft/<aircraft_id>/begin-unload", methods=["POST"])
def begin_aircraft_unload(aircraft_id):
    aircraft = STORE.get("aircraft", aircraft_id)
    bank = STORE.get("banks", aircraft["bank_id"])
    # Opening the bank's face moves every landed aircraft to UNLOADING, so an
    # aircraft may arrive here either still LANDED (it landed after the face
    # opened) or already holding the face; both are admitted, provided no other
    # aircraft on the bank currently occupies the bank's single unload face.
    if aircraft.get("status") not in ("LANDED", "CANCELLED", "UNLOADING"):
        raise ApiError(ERR_INVALID_STATE)
    if (aircraft.get("status") == "CANCELLED"
            and aircraft.get("maintenance_hold") and aircraft.get("actual_arrival_minutes") is None):
        raise ApiError(ERR_INVALID_STATE,
                       "A maintenance-held aircraft with no arrival cannot take the face.")
    if bank.get("status") != "UNLOADING" and aircraft.get("status") != "UNLOADING":
        raise ApiError(ERR_BANK_NOT_UNLOADING)
    if not bank.get("hydraulic_crew_available"):
        raise ApiError(ERR_HYDRAULIC_CREW_UNAVAILABLE, CREW_UNAVAILABLE_MESSAGE)
    others = [ac for ac in _bank_aircraft(bank["id"])
              if ac["id"] != aircraft_id and ac.get("status") == "UNLOADING"]
    if others:
        raise ApiError(ERR_UNLOAD_FACE_OCCUPIED)
    aircraft["status"] = "UNLOADING"
    STORE.touch("aircraft", aircraft)
    return success_object(to_dict("aircraft", aircraft))


@bp.route("/airhub/aircraft/<aircraft_id>/complete-unload", methods=["POST"])
def complete_unload(aircraft_id):
    aircraft = STORE.get("aircraft", aircraft_id)
    bank = STORE.get("banks", aircraft["bank_id"])
    hub = _bank_hub(bank)
    if aircraft.get("status") != "UNLOADING":
        raise ApiError(ERR_INVALID_STATE)
    # The maintenance divert is a self-transition that leaves the aircraft in the
    # air, so an unload cannot complete off a face it no longer holds (PRD 3.4).
    if aircraft.get("maintenance_hold"):
        raise ApiError(ERR_INVALID_STATE)
    payload = body()
    completed = require_int(payload, "unload_completed_minutes")
    if aircraft.get("actual_arrival_minutes") is not None:
        if completed < int(aircraft["actual_arrival_minutes"]):
            raise ApiError(ERR_LATE_UNLOAD_REGRESSION)
    for pkg in STORE.all("packages"):
        if pkg.get("aircraft_id") != aircraft_id:
            continue
        if pkg.get("commitment_status") not in ("COMMITTED", "DOWNGRADED"):
            continue
        if int(pkg["commitment_cutoff_minutes"]) > STORE.minute():
            continue
        svc.cascade_downgrade(pkg)
        if hub.get("contingency_mode"):
            pkg["commitment_status"] = "UPGRADED_HELD"
            pkg["final_commitment_minutes"] = int(pkg["commitment_cutoff_minutes"])
            svc.refresh_package_postures(pkg)
            svc.new_failure(STORE, hub, pkg, "WEATHER")
        STORE.touch("packages", pkg)
    aircraft["status"] = "UNLOADED"
    aircraft["unload_completed_minutes"] = completed
    STORE.touch("aircraft", aircraft)
    _settle_bank(bank, hub)
    svc.hub_and_shifts(STORE, hub)
    return success_object(to_dict("aircraft", aircraft))


def _settle_bank(bank, hub):
    aircraft = _bank_aircraft(bank["id"])
    if aircraft and all(ac.get("status") in ("UNLOADED", "CANCELLED") for ac in aircraft):
        if bank.get("status") == "UNLOADING":
            bank["status"] = "UNLOADED"
    calc.recompute_bank(STORE, hub, bank)
    STORE.touch("banks", bank)


@bp.route("/airhub/aircraft/<aircraft_id>/cancel", methods=["POST"])
def cancel_aircraft(aircraft_id):
    aircraft = STORE.get("aircraft", aircraft_id)
    bank = STORE.get("banks", aircraft["bank_id"])
    hub = _bank_hub(bank)
    if aircraft.get("status") not in ("SCHEDULED", "IN_FLIGHT", "LANDED", "UNLOADING", "UNLOADED"):
        raise ApiError(ERR_INVALID_STATE)
    payload = body()
    require_str(payload, "cause_code")
    if payload["cause_code"] not in calc.ATTRIBUTION:
        raise ApiError(ERR_INVALID_REQUEST, "Invalid cause_code.")
    for pkg in STORE.all("packages"):
        if pkg.get("aircraft_id") != aircraft_id:
            continue
        if pkg.get("sort_status") != "UNSORTED":
            raise ApiError(ERR_INVALID_STATE,
                           "No package on this aircraft may have left UNSORTED.")
    cause = payload["cause_code"]
    aircraft["status"] = "CANCELLED"
    if cause == "MECHANICAL":
        aircraft["maintenance_hold"] = True
    STORE.touch("aircraft", aircraft)
    for pkg in STORE.all("packages"):
        if pkg.get("aircraft_id") != aircraft_id:
            continue
        svc.cascade_upgrade_hold(pkg)
        svc.refresh_package_postures(pkg)
        STORE.touch("packages", pkg)
        svc.new_failure(STORE, hub, pkg, "MECHANICAL")
    _settle_bank(bank, hub)
    svc.hub_and_shifts(STORE, hub)
    return success_object(to_dict("aircraft", aircraft))


@bp.route("/airhub/aircraft/<aircraft_id>/divert-maintenance", methods=["POST"])
def divert_maintenance(aircraft_id):
    aircraft = STORE.get("aircraft", aircraft_id)
    bank = STORE.get("banks", aircraft["bank_id"])
    hub = _bank_hub(bank)
    if not hub.get("contingency_mode"):
        raise ApiError(ERR_CONTINGENCY_NOT_DECLARED)
    if aircraft.get("maintenance_hold"):
        raise ApiError(ERR_INVALID_STATE)
    if aircraft.get("status") != "IN_FLIGHT":
        raise ApiError(ERR_INVALID_STATE)
    aircraft["maintenance_hold"] = True
    aircraft["actual_arrival_minutes"] = None
    STORE.touch("aircraft", aircraft)
    calc.recompute_bank(STORE, hub, bank)
    return success_object(to_dict("aircraft", aircraft))


@bp.route("/airhub/aircraft/<aircraft_id>/reinstate", methods=["POST"])
def reinstate_aircraft(aircraft_id):
    aircraft = STORE.get("aircraft", aircraft_id)
    bank = STORE.get("banks", aircraft["bank_id"])
    hub = _bank_hub(bank)
    if aircraft.get("status") != "CANCELLED":
        raise ApiError(ERR_INVALID_STATE)
    if hub.get("contingency_mode"):
        raise ApiError(ERR_CONTINGENCY_NOT_DECLARED)
    if aircraft.get("maintenance_hold"):
        raise ApiError(ERR_INVALID_STATE)
    aircraft["status"] = "IN_FLIGHT"
    aircraft["actual_arrival_minutes"] = None
    aircraft["unload_completed_minutes"] = None
    aircraft["inbound_weight_grams"] = None
    STORE.touch("aircraft", aircraft)
    calc.recompute_bank(STORE, hub, bank)
    return success_object(to_dict("aircraft", aircraft))
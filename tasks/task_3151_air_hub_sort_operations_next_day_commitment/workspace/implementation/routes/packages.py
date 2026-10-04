"""Package routes: creation, induction, sorting, handling and commitment (PRD 3.1-3.5, 3.9, 3.14)."""

import json

from flask import Blueprint, request

import calculations as calc
import services as svc
from auth import (
    body,
    require_enum,
    require_int,
    require_str,
)
from errors import (
    ApiError,
    ERR_ACK_MISMATCH,
    ERR_AIRCRAFT_NOT_CANCELLED,
    ERR_COMMITMENT_GRACE_EXCEEDED,
    ERR_CONTINGENCY_NOT_DECLARED,
    ERR_CUTOFF_NOT_REACHED,
    ERR_DUPLICATE_LIVE_PACKAGE,
    ERR_FINALIZED_FAILURE_PRESENT,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_IRREGULAR_RESOLVE_BUDGET_EXCEEDED,
    ERR_LANE_CAPACITY_EXCEEDED,
    ERR_LANE_CERTIFICATION_LAPSED,
    ERR_LANE_NOT_AVAILABLE,
    ERR_NO_ALTERNATE_HUB,
    ERR_POSTURE_BLOCKS_INDUCTION,
    ERR_SORT_PENDING,
    ERR_SORT_STAGE_BUDGET_EXCEEDED,
    ERR_STALE_VERSION,
)
from response import paginate, success_list, success_object
from serializers import to_dict, to_list
from store import STORE

bp = Blueprint("packages", __name__)

COMMODITY_CLASSES = ("GENERAL", "IRREGULAR", "HAZMAT", "PERISHABLE")
SERVICE_LEVELS = ("NEXT_DAY_AIR", "SECOND_DAY_AIR", "GROUND")
LANE_KINDS = ("PRIMARY", "SECONDARY", "IRREGULAR", "HAZMAT")


def _hub(package):
    return STORE.get("hubs", package["hub_id"])


def _signature(payload):
    keys = ("aircraft_id", "tracking_number", "commodity_class", "destination_hub_code",
            "service_level", "planned_weight_grams", "dimension_weight_grams")
    return json.dumps({k: payload.get(k) for k in keys}, sort_keys=True)


def _clear_override(hub):
    hub.pop("_volume_override", None)


def _require_not_loaded(package):
    if package.get("sort_status") == "LOADED":
        raise ApiError(ERR_SORT_PENDING)


def _lane_gates(lane, package, hub, minute, kind=None):
    """Certification, availability and capacity, in the pinned rule order.

    A closed lane, or one whose commodity capability does not match, is simply
    not available; a capability-matching lane that would overflow its hourly
    capacity is refused with the capacity error even though its own derived
    status has already flipped to SATURATED.
    """
    if minute >= int(lane["certified_until_minutes"]):
        raise ApiError(ERR_LANE_CERTIFICATION_LAPSED)
    if lane.get("status") == "CLOSED":
        raise ApiError(ERR_LANE_NOT_AVAILABLE)
    if lane.get("commodity_capability") != package.get("commodity_class"):
        raise ApiError(ERR_LANE_NOT_AVAILABLE)
    if kind and lane.get("lane_kind") != kind:
        raise ApiError(ERR_LANE_NOT_AVAILABLE)
    load = calc.sort_lane_load(STORE, lane)
    if load + int(package.get("rated_weight_grams") or 0) > int(lane["capacity_weight_grams"]):
        raise ApiError(ERR_LANE_CAPACITY_EXCEEDED)
    if lane.get("status") != "AVAILABLE":
        raise ApiError(ERR_LANE_NOT_AVAILABLE)


# =============================================================================
# Creation and reads
# =============================================================================

@bp.route("/airhub/packages", methods=["POST"])
def create_package():
    payload = body()
    hub = STORE.get("hubs", payload.get("hub_id"))
    aircraft = STORE.get("aircraft", payload.get("aircraft_id"))
    if hub is None or aircraft is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND")
    if aircraft.get("bank_id"):
        bank = STORE.get("banks", aircraft["bank_id"])
        if bank and bank.get("hub_id") != hub["id"]:
            raise ApiError("ERR_RESOURCE_NOT_FOUND")

    require_str(payload, "tracking_number")
    commodity = require_enum(payload, "commodity_class", COMMODITY_CLASSES)
    require_str(payload, "destination_hub_code")
    service_level = require_enum(payload, "service_level", SERVICE_LEVELS)
    planned = require_int(payload, "planned_weight_grams", minimum=1)
    dimension = require_int(payload, "dimension_weight_grams", minimum=1)

    ack = payload.get("acknowledgement_number")
    if ack is not None:
        if not isinstance(ack, str):
            raise ApiError(ERR_INVALID_REQUEST, "acknowledgement_number must be a string.")
        existing = STORE.find_by_ack(hub["id"], ack)
        if existing is not None:
            if existing.get("_ack_signature") != _signature(payload):
                raise ApiError(ERR_ACK_MISMATCH)
            return success_object(to_dict("packages", existing))

    for other in STORE.all("packages"):
        if other.get("hub_id") != hub["id"]:
            continue
        if other.get("tracking_number") != payload["tracking_number"]:
            continue
        if other.get("commitment_status") in ("VOIDED", "DIVERTED"):
            continue
        raise ApiError(ERR_DUPLICATE_LIVE_PACKAGE)

    package = STORE.create("packages", {
        "hub_id": hub["id"],
        "aircraft_id": aircraft["id"],
        "tracking_number": payload["tracking_number"],
        "acknowledgement_number": ack,
        "commodity_class": commodity,
        "destination_hub_code": payload["destination_hub_code"],
        "service_level": service_level,
        "commitment_cutoff_minutes": calc.commitment_cutoff_minutes(service_level, hub),
        "planned_weight_grams": planned,
        "rated_weight_grams": None,
        "dimension_weight_grams": dimension,
        "induction_status": "NOT_INDUCTED",
        "sort_status": "UNSORTED",
        "commitment_status": "COMMITTED",
        "handling_status": "NORMAL",
        "last_sort_minutes": None,
        "buildup_id": None,
        "assigned_lane_id": None,
        "staged_feeder_id": None,
        "handling_posture": "STANDARD",
        "commitment_posture": "COMMITTED_OK",
        "final_commitment_minutes": None,
        "_ack_signature": _signature(payload) if ack is not None else None,
    })
    _clear_override(hub)
    svc.hub_and_shifts(STORE, hub)
    return success_object(to_dict("packages", package), 201)


@bp.route("/airhub/packages", methods=["GET"])
def list_packages():
    rows = STORE.all("packages")
    args = request.args
    for field in ("hub_id", "aircraft_id", "assigned_lane_id", "staged_feeder_id",
                  "buildup_id", "induction_status", "sort_status", "commitment_status",
                  "handling_status", "service_level", "commodity_class"):
        value = args.get(field)
        if value:
            rows = [r for r in rows if r.get(field) == value]
    page, limit, offset, total = paginate(rows, args)
    return success_list(to_list("packages", page), limit, offset, total)


@bp.route("/airhub/packages/<package_id>", methods=["GET"])
def get_package(package_id):
    package = STORE.get("packages", package_id)
    return success_object(to_dict("packages", package))


@bp.route("/airhub/packages/<package_id>/failures", methods=["GET"])
def list_package_failures(package_id):
    STORE.get("packages", package_id)
    rows = svc.package_failures(STORE, package_id)
    page, limit, offset, total = paginate(rows, request.args)
    return success_list(to_list("failures", page), limit, offset, total)


# =============================================================================
# Induction
# =============================================================================

@bp.route("/airhub/packages/<package_id>/induct", methods=["POST"])
def induct(package_id):
    package = STORE.get("packages", package_id)
    hub = _hub(package)
    payload = body()
    dimension = require_int(payload, "dimension_weight_grams", minimum=1)
    # The induction dimension is a one-way door: it is entered from NOT_INDUCTED
    # and REJECTED is terminal (PRD 3.1).
    if package.get("induction_status") != "NOT_INDUCTED":
        raise ApiError(ERR_INVALID_STATE)
    if hub.get("posture") not in ("OPEN", "CONGESTED"):
        raise ApiError(ERR_POSTURE_BLOCKS_INDUCTION)
    shift = calc.containing_shift(STORE, hub, STORE.minute())
    if shift is not None and shift.get("staffing_posture") == "SATURATED":
        raise ApiError(ERR_INVALID_STATE, "The containing shift is SATURATED.")
    aircraft = STORE.get("aircraft", package.get("aircraft_id"))
    if not aircraft or aircraft.get("status") != "UNLOADED":
        raise ApiError(ERR_INVALID_STATE, "The inbound aircraft must be UNLOADED.")
    if dimension < 1:
        raise ApiError(ERR_INVALID_REQUEST, "dimension_weight_grams must be at least 1.")
    package["dimension_weight_grams"] = dimension
    package["induction_status"] = "INDUCTED"
    package["rated_weight_grams"] = calc.rated_sort_weight(
        package["planned_weight_grams"], dimension)
    svc.refresh_package_postures(package)
    STORE.touch("packages", package)
    _clear_override(hub)
    svc.hub_and_shifts(STORE, hub)
    return success_object(to_dict("packages", package))


@bp.route("/airhub/packages/<package_id>/reject-induction", methods=["POST"])
def reject_induction(package_id):
    package = STORE.get("packages", package_id)
    if package.get("induction_status") != "NOT_INDUCTED":
        raise ApiError(ERR_INVALID_STATE)
    package["induction_status"] = "REJECTED"
    STORE.touch("packages", package)
    return success_object(to_dict("packages", package))


# =============================================================================
# Sorting
# =============================================================================

@bp.route("/airhub/packages/<package_id>/primary-sort", methods=["POST"])
def primary_sort(package_id):
    package = STORE.get("packages", package_id)
    hub = _hub(package)
    payload = body()
    lane = STORE.get("lanes", payload.get("lane_id"))
    if package.get("induction_status") != "INDUCTED":
        raise ApiError(ERR_INVALID_STATE)
    if hub.get("posture") == "LOCKDOWN":
        raise ApiError(ERR_INVALID_STATE)
    if package.get("handling_status") not in ("NORMAL", "ROUTED_TO_IRREGULAR"):
        raise ApiError(ERR_INVALID_STATE)
    minute = STORE.minute()
    _lane_gates(lane, package, hub, minute)
    # PRD 3.3 pins the primary sort's lane gates to availability and commodity
    # certification.  A dedicated commodity lane (IRREGULAR or HAZMAT) is a
    # legitimate primary face for the class it is certified for.
    if lane.get("lane_kind") not in ("PRIMARY", package.get("commodity_class")):
        raise ApiError(ERR_LANE_NOT_AVAILABLE)
    package["sort_status"] = "PRIMARY_SORTED"
    package["assigned_lane_id"] = lane["id"]
    package["last_sort_minutes"] = minute
    if package.get("commodity_class") in ("IRREGULAR", "PERISHABLE"):
        package["handling_status"] = "ROUTED_TO_IRREGULAR"
    elif package.get("commodity_class") == "HAZMAT":
        package["handling_status"] = "ROUTED_TO_HAZMAT"
    svc.refresh_package_postures(package)
    STORE.touch("packages", package)
    calc.recompute_lane(STORE, lane)
    return success_object(to_dict("packages", package))


@bp.route("/airhub/packages/<package_id>/secondary-sort", methods=["POST"])
def secondary_sort(package_id):
    package = STORE.get("packages", package_id)
    hub = _hub(package)
    payload = body()
    lane = STORE.get("lanes", payload.get("lane_id"))
    if package.get("sort_status") != "PRIMARY_SORTED":
        raise ApiError(ERR_INVALID_STATE)
    if package.get("handling_status") == "ROUTED_TO_IRREGULAR":
        raise ApiError(ERR_INVALID_STATE)
    if package.get("handling_status") == "DIVERTED":
        raise ApiError(ERR_INVALID_STATE)
    minute = STORE.minute()
    # PRD 2.8 orders the business-temporal rules (ERR_LANE_CERTIFICATION_LAPSED)
    # and the business constraints ahead of state admissibility, so the lane's
    # certification is settled before the lane-kind constraint and before the
    # secondary stage budget, which is the sort's own last gate.
    _lane_gates(lane, package, hub, minute)
    if package.get("handling_status") == "ROUTED_TO_HAZMAT":
        if lane.get("lane_kind") != "HAZMAT":
            raise ApiError(ERR_LANE_NOT_AVAILABLE)
    elif lane.get("lane_kind") != "SECONDARY":
        raise ApiError(ERR_LANE_NOT_AVAILABLE)
    last = int(package.get("last_sort_minutes") or 0)
    if last != int(minute) and minute - last > calc.SECONDARY_STAGE_BUDGET_MINUTES:
        raise ApiError(ERR_SORT_STAGE_BUDGET_EXCEEDED)
    previous = package.get("assigned_lane_id")
    package["sort_status"] = "SECONDARY_SORTED"
    package["assigned_lane_id"] = lane["id"]
    package["last_sort_minutes"] = minute
    svc.refresh_package_postures(package)
    STORE.touch("packages", package)
    calc.recompute_lane(STORE, lane)
    if previous and previous != lane["id"]:
        old = STORE.get("lanes", previous)
        if old:
            calc.recompute_lane(STORE, old)
    return success_object(to_dict("packages", package))


@bp.route("/airhub/packages/<package_id>/reclaim-lane", methods=["POST"])
def reclaim_lane(package_id):
    package = STORE.get("packages", package_id)
    if package.get("sort_status") not in ("PRIMARY_SORTED", "SECONDARY_SORTED"):
        raise ApiError(ERR_INVALID_STATE)
    lane = STORE.get("lanes", package.get("assigned_lane_id"))
    package["sort_status"] = "UNSORTED"
    package["assigned_lane_id"] = None
    if package.get("handling_status") in ("ROUTED_TO_IRREGULAR", "ROUTED_TO_HAZMAT"):
        package["handling_status"] = "NORMAL"
    svc.refresh_package_postures(package)
    STORE.touch("packages", package)
    if lane:
        calc.recompute_lane(STORE, lane)
    return success_object(to_dict("packages", package))


# =============================================================================
# Handling dimension
# =============================================================================

def _resolve_budget_ok(package, minute):
    last = package.get("last_sort_minutes")
    if last is None:
        return
    if minute > int(last) + calc.IRREGULAR_RESOLVE_BUDGET_MINUTES:
        raise ApiError(ERR_IRREGULAR_RESOLVE_BUDGET_EXCEEDED)


def _hazmat_lane_ok(package, lane, minute):
    if package.get("commodity_class") != "HAZMAT":
        raise ApiError(ERR_INVALID_STATE)
    if lane.get("status") != "AVAILABLE":
        raise ApiError(ERR_LANE_NOT_AVAILABLE)
    if minute >= int(lane["certified_until_minutes"]):
        raise ApiError(ERR_LANE_CERTIFICATION_LAPSED)
    if lane.get("lane_kind") != "HAZMAT":
        raise ApiError(ERR_LANE_NOT_AVAILABLE)


@bp.route("/airhub/packages/<package_id>/route-irregular", methods=["POST"])
def route_irregular(package_id):
    package = STORE.get("packages", package_id)
    payload = body()
    lane = STORE.get("lanes", payload.get("lane_id"))
    if package.get("commodity_class") not in ("IRREGULAR", "PERISHABLE"):
        raise ApiError(ERR_INVALID_STATE)
    if package.get("sort_status") != "UNSORTED":
        raise ApiError(ERR_INVALID_STATE)
    if lane.get("lane_kind") != "IRREGULAR":
        raise ApiError(ERR_LANE_NOT_AVAILABLE)
    if lane.get("status") != "AVAILABLE":
        raise ApiError(ERR_LANE_NOT_AVAILABLE)
    if STORE.minute() >= int(lane["certified_until_minutes"]):
        raise ApiError(ERR_LANE_CERTIFICATION_LAPSED)
    package["handling_status"] = "ROUTED_TO_IRREGULAR"
    svc.refresh_package_postures(package)
    STORE.touch("packages", package)
    return success_object(to_dict("packages", package))


@bp.route("/airhub/packages/<package_id>/resolve-irregular", methods=["POST"])
def resolve_irregular(package_id):
    package = STORE.get("packages", package_id)
    if package.get("handling_status") != "ROUTED_TO_IRREGULAR":
        raise ApiError(ERR_INVALID_STATE)
    _resolve_budget_ok(package, STORE.minute())
    package["handling_status"] = "NORMAL"
    svc.refresh_package_postures(package)
    STORE.touch("packages", package)
    return success_object(to_dict("packages", package))


@bp.route("/airhub/packages/<package_id>/route-hazmat", methods=["POST"])
def route_hazmat(package_id):
    package = STORE.get("packages", package_id)
    payload = body()
    lane = STORE.get("lanes", payload.get("lane_id"))
    status = package.get("handling_status")
    if status not in ("NORMAL", "ROUTED_TO_IRREGULAR"):
        raise ApiError(ERR_INVALID_STATE)
    _hazmat_lane_ok(package, lane, STORE.minute())
    if status == "ROUTED_TO_IRREGULAR":
        _resolve_budget_ok(package, STORE.minute())
        last = package.get("last_sort_minutes")
        # lane-freshness gate: strictly tighter than the reresolve budget
        if last is not None and STORE.minute() > int(last):
            raise ApiError(ERR_IRREGULAR_RESOLVE_BUDGET_EXCEEDED)
    previous = package.get("assigned_lane_id")
    package["handling_status"] = "ROUTED_TO_HAZMAT"
    svc.refresh_package_postures(package)
    STORE.touch("packages", package)
    if previous:
        old = STORE.get("lanes", previous)
        if old:
            calc.recompute_lane(STORE, old)
    return success_object(to_dict("packages", package))


@bp.route("/airhub/packages/<package_id>/resolve-hazmat", methods=["POST"])
def resolve_hazmat(package_id):
    package = STORE.get("packages", package_id)
    if package.get("handling_status") != "ROUTED_TO_HAZMAT":
        raise ApiError(ERR_INVALID_STATE)
    _resolve_budget_ok(package, STORE.minute())
    package["handling_status"] = "NORMAL"
    svc.refresh_package_postures(package)
    STORE.touch("packages", package)
    return success_object(to_dict("packages", package))


# =============================================================================
# Commitment dimension
# =============================================================================

@bp.route("/airhub/packages/<package_id>/downgrade-commitment", methods=["POST"])
def downgrade_commitment(package_id):
    package = STORE.get("packages", package_id)
    hub = _hub(package)
    payload = body()
    expected = payload.get("expected_package_version")
    if expected is not None:
        if int(expected) != int(package.get("version") or 1):
            raise ApiError(ERR_STALE_VERSION)
    if package.get("commitment_status") != "COMMITTED":
        raise ApiError(ERR_INVALID_STATE)
    _require_not_loaded(package)
    if package.get("handling_status") == "HOLD_AT_HUB":
        raise ApiError(ERR_INVALID_STATE)
    minute = STORE.minute()
    cutoff = int(package["commitment_cutoff_minutes"])
    if minute <= cutoff - calc.SERVICE_DOWNGRADE_LEAD_MINUTES:
        raise ApiError(ERR_CUTOFF_NOT_REACHED)
    if minute > cutoff + calc.COMMITMENT_GRACE_MINUTES:
        raise ApiError(ERR_COMMITMENT_GRACE_EXCEEDED)
    package["commitment_status"] = "DOWNGRADED"
    package["service_level"] = "SECOND_DAY_AIR"
    package["final_commitment_minutes"] = cutoff + calc.REROUTE_ASSURANCE_BUFFER_MINUTES
    svc.refresh_package_postures(package)
    STORE.touch("packages", package)
    svc.new_failure(STORE, hub, package, "LATE_INBOUND")
    svc.hub_and_shifts(STORE, hub)
    return success_object(to_dict("packages", package))


@bp.route("/airhub/packages/<package_id>/ground-downgrade", methods=["POST"])
def ground_downgrade(package_id):
    package = STORE.get("packages", package_id)
    hub = _hub(package)
    if hub.get("posture") not in ("LOCKDOWN", "GROUND_STOP"):
        raise ApiError(ERR_INVALID_STATE)
    if package.get("commitment_status") != "COMMITTED":
        raise ApiError(ERR_INVALID_STATE)
    _require_not_loaded(package)
    cutoff = int(package["commitment_cutoff_minutes"])
    package["commitment_status"] = "DOWNGRADED"
    package["service_level"] = "SECOND_DAY_AIR"
    package["final_commitment_minutes"] = cutoff + calc.GROUND_DOWNGRADE_EXTENSION_MINUTES
    svc.refresh_package_postures(package)
    STORE.touch("packages", package)
    svc.new_failure(STORE, hub, package, "WEATHER")
    svc.hub_and_shifts(STORE, hub)
    return success_object(to_dict("packages", package))


@bp.route("/airhub/packages/<package_id>/diverge", methods=["POST"])
def diverge(package_id):
    package = STORE.get("packages", package_id)
    hub = _hub(package)
    if not hub.get("contingency_mode"):
        raise ApiError(ERR_CONTINGENCY_NOT_DECLARED)
    if not hub.get("alternate_hub_id"):
        raise ApiError(ERR_NO_ALTERNATE_HUB)
    if package.get("commitment_status") != "COMMITTED":
        raise ApiError(ERR_INVALID_STATE)
    if package.get("handling_status") == "HOLD_AT_HUB":
        raise ApiError(ERR_INVALID_STATE)
    _require_not_loaded(package)
    if STORE.minute() <= int(package["commitment_cutoff_minutes"]):
        raise ApiError(ERR_INVALID_STATE, "The current minute must be strictly past the cutoff.")
    package["commitment_status"] = "REROUTED"
    package["handling_status"] = "DIVERTED"
    package["final_commitment_minutes"] = (
        int(package["commitment_cutoff_minutes"]) + calc.NORMAL_REROUTE_BUFFER_MINUTES)
    svc.refresh_package_postures(package)
    STORE.touch("packages", package)
    svc.new_failure(STORE, hub, package, "LATE_INBOUND")
    svc.hub_and_shifts(STORE, hub)
    return success_object(to_dict("packages", package))


@bp.route("/airhub/packages/<package_id>/upgrade-hold", methods=["POST"])
def upgrade_hold(package_id):
    package = STORE.get("packages", package_id)
    hub = _hub(package)
    if hub.get("contingency_mode"):
        raise ApiError(ERR_CONTINGENCY_NOT_DECLARED)
    if package.get("commitment_status") != "COMMITTED":
        raise ApiError(ERR_INVALID_STATE)
    if STORE.minute() <= int(package["commitment_cutoff_minutes"]):
        raise ApiError(ERR_INVALID_STATE, "The current minute must be strictly past the cutoff.")
    aircraft = STORE.get("aircraft", package.get("aircraft_id"))
    if not aircraft or aircraft.get("status") != "CANCELLED":
        raise ApiError(ERR_AIRCRAFT_NOT_CANCELLED)
    package["commitment_status"] = "UPGRADED_HELD"
    package["handling_status"] = "HOLD_AT_HUB"
    package["final_commitment_minutes"] = (
        int(package["commitment_cutoff_minutes"]) + calc.REROUTE_ASSURANCE_BUFFER_MINUTES)
    svc.refresh_package_postures(package)
    STORE.touch("packages", package)
    svc.hub_and_shifts(STORE, hub)
    return success_object(to_dict("packages", package))


@bp.route("/airhub/packages/<package_id>/clear-reroute", methods=["POST"])
def clear_reroute(package_id):
    package = STORE.get("packages", package_id)
    hub = _hub(package)
    if package.get("commitment_status") != "REROUTED":
        raise ApiError(ERR_INVALID_STATE)
    if hub.get("contingency_mode"):
        raise ApiError(ERR_CONTINGENCY_NOT_DECLARED)
    svc.cascade_commit(package)
    STORE.touch("packages", package)
    for failure in svc.package_failures(STORE, package["id"]):
        if failure.get("status") == "OPEN" and failure.get("cause_code") == "LATE_INBOUND":
            failure["status"] = "VOIDED"
            svc.refresh_failure(STORE, failure)
    svc.hub_and_shifts(STORE, hub)
    return success_object(to_dict("packages", package))


@bp.route("/airhub/packages/<package_id>/clear-upgrade-hold", methods=["POST"])
def clear_upgrade_hold(package_id):
    package = STORE.get("packages", package_id)
    hub = _hub(package)
    if package.get("commitment_status") != "UPGRADED_HELD":
        raise ApiError(ERR_INVALID_STATE)
    aircraft = STORE.get("aircraft", package.get("aircraft_id"))
    if aircraft and aircraft.get("status") == "CANCELLED":
        raise ApiError(ERR_AIRCRAFT_NOT_CANCELLED)
    if hub.get("contingency_mode"):
        raise ApiError(ERR_CONTINGENCY_NOT_DECLARED)
    svc.cascade_commit(package)
    package["sort_status"] = "UNSORTED"
    package["induction_status"] = "INDUCTED"
    package["last_sort_minutes"] = None
    package["assigned_lane_id"] = None
    svc.refresh_package_postures(package)
    STORE.touch("packages", package)
    svc.hub_and_shifts(STORE, hub)
    return success_object(to_dict("packages", package))


@bp.route("/airhub/packages/<package_id>/void", methods=["POST"])
def void_package(package_id):
    package = STORE.get("packages", package_id)
    hub = _hub(package)
    if package.get("commitment_status") != "DOWNGRADED":
        raise ApiError(ERR_INVALID_STATE)
    _require_not_loaded(package)
    if svc.has_finalized_failure(STORE, package["id"]):
        raise ApiError(ERR_FINALIZED_FAILURE_PRESENT)
    package["commitment_status"] = "VOIDED"
    package["handling_status"] = "DIVERTED"
    svc.refresh_package_postures(package)
    STORE.touch("packages", package)
    svc.hub_and_shifts(STORE, hub)
    return success_object(to_dict("packages", package))


@bp.route("/airhub/packages/<package_id>/claim-indemnity", methods=["POST"])
def claim_indemnity(package_id):
    package = STORE.get("packages", package_id)
    hub = _hub(package)
    payload = body()
    require_int(payload, "claimed_value_cents", minimum=0)
    svc.new_failure(STORE, hub, package, "NO_SCAN")
    STORE.touch("packages", package)
    return success_object(to_dict("packages", package))


@bp.route("/airhub/packages/<package_id>/assign-aircraft", methods=["POST"])
def assign_aircraft(package_id):
    package = STORE.get("packages", package_id)
    payload = body()
    aircraft = STORE.get("aircraft", payload.get("aircraft_id"))
    if aircraft is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND")
    package["aircraft_id"] = aircraft["id"]
    STORE.touch("packages", package)
    return success_object(to_dict("packages", package))
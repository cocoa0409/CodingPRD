"""Load move and buildup routes (PRD 3.6, 3.15)."""

from flask import Blueprint, request

import calculations as calc
import services as svc
from auth import body, require_enum, require_int
from errors import (
    ApiError,
    ERR_BUILDUP_UNDER_CAPACITY,
    ERR_CONTINGENCY_NOT_DECLARED,
    ERR_HAZMAT_CAP_EXCEEDED,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_LOAD_WEIGHT_EXCEEDED,
    ERR_RESOURCE_NOT_FOUND,
    ERR_STALE_VERSION,
)
from response import paginate, success_list, success_object
from serializers import to_dict, to_list
from store import STORE

bp = Blueprint("moves", __name__)

TIERS = ("UNDER_CAPACITY", "AT_CAPACITY", "RESERVE_TIER")


def _hub(record):
    return STORE.get("hubs", record["hub_id"])


def _buildups_of(move_id):
    return [b for b in STORE.all("buildups") if b.get("load_move_id") == move_id]


def _gateway_buildup(move_id, gateway_code):
    for buildup in _buildups_of(move_id):
        if buildup.get("destination_gateway_code") == gateway_code:
            return buildup
    return None


# =============================================================================
# Load moves
# =============================================================================

@bp.route("/airhub/moves", methods=["POST"])
def create_move():
    payload = body()
    hub = STORE.get("hubs", payload.get("hub_id"))
    aircraft = STORE.get("aircraft", payload.get("aircraft_id"))
    if hub is None or aircraft is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND)
    weight_limit = require_int(payload, "weight_limit_grams", minimum=1)
    sequence = int(STORE.move_sequence.get(hub["id"], 0)) + 1
    STORE.move_sequence[hub["id"]] = sequence
    move = STORE.create("moves", {
        "hub_id": hub["id"],
        "aircraft_id": aircraft["id"],
        "sequence": sequence,
        "status": "DRAFT",
        "weight_limit_grams": weight_limit,
        "planned_weight_grams": 0,
        "loaded_weight_grams": 0,
        "forward_capacity_grams": weight_limit,
        "load_plan_tier": "UNDER_CAPACITY",
        "gateway_requirements": {},
    })
    calc.recompute_move(STORE, move)
    return success_object(to_dict("moves", move), 201)


@bp.route("/airhub/moves", methods=["GET"])
def list_moves():
    rows = STORE.all("moves")
    args = request.args
    for field in ("hub_id", "aircraft_id", "status"):
        value = args.get(field)
        if value:
            rows = [r for r in rows if r.get(field) == value]
    page, limit, offset, total = paginate(rows, args)
    return success_list(to_list("moves", page), limit, offset, total)


@bp.route("/airhub/moves/<move_id>", methods=["GET"])
def get_move(move_id):
    move = STORE.get("moves", move_id)
    return success_object(to_dict("moves", move))


@bp.route("/airhub/moves/<move_id>/plan-load", methods=["POST"])
def plan_load(move_id):
    move = STORE.get("moves", move_id)
    aircraft = STORE.get("aircraft", move["aircraft_id"])
    if move.get("status") != "DRAFT":
        raise ApiError(ERR_INVALID_STATE)
    if not aircraft or aircraft.get("status") == "CANCELLED":
        raise ApiError(ERR_INVALID_STATE)
    if aircraft.get("maintenance_hold"):
        raise ApiError(ERR_INVALID_STATE)
    move["status"] = "PLANNED"
    calc.recompute_move(STORE, move)
    STORE.touch("moves", move)
    return success_object(to_dict("moves", move))


@bp.route("/airhub/moves/<move_id>/begin-loading", methods=["POST"])
def begin_loading(move_id):
    move = STORE.get("moves", move_id)
    hub = _hub(move)
    if move.get("status") != "PLANNED":
        raise ApiError(ERR_INVALID_STATE)
    if hub.get("posture") == "GROUND_STOP":
        raise ApiError(ERR_INVALID_STATE)
    move["status"] = "LOADING"
    STORE.touch("moves", move)
    return success_object(to_dict("moves", move))


@bp.route("/airhub/moves/<move_id>/complete-load", methods=["POST"])
def complete_load(move_id):
    move = STORE.get("moves", move_id)
    hub = _hub(move)
    if move.get("status") != "LOADING":
        raise ApiError(ERR_INVALID_STATE)
    for buildup in _buildups_of(move["id"]):
        delta = calc.buildup_delta(buildup)
        if delta > 0 and delta <= calc.BREACH_TOLERANCE_GRAMS:
            raise ApiError(ERR_BUILDUP_UNDER_CAPACITY)
    calc.recompute_move(STORE, move)
    planned = int(move["planned_weight_grams"])
    if planned > int(move["weight_limit_grams"]) + calc.USE_IT_OR_LOSE_IT_TOLERANCE_GRAMS:
        raise ApiError(ERR_LOAD_WEIGHT_EXCEEDED)
    if hub.get("posture") not in ("OPEN", "CONGESTED"):
        raise ApiError(ERR_INVALID_STATE)
    move["status"] = "LOADED"
    for buildup in _buildups_of(move["id"]):
        if buildup.get("status") == "OPEN":
            buildup["status"] = "SEALED"
            STORE.touch("buildups", buildup)
    STORE.touch("moves", move)
    return success_object(to_dict("moves", move))


@bp.route("/airhub/moves/<move_id>/replan", methods=["POST"])
def replan(move_id):
    move = STORE.get("moves", move_id)
    hub = _hub(move)
    if move.get("status") != "REWORK_REQUIRED":
        raise ApiError(ERR_INVALID_STATE)
    if hub.get("contingency_mode"):
        raise ApiError(ERR_CONTINGENCY_NOT_DECLARED)
    move["status"] = "PLANNED"
    STORE.touch("moves", move)
    return success_object(to_dict("moves", move))


@bp.route("/airhub/moves/<move_id>/cancel", methods=["POST"])
def cancel_move(move_id):
    move = STORE.get("moves", move_id)
    status = move.get("status")
    if status in ("DRAFT", "REWORK_REQUIRED"):
        pass
    elif status == "PLANNED":
        for pkg in STORE.move_members(move["id"]):
            if pkg.get("sort_status") == "LOADED":
                raise ApiError(ERR_INVALID_STATE,
                               "No package on this move may be LOADED.")
    else:
        raise ApiError(ERR_INVALID_STATE)
    move["status"] = "CANCELLED"
    STORE.touch("moves", move)
    return success_object(to_dict("moves", move))


@bp.route("/airhub/moves/<move_id>/set-tier", methods=["POST"])
def set_move_tier(move_id):
    move = STORE.get("moves", move_id)
    payload = body()
    move["load_plan_tier"] = require_enum(payload, "load_plan_tier", TIERS)
    STORE.touch("moves", move)
    return success_object(to_dict("moves", move))


@bp.route("/airhub/moves/<move_id>/gateway-requirements", methods=["POST"])
def gateway_requirements(move_id):
    move = STORE.get("moves", move_id)
    payload = body()
    code = payload.get("destination_gateway_code")
    if not isinstance(code, str) or not code:
        raise ApiError(ERR_INVALID_REQUEST, "destination_gateway_code is required.")
    requires = payload.get("requires_container")
    if not isinstance(requires, bool):
        raise ApiError(ERR_INVALID_REQUEST, "requires_container must be a boolean.")
    requirements = dict(move.get("gateway_requirements") or {})
    requirements[code] = requires
    move["gateway_requirements"] = requirements
    STORE.touch("moves", move)
    return success_object(to_dict("moves", move))


@bp.route("/airhub/moves/<move_id>/load-package", methods=["POST"])
def load_package(move_id):
    move = STORE.get("moves", move_id)
    payload = body()
    package = STORE.get("packages", payload.get("package_id"))
    if package is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND)

    # --- optimistic concurrency (the two guarded writes, §2.9) -------------
    expected_move = payload.get("expected_load_move_version")
    if expected_move is not None and int(expected_move) != int(move.get("version") or 1):
        raise ApiError(ERR_STALE_VERSION)
    expected_package = payload.get("expected_package_version")
    if expected_package is not None and int(expected_package) != int(package.get("version") or 1):
        raise ApiError(ERR_STALE_VERSION)

    if package.get("commitment_posture") != "COMMITTED_OK":
        raise ApiError(ERR_INVALID_STATE)
    if move.get("status") not in ("PLANNED", "LOADING"):
        raise ApiError(ERR_INVALID_STATE)
    aircraft = STORE.get("aircraft", move["aircraft_id"])
    if not aircraft or aircraft.get("status") == "CANCELLED" or aircraft.get("maintenance_hold"):
        raise ApiError(ERR_INVALID_STATE)

    target = None
    if payload.get("buildup_id"):
        target = STORE.get("buildups", payload["buildup_id"])
        if target is None:
            raise ApiError(ERR_RESOURCE_NOT_FOUND)
        if target.get("load_move_id") != move["id"]:
            raise ApiError(ERR_RESOURCE_NOT_FOUND)
    else:
        target = _gateway_buildup(move["id"], package.get("destination_hub_code"))

    # --- destination buildup guard ---------------------------------------
    if target is not None:
        delta = calc.buildup_delta(target)
        if 0 < delta <= calc.BREACH_TOLERANCE_GRAMS:
            raise ApiError(ERR_BUILDUP_UNDER_CAPACITY)
        # --- hazardous cap guard -----------------------------------------
        if package.get("commodity_class") == "HAZMAT":
            projected = int(target.get("hazardous_weight_grams") or 0) + int(
                package.get("rated_weight_grams") or 0)
            if projected > int(target.get("hazardous_cap_grams") or 0):
                raise ApiError(ERR_HAZMAT_CAP_EXCEEDED)

    # --- fiscal floors ----------------------------------------------------
    already_member = STORE.move_of(package["id"]) == move["id"]
    calc.recompute_move(STORE, move)
    raw_before = int(move.get("_raw_forward_grams", 0))
    if raw_before > calc.SORT_BUDGET_GRAMS_CEILING:
        raise ApiError(ERR_LOAD_WEIGHT_EXCEEDED)
    projected_filled = int(move["planned_weight_grams"])
    if not already_member:
        projected_filled += int(package.get("planned_weight_grams") or 0)
    raw_after = int(move["weight_limit_grams"]) - projected_filled
    if raw_after < calc.SORT_BUDGET_GRAMS_FLOOR:
        raise ApiError(ERR_LOAD_WEIGHT_EXCEEDED)

    previous_lane = package.get("assigned_lane_id")
    package["_move_id"] = move["id"]
    if target is not None:
        package["buildup_id"] = target["id"]
    package["sort_status"] = "LOADED"
    package["assigned_lane_id"] = None
    svc.refresh_package_postures(package)
    STORE.touch("packages", package)
    calc.recompute_move(STORE, move)
    STORE.touch("moves", move)
    if target is not None:
        calc.recompute_buildup(STORE, target)
        STORE.touch("buildups", target)
    if previous_lane:
        lane = STORE.get("lanes", previous_lane)
        if lane:
            calc.recompute_lane(STORE, lane)
    return success_object(to_dict("moves", move))


@bp.route("/airhub/moves/<move_id>/unload-package", methods=["POST"])
def unload_package(move_id):
    move = STORE.get("moves", move_id)
    payload = body()
    package = STORE.get("packages", payload.get("package_id"))
    if package is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND)
    if STORE.move_of(package["id"]) != move["id"]:
        raise ApiError(ERR_INVALID_STATE)
    if package.get("sort_status") != "LOADED":
        raise ApiError(ERR_INVALID_STATE)
    previous_buildup = STORE.get("buildups", package.get("buildup_id"))
    package["sort_status"] = "SECONDARY_SORTED"
    # Offboarding unwinds the onboarding: the package leaves the move and the
    # destination buildup, so both row sets return to their pre-load membership
    # (PRD 3.6: "a move read after a package was loaded and then unloaded returns
    # to exactly its pre-load tier and capacity, because the row set is identical").
    package["_move_id"] = None
    package["buildup_id"] = None
    svc.refresh_package_postures(package)
    STORE.touch("packages", package)
    calc.recompute_move(STORE, move)
    STORE.touch("moves", move)
    if previous_buildup:
        calc.recompute_buildup(STORE, previous_buildup)
        STORE.touch("buildups", previous_buildup)
    return success_object(to_dict("moves", move))


@bp.route("/airhub/moves/<move_id>/assign-buildup", methods=["POST"])
def assign_buildup(move_id):
    move = STORE.get("moves", move_id)
    payload = body()
    package = STORE.get("packages", payload.get("package_id"))
    buildup = STORE.get("buildups", payload.get("buildup_id"))
    if package is None or buildup is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND)
    if buildup.get("load_move_id") != move["id"]:
        raise ApiError(ERR_RESOURCE_NOT_FOUND)
    previous = STORE.get("buildups", package.get("buildup_id"))
    package["buildup_id"] = buildup["id"]
    STORE.touch("packages", package)
    calc.recompute_move(STORE, move)
    STORE.touch("moves", move)
    calc.recompute_buildup(STORE, buildup)
    STORE.touch("buildups", buildup)
    if previous and previous["id"] != buildup["id"]:
        calc.recompute_buildup(STORE, previous)
    return success_object(to_dict("moves", move))


# =============================================================================
# Buildups
# =============================================================================

@bp.route("/airhub/buildups", methods=["POST"])
def create_buildup():
    payload = body()
    hub = STORE.get("hubs", payload.get("hub_id"))
    # A missing required body field is a malformed request, not a missing path
    # resource (PRD 2.1): the foreign keys are validated in the order the
    # endpoint's input list declares them, and the required-input check precedes
    # the existence check for the resource that input names.
    if not payload.get("hub_id") or not payload.get("load_move_id"):
        raise ApiError(ERR_INVALID_REQUEST,
                       "hub_id and load_move_id are required.")
    move = STORE.get("moves", payload.get("load_move_id"))
    if hub is None or move is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND)
    code = payload.get("destination_gateway_code")
    if not isinstance(code, str) or not code:
        raise ApiError(ERR_INVALID_REQUEST, "destination_gateway_code is required.")
    if any(b.get("load_move_id") == move["id"] and b.get("destination_gateway_code") == code
           for b in STORE.all("buildups")):
        raise ApiError(ERR_INVALID_REQUEST,
                       "destination_gateway_code must be unique within the load move.")
    limit = require_int(payload, "container_limit_grams", minimum=1)
    cap = payload.get("hazardous_cap_grams", 0)
    if cap is None:
        cap = 0
    if isinstance(cap, bool) or not isinstance(cap, int) or cap < 0:
        raise ApiError(ERR_INVALID_REQUEST, "hazardous_cap_grams must be 0 or strictly positive.")
    requires = payload.get("requires_container", False)
    if not isinstance(requires, bool):
        raise ApiError(ERR_INVALID_REQUEST, "requires_container must be a boolean.")
    buildup = STORE.create("buildups", {
        "hub_id": hub["id"],
        "load_move_id": move["id"],
        "destination_gateway_code": code,
        "rated_weight_grams": 0,
        "container_limit_grams": limit,
        "hazardous_load": False,
        "hazardous_weight_grams": 0,
        "hazardous_cap_grams": cap,
        "requires_container": requires,
        "status": "OPEN",
        "load_plan_tier": "UNDER_CAPACITY",
    })
    return success_object(to_dict("buildups", buildup), 201)


@bp.route("/airhub/buildups", methods=["GET"])
def list_buildups():
    rows = STORE.all("buildups")
    args = request.args
    for field in ("load_move_id", "hub_id", "status"):
        value = args.get(field)
        if value:
            rows = [r for r in rows if r.get(field) == value]
    page, limit, offset, total = paginate(rows, args)
    return success_list(to_list("buildups", page), limit, offset, total)


@bp.route("/airhub/buildups/<buildup_id>", methods=["GET"])
def get_buildup(buildup_id):
    buildup = STORE.get("buildups", buildup_id)
    return success_object(to_dict("buildups", buildup))


@bp.route("/airhub/buildups/<buildup_id>/seal", methods=["POST"])
def seal_buildup(buildup_id):
    buildup = STORE.get("buildups", buildup_id)
    # PRD 2.8 orders the business constraints (ERR_BUILDUP_UNDER_CAPACITY) before
    # state admissibility, so the weight gates are settled before the status gate.
    # PRD 3.6: "sealing requires that its rated weight is at or below its
    # container limit" -- a buildup above its limit, whatever the overshoot, is
    # not sealable.
    if int(buildup["rated_weight_grams"]) > int(buildup["container_limit_grams"]):
        raise ApiError(ERR_BUILDUP_UNDER_CAPACITY)
    if buildup.get("status") != "OPEN":
        raise ApiError(ERR_INVALID_STATE)
    move = STORE.get("moves", buildup["load_move_id"])
    requires = False
    if move:
        requires = bool((move.get("gateway_requirements") or {})
                        .get(buildup["destination_gateway_code"], False))
    if requires:
        floor = int(buildup["container_limit_grams"]) - calc.CONTAINER_FILL_TOLERANCE_GRAMS
        if int(buildup["rated_weight_grams"]) < floor:
            raise ApiError(ERR_BUILDUP_UNDER_CAPACITY)
    buildup["status"] = "SEALED"
    calc.recompute_buildup(STORE, buildup)
    STORE.touch("buildups", buildup)
    return success_object(to_dict("buildups", buildup))


@bp.route("/airhub/buildups/<buildup_id>/unseal", methods=["POST"])
def unseal_buildup(buildup_id):
    buildup = STORE.get("buildups", buildup_id)
    if buildup.get("status") != "SEALED":
        raise ApiError(ERR_INVALID_STATE)
    buildup["status"] = "OPEN"
    STORE.touch("buildups", buildup)
    return success_object(to_dict("buildups", buildup))


@bp.route("/airhub/buildups/<buildup_id>/cancel", methods=["POST"])
def cancel_buildup(buildup_id):
    buildup = STORE.get("buildups", buildup_id)
    status = buildup.get("status")
    if status == "OPEN":
        for pkg in STORE.all("packages"):
            if pkg.get("buildup_id") != buildup["id"]:
                continue
            if pkg.get("sort_status") == "LOADED":
                raise ApiError(ERR_INVALID_STATE,
                               "No package in this buildup may be LOADED.")
    elif status == "SEALED":
        move = STORE.get("moves", buildup["load_move_id"])
        if move and move.get("status") == "LOADED":
            raise ApiError(ERR_INVALID_STATE)
    else:
        raise ApiError(ERR_INVALID_STATE)
    buildup["status"] = "CANCELLED"
    STORE.touch("buildups", buildup)
    return success_object(to_dict("buildups", buildup))


@bp.route("/airhub/buildups/<buildup_id>/set-tier", methods=["POST"])
def set_buildup_tier(buildup_id):
    buildup = STORE.get("buildups", buildup_id)
    payload = body()
    buildup["load_plan_tier"] = require_enum(payload, "load_plan_tier", TIERS)
    STORE.touch("buildups", buildup)
    return success_object(to_dict("buildups", buildup))
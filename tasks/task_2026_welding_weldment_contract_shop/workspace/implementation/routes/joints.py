"""Joints and weld passes (nested routes)."""

from flask import Blueprint

from db import db
from errors import (
    ApiError, ERR_STALE_VERSION, ERR_INSUFFICIENT_PERMISSIONS,
    ERR_WELDMENT_NOT_OPEN, ERR_WPS_NOT_APPROVED, ERR_JOINT_THICKNESS_OUTSIDE_WPS,
    ERR_NO_WELD_PASSES, ERR_REPAIR_CYCLE_LIMIT, ERR_WELDER_CONTINUITY_LAPSED,
    ERR_LOT_NOT_USABLE, invalid_request, invalid_state,
)
from helpers import (
    json_body, require_fields, parse_int, parse_number, kg, paginate, NDT_METHODS,
)
from middleware import require_roles, require_any
from response import success_object, success_list
from serializers import joint_out, weld_pass_out
from services import (
    stamp_new, make_versioned, mutate, get_shop, get_weldment, get_joint,
    get_welder, get_qual, get_lot, compute_continuity_expiry,
    recompute_repair_rate, check_repair_review_gate,
    derive_posture_open_restricted,
)

bp = Blueprint("joints", __name__)


# ---------------------------------------------------------------------------
# Joints
# ---------------------------------------------------------------------------

@bp.route("/weld-shop/shops/<shop_id>/weldments/<weldment_id>/joints", methods=["POST"])
@require_roles("WeldLead")
def create_joint(user_id, role, shop_id, weldment_id):
    shop = get_shop(shop_id)
    wm = get_weldment(shop_id, weldment_id)
    body = json_body()
    require_fields(body, [
        "joint_number", "wps_id", "base_metal_thickness_mm", "required_ndt_methods",
    ])
    if not isinstance(body["joint_number"], str):
        raise invalid_request("joint_number must be a string")
    wps = db.wps.get(body["wps_id"])
    if wps is None or wps["shop_id"] != shop["id"]:
        from errors import not_found
        raise not_found("WPS")
    thickness = parse_number(body["base_metal_thickness_mm"], "base_metal_thickness_mm")
    methods = body["required_ndt_methods"]
    if not isinstance(methods, list) or any(m not in NDT_METHODS for m in methods):
        raise invalid_request("required_ndt_methods must be a subset of [VT, UT, RT]")
    joint = stamp_new({
        "shop_id": shop["id"],
        "weldment_id": wm["id"],
        "joint_number": body["joint_number"],
        "wps_id": wps["id"],
        "base_metal_thickness_mm": thickness,
        "required_ndt_methods": list(methods),
        "fabrication_status": "PENDING",
        "inspection_status": "NOT_READY",
        "repair_cycle_count": 0,
        "_last_ndt_failed_at": None,
    })
    make_versioned(joint)
    db.joints[joint["id"]] = joint
    return success_object(joint_out(joint), status=201)


@bp.route("/weld-shop/shops/<shop_id>/weldments/<weldment_id>/joints", methods=["GET"])
@require_any
def list_joints_under_weldment(user_id, role, shop_id, weldment_id):
    get_shop(shop_id)
    wm = get_weldment(shop_id, weldment_id)
    records = [j for j in db.joints.values() if j["weldment_id"] == wm["id"]]
    page, limit, offset, total = paginate(records)
    return success_list([joint_out(j) for j in page], limit, offset, total)


@bp.route("/weld-shop/shops/<shop_id>/joints/<joint_id>", methods=["GET"])
@require_any
def get_joint_route(user_id, role, shop_id, joint_id):
    get_shop(shop_id)
    return success_object(joint_out(get_joint(shop_id, joint_id)))


@bp.route("/weld-shop/shops/<shop_id>/joints/<joint_id>/start-fabrication", methods=["POST"])
@require_roles("WeldLead")
def start_fabrication(user_id, role, shop_id, joint_id):
    get_shop(shop_id)
    joint = get_joint(shop_id, joint_id)
    # OCC gate (expected_joint_version non-optional)
    body = json_body()
    if "expected_joint_version" not in body or body["expected_joint_version"] is None:
        raise invalid_request("Missing required field: expected_joint_version")
    expected = parse_int(body["expected_joint_version"], "expected_joint_version")
    if expected != joint["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_joint_version does not match current version")
    if joint["fabrication_status"] != "PENDING":
        raise invalid_state("Joint fabrication_status must be PENDING to start")
    wm = db.weldments.get(joint["weldment_id"])
    if wm is None or wm["posture"] != "OPEN":
        raise ApiError(ERR_WELDMENT_NOT_OPEN, 409,
                       "Weldment posture not OPEN; start-fabrication blocked")
    wps = db.wps.get(joint["wps_id"])
    if wps is None or wps["status"] != "APPROVED":
        raise ApiError(ERR_WPS_NOT_APPROVED, 422,
                       "Referenced WPS must be APPROVED and not SUPERSEDED")
    if not (wps["thickness_min_mm"] <= joint["base_metal_thickness_mm"]
            <= wps["thickness_max_mm"]):
        raise ApiError(ERR_JOINT_THICKNESS_OUTSIDE_WPS, 422,
                       "Joint thickness outside WPS thickness envelope")
    fixture = db.fixtures.get(wm["fixture_id"])
    if fixture is None or fixture["status"] not in ("RESERVED", "IN_USE"):
        raise invalid_state("Fixture must be RESERVED or IN_USE to start fabrication")
    joint["fabrication_status"] = "IN_PROGRESS"
    mutate(joint)
    if fixture["status"] == "RESERVED":
        fixture["status"] = "IN_USE"
        mutate(fixture)
    return success_object(joint_out(joint))


@bp.route("/weld-shop/shops/<shop_id>/joints/<joint_id>/weld-out", methods=["POST"])
@require_roles("WeldLead")
def weld_out(user_id, role, shop_id, joint_id):
    get_shop(shop_id)
    joint = get_joint(shop_id, joint_id)
    if joint["fabrication_status"] != "IN_PROGRESS":
        raise invalid_state("Joint fabrication_status must be IN_PROGRESS to weld out")
    passes = [p for p in db.weld_passes.values() if p["joint_id"] == joint["id"]]
    if joint["inspection_status"] == "REPAIR_REQUIRED":
        # repair loop: needs a repair pass recorded at/after the latest NDT_FAILED
        threshold = joint["_last_ndt_failed_at"]
        has_repair = any(
            p["is_repair"] and (threshold is None or p["welded_at_utc"] >= threshold)
            for p in passes
        )
        if not has_repair:
            raise ApiError(ERR_NO_WELD_PASSES, 409,
                           "Weld-out after repair requires a repair weld pass")
    elif not passes:
        raise ApiError(ERR_NO_WELD_PASSES, 409,
                       "Weld-out requires at least one recorded weld pass")
    wm = db.weldments.get(joint["weldment_id"])
    if wm is None or wm["posture"] != "OPEN":
        raise ApiError(ERR_WELDMENT_NOT_OPEN, 409,
                       "Weldment posture not OPEN; weld-out blocked")
    joint["fabrication_status"] = "WELDED_OUT"
    if joint["inspection_status"] in ("NOT_READY", "REPAIR_REQUIRED"):
        # NOT_READY: first weld-out; REPAIR_REQUIRED: completed repair weld-out
        # (passes through REPAIR_WELDED_OUT) returns to the VT hold point.
        joint["inspection_status"] = "READY_FOR_VT"
    mutate(joint)
    return success_object(joint_out(joint))


@bp.route("/weld-shop/shops/<shop_id>/joints/<joint_id>/declare-repair", methods=["POST"])
@require_roles("QCManager")
def declare_repair(user_id, role, shop_id, joint_id):
    get_shop(shop_id)
    joint = get_joint(shop_id, joint_id)
    if joint["inspection_status"] != "NDT_FAILED":
        raise invalid_state("Joint inspection_status must be NDT_FAILED to declare repair")
    if joint["repair_cycle_count"] > 2:
        raise ApiError(ERR_REPAIR_CYCLE_LIMIT, 422,
                       "Joint repair_cycle_count would exceed hard cap of 2")
    joint["inspection_status"] = "REPAIR_REQUIRED"
    joint["fabrication_status"] = "IN_PROGRESS"
    mutate(joint)
    return success_object(joint_out(joint))


@bp.route("/weld-shop/shops/<shop_id>/joints/<joint_id>/rebind-wps", methods=["POST"])
@require_roles("QCManager")
def rebind_wps(user_id, role, shop_id, joint_id):
    shop = get_shop(shop_id)
    joint = get_joint(shop_id, joint_id)
    body = json_body()
    require_fields(body, ["new_wps_id"])
    if joint["fabrication_status"] != "ON_HOLD":
        raise invalid_state("Joint fabrication_status must be ON_HOLD to rebind")
    new_wps = db.wps.get(body["new_wps_id"])
    if new_wps is None or new_wps["shop_id"] != shop["id"]:
        from errors import not_found
        raise not_found("WPS")
    if new_wps["status"] != "APPROVED":
        raise ApiError(ERR_WPS_NOT_APPROVED, 422,
                       "New WPS must be APPROVED and not SUPERSEDED")
    if not (new_wps["thickness_min_mm"] <= joint["base_metal_thickness_mm"]
            <= new_wps["thickness_max_mm"]):
        raise ApiError(ERR_JOINT_THICKNESS_OUTSIDE_WPS, 422,
                       "Joint thickness outside WPS thickness envelope")
    joint["wps_id"] = new_wps["id"]
    joint["fabrication_status"] = "PENDING"
    mutate(joint)
    wm = db.weldments.get(joint["weldment_id"])
    if wm is not None:
        derive_posture_open_restricted(wm)
    return success_object(joint_out(joint))


# ---------------------------------------------------------------------------
# Weld passes
# ---------------------------------------------------------------------------

@bp.route("/weld-shop/shops/<shop_id>/joints/<joint_id>/weld-passes", methods=["POST"])
@require_roles("Welder")
def record_weld_pass(user_id, role, shop_id, joint_id):
    shop = get_shop(shop_id)
    joint = get_joint(shop_id, joint_id)
    body = json_body()
    require_fields(body, [
        "welder_id", "qualification_id", "consumable_lot_id",
        "consumable_used_kg", "is_repair",
    ])
    # Welder records passes under its own entity identity (PRD §2.1)
    if body["welder_id"] != user_id:
        raise ApiError(ERR_INSUFFICIENT_PERMISSIONS, 403,
                       "Welder may only record weld passes under its own identity")
    welder = get_welder(shop_id, body["welder_id"])
    qual = get_qual(shop_id, body["qualification_id"])
    lot = get_lot(shop_id, body["consumable_lot_id"])
    used = kg(parse_number(body["consumable_used_kg"], "consumable_used_kg"))
    if not isinstance(body["is_repair"], bool):
        raise invalid_request("is_repair must be a boolean")
    # Gate 1: qualification continuity (lapsed AT the expiry instant)
    now = shop["current_utc"]
    if qual["status"] != "QUALIFIED" or now >= qual["continuity_expires_at_utc"]:
        raise ApiError(ERR_WELDER_CONTINUITY_LAPSED, 422,
                       "Welder qualification continuity has lapsed at weld-pass time")
    # Gate 2: lot usability (ISSUED and process-compatible with the joint's WPS)
    wps = db.wps.get(joint["wps_id"])
    if lot["status"] != "ISSUED" or wps is None or lot["process"] != wps["process"]:
        raise ApiError(ERR_LOT_NOT_USABLE, 422,
                       "Lot status not usable for weld-pass consumption")
    # Gate 3: weldment posture must be OPEN
    wm = db.weldments.get(joint["weldment_id"])
    if wm is None or wm["posture"] != "OPEN":
        raise ApiError(ERR_WELDMENT_NOT_OPEN, 409,
                       "Weldment posture not OPEN; weld-pass blocked")
    record = stamp_new({
        "shop_id": shop["id"],
        "joint_id": joint["id"],
        "welder_id": welder["id"],
        "qualification_id": qual["id"],
        "consumable_lot_id": lot["id"],
        "consumable_used_kg": used,
        "is_repair": body["is_repair"],
        "welded_at_utc": now,
    })
    db.weld_passes[record["id"]] = record
    # fan-out: qualification continuity clock refresh
    qual["last_weld_at_utc"] = now
    qual["continuity_expires_at_utc"] = compute_continuity_expiry(
        qual["qualified_at_utc"], now)
    mutate(qual)
    # fan-out: lot drawdown; zero -> EXHAUSTED
    lot["remaining_kg"] -= used
    if lot["remaining_kg"] <= 0:
        lot["status"] = "EXHAUSTED"
    mutate(lot)
    # fan-out: weldment counters, rate, repair-review gate
    wm["total_pass_count"] += 1
    if body["is_repair"]:
        wm["repair_pass_count"] += 1
    recompute_repair_rate(wm)
    check_repair_review_gate(wm, shop)
    mutate(wm)
    # fan-out: first pass on a joint opens the VT hold point
    if joint["inspection_status"] == "NOT_READY":
        joint["inspection_status"] = "READY_FOR_VT"
        mutate(joint)
    return success_object(weld_pass_out(record), status=201)


@bp.route("/weld-shop/shops/<shop_id>/joints/<joint_id>/weld-passes", methods=["GET"])
@require_any
def list_weld_passes(user_id, role, shop_id, joint_id):
    get_shop(shop_id)
    joint = get_joint(shop_id, joint_id)
    records = [p for p in db.weld_passes.values() if p["joint_id"] == joint["id"]]
    page, limit, offset, total = paginate(records)
    return success_list([weld_pass_out(p) for p in page], limit, offset, total)

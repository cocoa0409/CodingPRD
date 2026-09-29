"""Dealers, legacy fleet imports, recall campaigns and remedy tasks (PRD 3.8, 3.9)."""

from flask import Blueprint

import shapes
from db import (by_creation, db, get_or_404, make_record, now_dt, now_iso,
                public, touch, values)
from errors import ApiError
from middleware import (COMPLIANCE_OFFICER, CONTRACTS_ADMIN, DEALER_AGENT,
                        actor)
from response import created, list_response, object_response, q_enum, q_str
from services import calc, domain

bp = Blueprint("network", __name__)

STANDINGS = ("GOOD", "RESTRICTED", "SUSPENDED")
CAMPAIGN_STATUSES = ("DRAFT", "LAUNCHED", "COMPLETED")
TASK_STATUSES = ("OPEN", "IN_PROGRESS", "COMPLETED", "CANCELLED")
ESCALATION_LEVELS = ("DEALER_DIRECTED", "FACTORY_DIRECTED")


# ------------------------------------------------------------------- dealers

@bp.post("/dealers")
def create_dealer():
    actor(CONTRACTS_ADMIN)
    data = shapes.body()
    fields = {
        "dealer_code": shapes.get_str(data, "dealer_code"),
        "dealer_name": shapes.get_str(data, "dealer_name"),
        "licensed_state_codes": shapes.get_str_array(
            data, "licensed_state_codes", pattern=shapes.STATE_CODE_RE),
        "training_capacity_per_month": shapes.get_int(
            data, "training_capacity_per_month", minimum=0),
        "delivered_unit_count": 0,
        "open_recall_unit_count": 0,
        "certification_standing": "GOOD",
    }
    if domain.code_exists(db.dealers, "dealer_code", fields["dealer_code"]):
        raise ApiError("ERR_DUPLICATE_CODE", "dealer_code is already registered.")
    dealer = make_record(fields)
    db.dealers[dealer["id"]] = dealer
    return created(public(dealer))


@bp.get("/dealers")
def list_dealers():
    actor()
    standing = q_enum("certification_standing", STANDINGS)
    rows = [d for d in values(db.dealers)
            if standing is None or d["certification_standing"] == standing]
    return list_response(by_creation(rows))


@bp.get("/dealers/<dealer_id>")
def read_dealer(dealer_id):
    actor()
    dealer = get_or_404(db.dealers, dealer_id, "ERR_DEALER_NOT_FOUND")
    return object_response(public(dealer))


@bp.post("/dealers/<dealer_id>/legacy-fleet-records")
def create_legacy_record(dealer_id):
    actor(CONTRACTS_ADMIN)
    data = shapes.body()
    model_id = shapes.get_str(data, "bus_model_id")
    package_id = shapes.get_str(data, "propulsion_package_id")
    profile_id = shapes.get_str(data, "spec_profile_id")
    vin = shapes.get_str(data, "vin")
    delivered_raw, delivered_dt = shapes.get_instant(data, "delivered_at")

    profile = get_or_404(db.profiles, profile_id, "ERR_SPEC_PROFILE_NOT_FOUND")
    model = get_or_404(db.models, model_id, "ERR_BUS_MODEL_NOT_FOUND")
    package = get_or_404(db.packages, package_id, "ERR_PROPULSION_PACKAGE_NOT_FOUND")
    dealer = get_or_404(db.dealers, dealer_id, "ERR_DEALER_NOT_FOUND")

    if delivered_dt > now_dt():
        raise ApiError("ERR_INVALID_BUILD_WINDOW",
                       "delivered_at may not be later than the logical clock.")
    if package["compatible_bus_model_id"] != model["id"]:
        raise ApiError("ERR_PROPULSION_MODEL_INCOMPATIBLE")
    if profile["state_code"] not in dealer["licensed_state_codes"]:
        raise ApiError("ERR_DEALER_NOT_LICENSED_IN_STATE")
    if domain.vin_exists(vin):
        raise ApiError("ERR_VIN_ALREADY_EXISTS")

    base = {
        "seat_capacity": int(model["base_seat_capacity"]),
        "emergency_exit_count": int(model["base_emergency_exit_count"]),
        "mirror_config": "STANDARD",
        "lap_shoulder_belts": False,
        "eight_lamp_system": False,
        "crossing_arm": False,
        "rollover_reinforcement": False,
    }
    cfg = calc.upgrade_config(base, profile)
    nominal, derated = calc.range_validation(package, profile)
    unit = make_record({
        "contract_order_id": None,
        "bus_model_id": model["id"],
        "propulsion_package_id": package["id"],
        "spec_profile_id": profile["id"],
        "dealer_id": dealer["id"],
        "vin": vin,
        "seat_capacity": cfg["seat_capacity"],
        "emergency_exit_count": cfg["emergency_exit_count"],
        "mirror_config": cfg["mirror_config"],
        "lap_shoulder_belts": cfg["lap_shoulder_belts"],
        "eight_lamp_system": cfg["eight_lamp_system"],
        "crossing_arm": cfg["crossing_arm"],
        "rollover_reinforcement": cfg["rollover_reinforcement"],
        "joint_strength_kn": calc.joint_strength_kn(model, cfg["rollover_reinforcement"]),
        "registration_state_code": profile["state_code"],
        "nominal_range_mi": nominal,
        "derated_route_range_mi": derated,
        "production_status": "DELIVERED",
        "certification_status": "CERTIFIED",
        "service_status": "NONE",
        "driver_training_status": "COMPLETED",
        "certified_at": None,
        "delivered_at": delivered_raw,
        "waiver_justification": None,
        "is_legacy_import": True,
    })
    db.units[unit["id"]] = unit
    domain.recompute_dealer(dealer)
    return created(public(unit))


# ----------------------------------------------------------- recall campaigns

@bp.post("/recall-campaigns")
def create_campaign():
    actor(COMPLIANCE_OFFICER)
    data = shapes.body()
    code = shapes.get_str(data, "campaign_code")
    model_id = shapes.get_str(data, "affected_bus_model_id")
    propulsion = shapes.get_enum(data, "affected_propulsion_type", calc.PROPULSION_TYPES)
    defect = shapes.get_enum(data, "defect_category", calc.DEFECT_CATEGORIES)
    start_raw, start_date = shapes.get_date(data, "build_window_start")
    end_raw, end_date = shapes.get_date(data, "build_window_end")
    kits_per_unit = shapes.get_int(data, "kits_per_unit", minimum=1)
    total_kits = shapes.get_int(data, "total_kits", minimum=1)

    get_or_404(db.models, model_id, "ERR_BUS_MODEL_NOT_FOUND")
    if end_date < start_date:
        raise ApiError("ERR_INVALID_BUILD_WINDOW",
                       "build_window_end must not precede build_window_start.")
    if domain.code_exists(db.campaigns, "campaign_code", code):
        raise ApiError("ERR_DUPLICATE_CODE", "campaign_code is already registered.")

    campaign = make_record({
        "campaign_code": code,
        "affected_bus_model_id": model_id,
        "affected_propulsion_type": propulsion,
        "defect_category": defect,
        "build_window_start": start_raw,
        "build_window_end": end_raw,
        "kits_per_unit": kits_per_unit,
        "total_kits": total_kits,
        "affected_unit_count": 0,
        "reserved_kits": 0,
        "consumed_kits": 0,
        "available_kits": total_kits,
        "escalated_task_count": 0,
        "kit_shortfall_count": 0,
        "status": "DRAFT",
        "launched_at": None,
    })
    db.campaigns[campaign["id"]] = campaign
    return created(public(campaign))


@bp.get("/recall-campaigns")
def list_campaigns():
    actor()
    model_id = q_str("affected_bus_model_id")
    propulsion = q_enum("affected_propulsion_type", calc.PROPULSION_TYPES)
    status = q_enum("status", CAMPAIGN_STATUSES)
    rows = []
    for campaign in values(db.campaigns):
        if model_id is not None and campaign["affected_bus_model_id"] != model_id:
            continue
        if propulsion is not None and campaign["affected_propulsion_type"] != propulsion:
            continue
        if status is not None and campaign["status"] != status:
            continue
        rows.append(campaign)
    return list_response(by_creation(rows))


@bp.get("/recall-campaigns/<campaign_id>")
def read_campaign(campaign_id):
    actor()
    campaign = get_or_404(db.campaigns, campaign_id, "ERR_RECALL_CAMPAIGN_NOT_FOUND")
    return object_response(public(campaign))


def _recall_scope(campaign):
    """PRD 3.9 recall_scope: the delivered fleet inside the closed window."""
    window_start = domain.to_date(campaign["build_window_start"])
    window_end = domain.to_date(campaign["build_window_end"])
    scoped = []
    for unit in values(db.units):
        if unit["bus_model_id"] != campaign["affected_bus_model_id"]:
            continue
        package = db.packages.get(unit["propulsion_package_id"])
        if package is None or package["propulsion_type"] != campaign["affected_propulsion_type"]:
            continue
        if unit["production_status"] != "DELIVERED":
            continue
        if not unit.get("dealer_id"):
            continue
        delivered = unit.get("delivered_at")
        if not delivered:
            continue
        delivered_date = domain.to_date(delivered)
        if delivered_date < window_start or delivered_date > window_end:
            continue
        scoped.append(unit)
    scoped.sort(key=lambda u: (domain.to_date(u["delivered_at"]), u["delivered_at"],
                               u["created_at"], u["_seq"]))
    return scoped


@bp.post("/recall-campaigns/<campaign_id>/launch")
def launch_campaign(campaign_id):
    actor(COMPLIANCE_OFFICER)
    campaign = get_or_404(db.campaigns, campaign_id, "ERR_RECALL_CAMPAIGN_NOT_FOUND")
    if campaign["status"] != "DRAFT":
        raise ApiError("ERR_CAMPAIGN_NOT_DRAFT",
                       "Only a DRAFT campaign can be launched.")
    scope = _recall_scope(campaign)
    if len(scope) < 1:
        raise ApiError("ERR_NO_AFFECTED_UNITS")
    kits_per_unit = int(campaign["kits_per_unit"])
    if int(campaign["total_kits"]) < len(scope) * kits_per_unit:
        raise ApiError("ERR_INSUFFICIENT_REMEDY_KITS")

    campaign["launched_at"] = now_iso()
    campaign["affected_unit_count"] = len(scope)
    campaign["status"] = "LAUNCHED"

    dealer_order = []
    for unit in scope:
        task = make_record({
            "recall_campaign_id": campaign["id"],
            "bus_unit_id": unit["id"],
            "dealer_id": unit["dealer_id"],
            "kits_reserved": kits_per_unit,
            "escalation_level": "DEALER_DIRECTED",
            "status": "OPEN",
            "completed_at": None,
        })
        db.tasks[task["id"]] = task
        unit["service_status"] = "RECALL_OPEN"
        touch(unit)
        if unit["dealer_id"] not in dealer_order:
            dealer_order.append(unit["dealer_id"])

    domain.recompute_campaign(campaign)
    for dealer_id in dealer_order:
        domain.recompute_dealer(db.dealers.get(dealer_id))
    return object_response(public(campaign))


# --------------------------------------------------------------- remedy tasks

@bp.get("/remedy-tasks")
def list_tasks():
    actor()
    campaign_id = q_str("recall_campaign_id")
    unit_id = q_str("bus_unit_id")
    dealer_id = q_str("dealer_id")
    status = q_enum("status", TASK_STATUSES)
    level = q_enum("escalation_level", ESCALATION_LEVELS)
    rows = []
    for task in values(db.tasks):
        if campaign_id is not None and task["recall_campaign_id"] != campaign_id:
            continue
        if unit_id is not None and task["bus_unit_id"] != unit_id:
            continue
        if dealer_id is not None and task["dealer_id"] != dealer_id:
            continue
        if status is not None and task["status"] != status:
            continue
        if level is not None and task["escalation_level"] != level:
            continue
        rows.append(task)
    return list_response(by_creation(rows))


@bp.get("/remedy-tasks/<task_id>")
def read_task(task_id):
    actor()
    task = get_or_404(db.tasks, task_id, "ERR_REMEDY_TASK_NOT_FOUND")
    return object_response(public(task))


def _settle_task(task):
    """Shared post-terminal recomputation for complete and cancel."""
    campaign = db.campaigns.get(task["recall_campaign_id"])
    if campaign is not None:
        domain.recompute_campaign(campaign)
    unit = db.units.get(task["bus_unit_id"])
    if unit is not None:
        domain.refresh_unit_service_status(unit)
    domain.recompute_dealer(db.dealers.get(task["dealer_id"]))
    if campaign is not None:
        domain.close_campaign_if_complete(campaign)


@bp.post("/remedy-tasks/<task_id>/start")
def start_task(task_id):
    user_id, _role = actor(DEALER_AGENT)
    task = get_or_404(db.tasks, task_id, "ERR_REMEDY_TASK_NOT_FOUND")
    if task["dealer_id"] != user_id:
        raise ApiError("ERR_NOT_ASSIGNED_DEALER")
    if task["status"] != "OPEN":
        raise ApiError("ERR_TASK_STATE_INVALID", "Only an OPEN remedy task can be started.")
    task["status"] = "IN_PROGRESS"
    touch(task)
    return object_response(public(task))


@bp.post("/remedy-tasks/<task_id>/complete")
def complete_task(task_id):
    user_id, _role = actor(DEALER_AGENT)
    task = get_or_404(db.tasks, task_id, "ERR_REMEDY_TASK_NOT_FOUND")
    if task["dealer_id"] != user_id:
        raise ApiError("ERR_NOT_ASSIGNED_DEALER")
    if task["status"] not in ("OPEN", "IN_PROGRESS"):
        raise ApiError("ERR_TASK_STATE_INVALID",
                       "Only an OPEN or IN_PROGRESS remedy task can be completed.")
    task["status"] = "COMPLETED"
    task["completed_at"] = now_iso()
    touch(task)
    _settle_task(task)
    return object_response(public(task))


@bp.post("/remedy-tasks/<task_id>/cancel")
def cancel_task(task_id):
    actor(COMPLIANCE_OFFICER)
    task = get_or_404(db.tasks, task_id, "ERR_REMEDY_TASK_NOT_FOUND")
    if task["status"] not in ("OPEN", "IN_PROGRESS"):
        raise ApiError("ERR_TASK_STATE_INVALID",
                       "Only an OPEN or IN_PROGRESS remedy task can be cancelled.")
    task["status"] = "CANCELLED"
    touch(task)
    _settle_task(task)
    return object_response(public(task))

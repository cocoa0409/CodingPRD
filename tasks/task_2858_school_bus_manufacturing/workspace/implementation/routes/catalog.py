"""Specification profiles, bus models and propulsion packages (PRD 3.1, 3.2)."""

from flask import Blueprint

import shapes
from db import (by_creation, db, get_or_404, make_record, now_iso, public,
                touch, values)
from errors import ApiError
from middleware import COMPLIANCE_OFFICER, actor
from response import created, list_response, object_response, q_enum, q_str
from services import calc, domain

bp = Blueprint("catalog", __name__)

PROFILE_STATUSES = ("DRAFT", "PUBLISHED", "SUPERSEDED")


# --------------------------------------------------------- spec profiles

@bp.post("/state-spec-profiles")
def create_profile():
    actor(COMPLIANCE_OFFICER)
    data = shapes.body()
    fields = {
        "state_code": shapes.get_str(data, "state_code", pattern=shapes.STATE_CODE_RE),
        "school_year": shapes.get_str(data, "school_year", pattern=shapes.SCHOOL_YEAR_RE),
        "status": "DRAFT",
        "min_seat_capacity": shapes.get_int(data, "min_seat_capacity", minimum=1),
        "requires_eight_lamp_system": shapes.get_bool(
            data, "requires_eight_lamp_system", required=False, default=False),
        "requires_crossing_arm": shapes.get_bool(
            data, "requires_crossing_arm", required=False, default=False),
        "required_mirror_config": shapes.get_enum(
            data, "required_mirror_config", calc.MIRROR_CONFIGS, required=False,
            default="STANDARD"),
        "requires_lap_shoulder_belts": shapes.get_bool(
            data, "requires_lap_shoulder_belts", required=False, default=False),
        "min_emergency_exit_count": shapes.get_int(data, "min_emergency_exit_count", minimum=1),
        "min_joint_strength_kn": shapes.get_number(
            data, "min_joint_strength_kn", exclusive_minimum=0),
        "requires_rollover_protection": shapes.get_bool(
            data, "requires_rollover_protection", required=False, default=False),
        "requires_joint_strength_test": shapes.get_bool(
            data, "requires_joint_strength_test", required=False, default=False),
        "required_route_range_mi": shapes.get_number(
            data, "required_route_range_mi", exclusive_minimum=0),
        "terrain_class": shapes.get_enum(
            data, "terrain_class", calc.TERRAIN_CLASSES, required=False, default="FLAT"),
        "published_at": None,
        "superseded_by_profile_id": None,
    }
    profile = make_record(fields)
    db.profiles[profile["id"]] = profile
    return created(public(profile))


@bp.get("/state-spec-profiles")
def list_profiles():
    actor()
    state_code = q_str("state_code")
    school_year = q_str("school_year")
    status = q_enum("status", PROFILE_STATUSES)
    superseded_by = q_str("superseded_by_profile_id")
    rows = []
    for profile in values(db.profiles):
        if state_code is not None and profile["state_code"] != state_code:
            continue
        if school_year is not None and profile["school_year"] != school_year:
            continue
        if status is not None and profile["status"] != status:
            continue
        if superseded_by is not None and profile["superseded_by_profile_id"] != superseded_by:
            continue
        rows.append(profile)
    return list_response(by_creation(rows))


@bp.get("/state-spec-profiles/<pid>")
def read_profile(pid):
    actor()
    profile = get_or_404(db.profiles, pid, "ERR_SPEC_PROFILE_NOT_FOUND")
    return object_response(public(profile))


@bp.post("/state-spec-profiles/<pid>/publish")
def publish_profile(pid):
    actor(COMPLIANCE_OFFICER)
    profile = get_or_404(db.profiles, pid, "ERR_SPEC_PROFILE_NOT_FOUND")
    if profile["status"] != "DRAFT":
        raise ApiError("ERR_PROFILE_NOT_DRAFT")
    previous = domain.published_profile(profile["state_code"], profile["school_year"])
    profile["status"] = "PUBLISHED"
    profile["published_at"] = now_iso()
    touch(profile)
    if previous is not None and previous["id"] != profile["id"]:
        previous["status"] = "SUPERSEDED"
        previous["superseded_by_profile_id"] = profile["id"]
        touch(previous)
    return object_response(public(profile))


# ------------------------------------------------------------- bus models

@bp.post("/bus-models")
def create_model():
    actor(COMPLIANCE_OFFICER)
    data = shapes.body()
    fields = {
        "model_code": shapes.get_str(data, "model_code"),
        "body_class": shapes.get_enum(data, "body_class", calc.BODY_CLASSES),
        "base_seat_capacity": shapes.get_int(data, "base_seat_capacity", minimum=1),
        "base_emergency_exit_count": shapes.get_int(data, "base_emergency_exit_count", minimum=1),
        "base_price_cents": shapes.get_int(data, "base_price_cents", minimum=1),
        "body_joint_strength_kn": shapes.get_number(
            data, "body_joint_strength_kn", exclusive_minimum=0),
        "max_battery_bays": shapes.get_int(data, "max_battery_bays", minimum=0),
        "curb_weight_lb": shapes.get_int(data, "curb_weight_lb", minimum=1),
    }
    if domain.code_exists(db.models, "model_code", fields["model_code"]):
        raise ApiError("ERR_DUPLICATE_CODE", "model_code is already registered.")
    model = make_record(fields)
    db.models[model["id"]] = model
    return created(public(model))


@bp.get("/bus-models")
def list_models():
    actor()
    body_class = q_enum("body_class", calc.BODY_CLASSES)
    rows = [m for m in values(db.models)
            if body_class is None or m["body_class"] == body_class]
    return list_response(by_creation(rows))


@bp.get("/bus-models/<mid>")
def read_model(mid):
    actor()
    model = get_or_404(db.models, mid, "ERR_BUS_MODEL_NOT_FOUND")
    return object_response(public(model))


# ------------------------------------------------------ propulsion packages

@bp.post("/propulsion-packages")
def create_package():
    actor(COMPLIANCE_OFFICER)
    data = shapes.body()
    fields = {
        "package_code": shapes.get_str(data, "package_code"),
        "compatible_bus_model_id": shapes.get_str(data, "compatible_bus_model_id"),
        "propulsion_type": shapes.get_enum(data, "propulsion_type", calc.PROPULSION_TYPES),
        "option_price_cents": shapes.get_int(data, "option_price_cents", minimum=0),
        "battery_pack_count": shapes.get_int(
            data, "battery_pack_count", required=False, default=0, minimum=0),
        "usable_kwh": shapes.get_number(data, "usable_kwh", required=False, default=0, minimum=0),
        "nominal_consumption_kwh_per_mi": shapes.get_number(
            data, "nominal_consumption_kwh_per_mi", required=False, default=0, minimum=0),
        "hvac_load_kw": shapes.get_number(
            data, "hvac_load_kw", required=False, default=0, minimum=0),
        "fuel_capacity_gal": shapes.get_number(
            data, "fuel_capacity_gal", required=False, default=0, minimum=0),
        "rated_mpg": shapes.get_number(data, "rated_mpg", required=False, default=0, minimum=0),
        "cold_weather_derate_pct": shapes.get_number(
            data, "cold_weather_derate_pct", minimum=0, exclusive_maximum=1),
        "reserve_floor_pct": shapes.get_number(
            data, "reserve_floor_pct", minimum=0, exclusive_maximum=1),
    }
    model = get_or_404(db.models, fields["compatible_bus_model_id"], "ERR_BUS_MODEL_NOT_FOUND")
    if (fields["propulsion_type"] == "ELECTRIC"
            and int(fields["battery_pack_count"]) > int(model["max_battery_bays"])):
        raise ApiError("ERR_BATTERY_BAY_CAPACITY_EXCEEDED")
    if domain.code_exists(db.packages, "package_code", fields["package_code"]):
        raise ApiError("ERR_DUPLICATE_CODE", "package_code is already registered.")
    ordered = {
        "package_code": fields["package_code"],
        "compatible_bus_model_id": fields["compatible_bus_model_id"],
        "propulsion_type": fields["propulsion_type"],
        "option_price_cents": fields["option_price_cents"],
        "battery_pack_count": fields["battery_pack_count"],
        "usable_kwh": fields["usable_kwh"],
        "nominal_consumption_kwh_per_mi": fields["nominal_consumption_kwh_per_mi"],
        "hvac_load_kw": fields["hvac_load_kw"],
        "fuel_capacity_gal": fields["fuel_capacity_gal"],
        "rated_mpg": fields["rated_mpg"],
        "cold_weather_derate_pct": fields["cold_weather_derate_pct"],
        "reserve_floor_pct": fields["reserve_floor_pct"],
    }
    package = make_record(ordered)
    db.packages[package["id"]] = package
    return created(public(package))


@bp.get("/propulsion-packages")
def list_packages():
    actor()
    model_id = q_str("compatible_bus_model_id")
    propulsion = q_enum("propulsion_type", calc.PROPULSION_TYPES)
    rows = []
    for package in values(db.packages):
        if model_id is not None and package["compatible_bus_model_id"] != model_id:
            continue
        if propulsion is not None and package["propulsion_type"] != propulsion:
            continue
        rows.append(package)
    return list_response(by_creation(rows))


@bp.get("/propulsion-packages/<pkg_id>")
def read_package(pkg_id):
    actor()
    package = get_or_404(db.packages, pkg_id, "ERR_PROPULSION_PACKAGE_NOT_FOUND")
    return object_response(public(package))

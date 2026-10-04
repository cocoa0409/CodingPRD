"""Reservoir (singleton) and EnvironmentalConstraints (PRD sections 3.1, 3.5)."""
from decimal import Decimal

from flask import Blueprint, request

from calc import windows_intersect
from auth import ALL_ROLES, authenticate
from envelope import list_response, success
from errors import ApiError, not_found
from serial import constraint_view, reservoir_view
from store import DB, new_record
from validate import (as_datetime, as_enum, as_int_range, as_number, as_str,
                      get_body, required)

bp = Blueprint("reservoirs", __name__)

SPECIES = ("SALMON", "SMELT", "STURGEON")
REQUIREMENT_TYPES = ("MIN_FLOW", "PULSE_FLOW", "MAX_RELEASE")


def reservoir_or_404(reservoir_id):
    reservoir = DB["reservoirs"].get(reservoir_id)
    if reservoir is None:
        not_found("Reservoir")
    return reservoir


@bp.post("/water/reservoirs")
def create_reservoir():
    authenticate(["SystemAdmin"])
    body = get_body()
    name = as_str(required(body, "name"), "name")
    capacity = as_int_range(required(body, "capacity_af"), "capacity_af", 1)
    dead_pool = as_int_range(required(body, "dead_pool_af"), "dead_pool_af", 0)
    flood_max = as_int_range(required(body, "flood_control_max_storage_af"),
                             "flood_control_max_storage_af", 1)
    initial = as_int_range(required(body, "initial_storage_af"),
                           "initial_storage_af", 0)
    outlet = as_int_range(required(body, "outlet_capacity_cfs"),
                          "outlet_capacity_cfs", 1)
    power = as_number(required(body, "power_conversion_mwh_per_af"),
                      "power_conversion_mwh_per_af")
    if dead_pool >= capacity:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "dead_pool_af must be strictly below capacity_af")
    if initial > capacity:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "initial_storage_af must not exceed capacity_af")
    if power <= Decimal(0):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "power_conversion_mwh_per_af must be > 0")
    # singleton project reservoir
    if DB["reservoirs"]:
        raise ApiError("ERR_RESERVOIR_ALREADY_EXISTS", 409,
                       "the project reservoir already exists")
    rec = new_record()
    rec.update({
        "name": name,
        "capacity_af": capacity,
        "dead_pool_af": dead_pool,
        "flood_control_max_storage_af": flood_max,
        "initial_storage_af": initial,
        "current_storage_af": initial,
        "outlet_capacity_cfs": outlet,
        "power_conversion_mwh_per_af": power,
    })
    DB["reservoirs"][rec["id"]] = rec
    return success(reservoir_view(rec), 201)


@bp.get("/water/reservoirs/<string:reservoir_id>")
def get_reservoir(reservoir_id):
    authenticate(ALL_ROLES)
    return success(reservoir_view(reservoir_or_404(reservoir_id)))


@bp.post("/water/reservoirs/<string:reservoir_id>/environmental-constraints")
def create_constraint(reservoir_id):
    authenticate(["EnvironmentalOfficer"])
    body = get_body()
    species = as_enum(required(body, "species"), "species", SPECIES)
    req_type = as_enum(required(body, "requirement_type"), "requirement_type",
                       REQUIREMENT_TYPES)
    enforce_start = as_datetime(required(body, "enforce_start"), "enforce_start")
    enforce_end = as_datetime(required(body, "enforce_end"), "enforce_end")
    if enforce_start >= enforce_end:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "enforce_start must be strictly before enforce_end")
    required_min = None
    max_release = None
    if req_type in ("MIN_FLOW", "PULSE_FLOW"):
        required_min = as_int_range(required(body, "required_min_cfs"),
                                    "required_min_cfs", 1)
        if body.get("max_release_cfs") is not None:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "max_release_cfs is forbidden for " + req_type)
    else:
        max_release = as_int_range(required(body, "max_release_cfs"),
                                   "max_release_cfs", 1)
        if body.get("required_min_cfs") is not None:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "required_min_cfs is forbidden for MAX_RELEASE")
    reservoir = reservoir_or_404(reservoir_id)
    # pulse windows on the same reservoir must not strictly overlap; adjacency OK
    if req_type == "PULSE_FLOW":
        for existing in DB["constraints"].values():
            if (existing["reservoir_id"] == reservoir["id"]
                    and existing["requirement_type"] == "PULSE_FLOW"
                    and windows_intersect(enforce_start, enforce_end,
                                          existing["enforce_start"],
                                          existing["enforce_end"])):
                raise ApiError("ERR_PULSE_WINDOW_OVERLAP", 409,
                               "PULSE_FLOW window overlaps an existing pulse window")
    rec = new_record()
    rec.update({
        "reservoir_id": reservoir["id"],
        "species": species,
        "requirement_type": req_type,
        "required_min_cfs": required_min,
        "max_release_cfs": max_release,
        "enforce_start": enforce_start,
        "enforce_end": enforce_end,
    })
    DB["constraints"][rec["id"]] = rec
    return success(constraint_view(rec), 201)


@bp.get("/water/reservoirs/<string:reservoir_id>/environmental-constraints")
def list_constraints(reservoir_id):
    authenticate(ALL_ROLES)
    reservoir = reservoir_or_404(reservoir_id)
    filters = {
        "requirement_type": request.args.get("requirement_type"),
        "species": request.args.get("species"),
    }
    records = [c for c in DB["constraints"].values()
               if c["reservoir_id"] == reservoir["id"]]
    return list_response(records, constraint_view, filters)

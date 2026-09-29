"""Stocking destinations (PRD 3.6, first half)."""

from decimal import Decimal

from flask import Blueprint

import calc
import constants as K
import validators as v
from auth import authorize
from envelope import created, enum_filter, ok, pagination, paginate, str_filter
from errors import ApiError
from serialize import dump
from store import Tx, base_record, get_or_404, insert, sort_key, values

bp = Blueprint("water", __name__)

READ_ROLES = (K.PROGRAM_ADMIN, K.HATCHERY_MANAGER, K.VETERINARIAN,
              K.REGIONAL_BIOLOGIST, K.PUBLIC_REQUESTER)


@bp.post("/waters")
def create_water():
    authorize(K.PROGRAM_ADMIN)
    body = v.body()
    name = v.req_str(body, "name")
    county = v.req_str(body, "county")
    water_class = v.req_enum(body, "water_class", K.WATER_CLASSES)
    habitat_suitability_score = v.req_int(body, "habitat_suitability_score",
                                         minimum=Decimal(0), maximum=Decimal(100))
    angler_demand_index = v.req_int(body, "angler_demand_index",
                                   minimum=Decimal(0), maximum=Decimal(100))
    plan_species = v.req_enum(body, "plan_species", K.SPECIES)
    plan_target_count = v.req_int(body, "plan_target_count", minimum=Decimal(1))
    access_type = v.req_enum(body, "access_type", K.ACCESS_TYPES)

    record = base_record()
    record.update({
        "name": name,
        "county": county,
        "water_class": water_class,
        "habitat_suitability_score": habitat_suitability_score,
        "angler_demand_index": angler_demand_index,
        "plan_species": plan_species,
        "plan_target_count": plan_target_count,
        "access_type": access_type,
        "allocated_count_ytd": 0,
        "released_count_ytd": 0,
        "plan_shortfall_count": plan_target_count,
        "plan_fill_pct": calc.q2(0),
        "last_release_at": None,
        "status": "ACTIVE",
    })
    insert("waters", record)
    return created(dump(record))


@bp.get("/waters/<identifier>")
def get_water(identifier):
    authorize(*READ_ROLES)
    return ok(dump(get_or_404("waters", identifier)))


@bp.get("/waters")
def list_waters():
    authorize(*READ_ROLES)
    status = enum_filter("status", K.WATER_STATUSES)
    plan_species = enum_filter("plan_species", K.SPECIES)
    county = str_filter("county")
    limit, offset = pagination()

    records = values("waters")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    if plan_species is not None:
        records = [r for r in records if r["plan_species"] == plan_species]
    if county is not None:
        records = [r for r in records if r["county"] == county]
    records.sort(key=sort_key)
    return paginate(records, limit, offset, dump)


@bp.post("/waters/<identifier>/close")
def close_water(identifier):
    authorize(K.PROGRAM_ADMIN)
    water = get_or_404("waters", identifier)
    if water["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "This water is already closed.")
    tx = Tx()
    water["status"] = "CLOSED"
    tx.touch(water)
    tx.settle()
    return ok(dump(water))

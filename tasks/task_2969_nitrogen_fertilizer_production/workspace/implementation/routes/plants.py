"""Plants: registration, the gas index, permit standing and PSM standing (PRD 3.1 / 3.10)."""
from flask import Blueprint, request

import cascade
import serialize
import validate as v
from auth import ALL_ROLES, REGULATORY_ADMIN, SAFETY_OFFICER, actor
from envelope import list_response, object_response, paging
from guards import duplicate, load
from mutate import touch
from store import db, stamp_new

bp = Blueprint("plants", __name__)
PREFIX = "/nitrogen-ops/plants"


@bp.post(PREFIX)
def create_plant():
    actor([REGULATORY_ADMIN])
    body = v.get_body()
    name = v.s_str(body, "name", min_len=1, max_len=120)
    site_code = v.s_code(body, "site_code", 3, 12, upper_alnum=True)
    limit_tons = v.s_num(body, "permit_limit_tons_30d", 2, gt=0)
    spot = v.s_num(body, "spot_gas_index_usd_per_mmbtu", 4, gt=0)
    duplicate("plants", "site_code", site_code)
    row = {
        "name": name,
        "site_code": site_code,
        "permit_limit_tons_30d": limit_tons,
        "spot_gas_index_usd_per_mmbtu": spot,
        "gas_index_updated_at": db.clock,
        "permit_status": "ACTIVE",
        "psm_program_status": "CURRENT",
        "operating_posture": "NORMAL",
        "exceeded_pollutants": [],
        "last_vessel_inspection_at": None,
    }
    stamp_new(row)
    db.plants[row["id"]] = row
    return object_response(serialize.plant_json(row), 201)


@bp.get(PREFIX + "/<id>")
def get_plant(id):
    actor(ALL_ROLES)
    plant = load("plants", id)
    return object_response(serialize.plant_json(plant))


@bp.get(PREFIX)
def list_plants():
    actor(ALL_ROLES)
    limit, offset = paging(request.args)
    rows = db.rows("plants")
    return list_response(serialize.dump("plants", rows), limit, offset)


@bp.post(PREFIX + "/<id>/gas-index")
def post_gas_index(id):
    actor([REGULATORY_ADMIN])
    body = v.get_body()
    spot = v.s_num(body, "spot_gas_index_usd_per_mmbtu", 4, gt=0)
    plant = load("plants", id)
    plant["spot_gas_index_usd_per_mmbtu"] = spot
    plant["gas_index_updated_at"] = db.clock
    touch(plant)
    return object_response(serialize.plant_json(plant))


@bp.post(PREFIX + "/<id>/permit-status")
def post_permit_status(id):
    actor([REGULATORY_ADMIN])
    body = v.get_body()
    status = v.s_enum(body, "permit_status", ("ACTIVE", "SUSPENDED"))
    plant = load("plants", id)
    plant["permit_status"] = status
    touch(plant)
    cascade.rederive_posture(plant)
    return object_response(serialize.plant_json(plant))


@bp.post(PREFIX + "/<id>/psm-program-status")
def post_psm_program_status(id):
    actor([SAFETY_OFFICER])
    body = v.get_body()
    status = v.s_enum(body, "psm_program_status", ("CURRENT", "DUE", "OVERDUE"))
    plant = load("plants", id)
    plant["psm_program_status"] = status
    touch(plant)
    cascade.rederive_posture(plant)
    return object_response(serialize.plant_json(plant))

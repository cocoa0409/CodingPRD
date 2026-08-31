"""Material category endpoints (PRD §3.1)."""

from flask import Blueprint, request

import serializers
from common import list_response
from envelope import ok
from errors import ApiError
from rollups import refresh_world
from store import new_row, store
from validation import (
    ALL_READ_ROLES,
    authorize,
    body,
    context,
    lookup,
    opt_str,
    req_enum,
    req_int,
    req_num,
    req_str,
)

bp = Blueprint("material_categories", __name__)

ACCEPTANCE_POLICIES = ["ACCEPTED_WITH_LIMIT", "REJECTED_ALWAYS"]
COMPATIBILITY_CLASSES = [
    "FLAMMABLE",
    "CORROSIVE_ACID",
    "CORROSIVE_BASE",
    "OXIDIZER",
    "TOXIC",
    "AEROSOL",
    "UNIVERSAL_WASTE",
]
DEFAULT_REFERRAL_PROGRAM_CODE = "CESQG-DROPOFF"


@bp.post("/hhw/material-categories")
def create_material_category():
    user_id, role = context()
    authorize(role, ["ProgramAdmin"])
    payload = body()
    program_id = req_str(payload, "program_id")
    code = req_str(payload, "code")
    display_name = req_str(payload, "display_name")
    acceptance_policy = req_enum(payload, "acceptance_policy", ACCEPTANCE_POLICIES)
    compatibility_class = req_enum(payload, "compatibility_class", COMPATIBILITY_CLASSES)
    dot_hazard_class = req_str(payload, "dot_hazard_class")
    max_event = req_num(payload, "max_kg_per_resident_per_event", gt=0)
    max_year = req_num(payload, "max_kg_per_resident_per_year", gt=0)
    rate = req_int(payload, "disposal_rate_cents_per_kg", minimum=0)
    referral = opt_str(payload, "business_referral_program_code",
                       DEFAULT_REFERRAL_PROGRAM_CODE)

    program = lookup("program", program_id)

    for existing in store.material_categories.values():
        if existing["program_id"] == program["id"] and existing["code"] == code:
            raise ApiError("ERR_INVALID_REQUEST",
                           "code must be unique within the program.")

    row = new_row({
        "program_id": program["id"],
        "code": code,
        "display_name": display_name,
        "acceptance_policy": acceptance_policy,
        "compatibility_class": compatibility_class,
        "dot_hazard_class": dot_hazard_class,
        "max_kg_per_resident_per_event": max_event,
        "max_kg_per_resident_per_year": max_year,
        "disposal_rate_cents_per_kg": rate,
        "business_referral_program_code": referral,
    })
    store.material_categories[row["id"]] = row
    refresh_world()
    return ok(serializers.material_category(row), 201)


@bp.get("/hhw/material-categories")
def list_material_categories():
    user_id, role = context()
    authorize(role, ALL_READ_ROLES)
    filters = {
        "program_id": request.args.get("program_id"),
        "acceptance_policy": request.args.get("acceptance_policy"),
        "compatibility_class": request.args.get("compatibility_class"),
    }
    return list_response(request.args, list(store.material_categories.values()),
                         serializers.material_category, filters)


@bp.get("/hhw/material-categories/<category_id>")
def read_material_category(category_id):
    user_id, role = context()
    authorize(role, ALL_READ_ROLES)
    return ok(serializers.material_category(lookup("material_category", category_id)))

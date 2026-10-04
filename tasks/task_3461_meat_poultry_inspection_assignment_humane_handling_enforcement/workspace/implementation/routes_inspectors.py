"""Inspectors (PRD §3.2): onboarding and deactivation."""
from flask import Blueprint

import store
from authz import require_roles
from cascades import cascade_inspector_deactivation
from envelope import get_body, success_object
from errors import raise_err, ERR_INSPECTOR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE
from guards import entity_or_404
from store import insert, stamp_new, touch
from validate import SPECIES_ENUM, require_string, require_string_array

bp = Blueprint("inspectors", __name__)


@bp.post("/inspection/inspectors")
def create_inspector():
    require_roles("ProgramAdministrator")
    body = get_body()
    full_name = require_string(body, "full_name")
    badge_number = require_string(body, "badge_number")
    species_qualifications = require_string_array(body, "species_qualifications", members=SPECIES_ENUM)

    # Badge numbers are unique across the agency.
    for existing in store.all_of("inspectors"):
        if existing["badge_number"] == badge_number:
            raise_err(ERR_INVALID_REQUEST, "badge_number already in use")

    inspector = {
        "full_name": full_name,
        "badge_number": badge_number,
        "species_qualifications": list(species_qualifications),
        "employment_status": "ACTIVE",
    }
    stamp_new(inspector)
    insert("inspectors", inspector)
    return success_object(inspector, status=201)


@bp.post("/inspection/inspectors/<inspector_id>/deactivate")
def deactivate_inspector(inspector_id):
    require_roles("ProgramAdministrator")
    inspector = entity_or_404("inspectors", inspector_id, ERR_INSPECTOR_NOT_FOUND)
    if inspector["employment_status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "deactivate requires employment_status ACTIVE")
    inspector["employment_status"] = "INACTIVE"
    touch(inspector)
    cascade_inspector_deactivation(inspector)
    return success_object(inspector)
